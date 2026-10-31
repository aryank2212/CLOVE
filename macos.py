"""macOS versions of the desktop actions in desktop.py, deskctx.py, dictate.py and screen.py.

Everything here uses what ships with macOS (open, osascript, pbcopy/pbpaste, screencapture, lsof) plus Homebrew for
installs, so CLOVE needs no extra system tools on a Mac. Three macOS permissions matter, each asked for once:
- Accessibility: window control, typing dictated text, media keys (System Settings > Privacy & Security > Accessibility)
- Screen Recording: screenshots and window titles (… > Screen & System Audio Recording)
- Microphone: hearing you (… > Microphone)
They are granted to the app that runs CLOVE: Terminal (or iTerm) when started by hand, Python for the login agent.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CHROME_APP = "Google Chrome"
CHROME_DIR = Path.home() / "Library/Application Support/Google/Chrome"
APP_DIRS = [Path("/Applications"), Path("/Applications/Utilities"), Path("/System/Applications"),
            Path("/System/Applications/Utilities"), Path.home() / "Applications", Path("/System/Library/CoreServices")]
BREW_PATHS = ["/opt/homebrew/bin", "/usr/local/bin"]
PERMISSION = {
    "accessibility": "System Settings > Privacy & Security > Accessibility",
    "screen": "System Settings > Privacy & Security > Screen & System Audio Recording",
    "microphone": "System Settings > Privacy & Security > Microphone",
}


def add_brew_to_path():
    """A login agent starts with a bare PATH; Homebrew's tools (ollama, claude via node, brew itself) live here."""
    parts = os.environ.get("PATH", "").split(":")
    for p in reversed(BREW_PATHS + [str(Path.home() / ".local/bin")]):
        if p not in parts and os.path.isdir(p):
            parts.insert(0, p)
    os.environ["PATH"] = ":".join(x for x in parts if x)


# ---- AppleScript ---------------------------------------------------------------------------------
def q(s: str) -> str:
    """A Python string as an AppleScript string literal."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def osascript(script: str, timeout: float = 10) -> tuple[int, str]:
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, "timed out"
    except OSError as e:
        return 1, str(e)
    return r.returncode, (r.stdout if r.returncode == 0 else r.stderr).strip()


def needs_permission(err: str) -> str:
    """Name the macOS permission an AppleScript error is about, or ''."""
    low = err.lower()
    if "-1719" in err or "-25211" in err or "assistive access" in low or "accessibility" in low:
        return "accessibility"
    if "-1743" in err or "not authorized to send apple events" in low:
        return "automation"
    return ""


def _perm_error(err: str, what: str) -> str:
    p = needs_permission(err)
    if p == "accessibility":
        return (f"error: {what} needs the Accessibility permission. Tell sir: open {PERMISSION['accessibility']} and turn "
                "on the app CLOVE runs in (Terminal, or Python for the login agent), then ask again.")
    if p == "automation":
        return (f"error: {what} needs permission to control other apps. Tell sir: open System Settings > Privacy & "
                "Security > Automation and allow it for the app CLOVE runs in.")
    return f"error: {what} failed ({err[:150]})"


def _detach(argv):
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def open_target(target: str):
    _detach(["open", target])


# ---- sound, media, clipboard, notifications --------------------------------------------------------
def volume(action: str, percent: int = 0) -> str:
    if action not in ("up", "down", "set", "mute", "unmute", "get"):
        return "error: action must be up, down, set, mute, unmute or get"
    code, out = osascript("output volume of (get volume settings) & \",\" & output muted of (get volume settings)")
    try:
        cur, muted = int(out.split(",")[0]), out.split(",")[1].strip() == "true"
    except (ValueError, IndexError):
        cur, muted = 50, False
    step = percent or 10
    new = {"up": cur + step, "down": cur - step, "set": percent}.get(action)
    if new is not None:
        osascript(f"set volume output volume {max(0, min(100, int(new)))} without output muted")
    elif action in ("mute", "unmute"):
        osascript(f"set volume {'with' if action == 'mute' else 'without'} output muted")
    code, out = osascript("output volume of (get volume settings) & \",\" & output muted of (get volume settings)")
    try:
        cur, muted = int(out.split(",")[0]), out.split(",")[1].strip() == "true"
    except (ValueError, IndexError):
        return f"error: couldn't read the volume ({out[:100]})"
    return f"volume {cur}%{' (muted)' if muted else ''}"


MEDIA_APPS = ("Spotify", "Music")
NX_KEYS = {"toggle": 16, "play": 16, "pause": 16, "next": 17, "previous": 18}


def _running(app: str) -> bool:
    code, out = osascript(f"application {q(app)} is running", 5)
    return code == 0 and out == "true"


def _media_key(action: str) -> bool:
    """Press the keyboard's play/next/previous key: macOS sends it to whatever is playing (Chrome/YouTube included)."""
    try:
        import Quartz
        from AppKit import NSEvent
    except ImportError:
        return False
    key = NX_KEYS[action]
    for down in (True, False):
        ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            14, (0, 0), 0xa00 if down else 0xb00, 0, 0, None, 8, (key << 16) | ((0xa if down else 0xb) << 8), -1)
        Quartz.CGEventPost(0, ev.CGEvent())
    return True


def media(action: str) -> str:
    verb = {"play": "play", "pause": "pause", "toggle": "playpause", "next": "next track",
            "previous": "previous track"}.get(action)
    if not verb:
        return "error: action must be play, pause, toggle, next or previous"
    running = [a for a in MEDIA_APPS if _running(a)]
    playing = next((a for a in running if osascript(f"tell application {q(a)} to player state as string", 5)[1]
                    == "playing"), None)
    # A music app that is playing (or the only player when nothing plays and he says play) gets the command directly.
    target = playing or (running[0] if running and action in ("play", "toggle") and not _browser_playing() else None)
    if target:
        code, out = osascript(f"tell application {q(target)} to {verb}", 5)
        return f"{action} sent to {target}" if code == 0 else _perm_error(out, "media control")
    if _media_key(action):
        return f"{action} sent to what is playing"
    return "no media player is running (Spotify or Music), and media keys need pyobjc (pip install pyobjc)"


def _browser_playing() -> bool:
    try:
        from browser_bridge import bridge
        return bool(bridge.connected and bridge.active.get("audible"))
    except Exception:
        return False


def clipboard(action: str, text: str = "") -> str:
    if action == "get":
        r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        return r.stdout[:4000] if r.stdout else "clipboard is empty"
    if action == "set":
        subprocess.run(["pbcopy"], input=text, text=True, timeout=5)
        return f"copied {len(text)} chars to the clipboard"
    return "error: action must be get or set"


def notify(title: str, body: str = ""):
    osascript(f"display notification {q(body)} with title {q(title)}", 5)


# ---- apps, terminals, Chrome -------------------------------------------------------------------------
APP_ALIASES = {
    "terminal": ["Ghostty", "iTerm", "Warp", "WezTerm", "kitty", "Alacritty", "Terminal"], "console": ["Terminal"],
    "files": ["Finder"], "file manager": ["Finder"], "explorer": ["Finder"], "finder": ["Finder"],
    "browser": [CHROME_APP, "Safari"], "chrome": [CHROME_APP], "google chrome": [CHROME_APP],
    "settings": ["System Settings", "System Preferences"], "system settings": ["System Settings", "System Preferences"],
    "text editor": ["TextEdit"], "editor": ["TextEdit"], "notes": ["Notes"],
    "vs code": ["Visual Studio Code"], "vscode": ["Visual Studio Code"], "visual studio code": ["Visual Studio Code"],
    "code": ["Visual Studio Code"], "calculator": ["Calculator"], "calendar": ["Calendar"], "mail": ["Mail"],
    "system monitor": ["Activity Monitor"], "task manager": ["Activity Monitor"], "activity monitor": ["Activity Monitor"],
    "app store": ["App Store"], "music": ["Music"], "photos": ["Photos"], "messages": ["Messages"],
}
TERMINAL_APPS = {"Terminal", "iTerm", "iTerm2", "Ghostty", "Warp", "WezTerm", "kitty", "Alacritty", "Hyper", "Tabby"}


def installed_apps() -> dict[str, Path]:
    """Display name -> .app bundle, for every app in the usual folders."""
    apps = {}
    for d in APP_DIRS:
        try:
            for p in d.glob("*.app"):
                apps.setdefault(p.stem, p)
        except OSError:
            pass
    return apps


def find_app(name: str, apps: dict[str, Path] | None = None) -> str:
    """The installed app's name that best matches what he said ('' if none)."""
    apps = installed_apps() if apps is None else apps
    q_ = name.lower().strip()
    if not q_:
        return ""
    for cand in APP_ALIASES.get(q_, []):
        if cand in apps or cand == "Finder":
            return cand
    exact = next((n for n in apps if n.lower() == q_), "")
    if exact:
        return exact
    starts = sorted((n for n in apps if n.lower().startswith(q_)), key=len)
    if starts:
        return starts[0]
    inside = sorted((n for n in apps if q_ in n.lower()), key=len)
    return inside[0] if inside else ""


def open_app(name: str) -> str:
    app = find_app(name)
    if app:
        r = subprocess.run(["open", "-a", app], capture_output=True, text=True, timeout=15)
        return f"launched {app}" if r.returncode == 0 else f"error: couldn't open {app} ({r.stderr.strip()[:120]})"
    argv = name.split()
    if argv and shutil.which(argv[0]):                      # a command-line program
        _detach(argv)
        return f"launched {name}"
    return f"no app found called '{name}'"


def terminal_app() -> str:
    apps = installed_apps()
    return next((a for a in ("iTerm", "Terminal") if a in apps or a == "Terminal"), "Terminal")


def run_in_terminal(command: str, keep_open: bool = True) -> str:
    """A visible terminal window running a command (Terminal.app, or iTerm when installed)."""
    # keep_open=False: the window closes when the command succeeds (Terminal closes a cleanly exited shell) and stays
    # open on a failure, like the Linux terminals
    cmd = command + ("; echo; read -p 'Press Enter to close...'" if keep_open else "; exit")
    if terminal_app() == "iTerm":
        script = (f'tell application "iTerm"\n activate\n set w to (create window with default profile)\n'
                  f' tell current session of w to write text {q(cmd)}\nend tell')
    else:
        script = f'tell application "Terminal"\n activate\n do script {q(cmd)}\nend tell'
    code, out = osascript(script, 15)
    return f"opened terminal running: {command}" if code == 0 else _perm_error(out, "opening a terminal")


def chrome_binary() -> str:
    for base in (Path("/Applications"), Path.home() / "Applications"):
        exe = base / f"{CHROME_APP}.app/Contents/MacOS/{CHROME_APP}"
        if exe.exists():
            return str(exe)
    return ""


# ---- installs (Homebrew) ---------------------------------------------------------------------------
def brew() -> str:
    return shutil.which("brew") or next((f"{p}/brew" for p in BREW_PATHS if os.path.exists(f"{p}/brew")), "")


def install_argv(packages: list[str], source: str) -> list[str]:
    """Homebrew installs as the user (never sudo). system = a formula (command-line tool), cask = an app."""
    b = brew()
    if not b:
        raise ValueError("Homebrew is not installed (see https://brew.sh); install it first")
    if source in ("system", "brew", "formula", "dnf", "pacman", "apt"):
        return [b, "install", *packages]
    if source in ("cask", "app", "flatpak"):
        return [b, "install", "--cask", *packages]
    raise ValueError("source must be system (a Homebrew formula) or cask (an app)")


# ---- windows ---------------------------------------------------------------------------------------
def _windows_script() -> str:
    return ('set out to ""\n'
            'tell application "System Events"\n'
            ' repeat with p in (every process whose background only is false)\n'
            '  try\n'
            '   repeat with w in (every window of p)\n'
            '    set out to out & (name of p) & tab & (name of w) & linefeed\n'
            '   end repeat\n'
            '  end try\n'
            ' end repeat\n'
            'end tell\n'
            'return out')


def list_windows() -> list[tuple[str, str]]:
    code, out = osascript(_windows_script(), 15)
    if code != 0:
        raise PermissionError(out)
    rows = []
    for line in out.splitlines():
        app, _, title = line.partition("\t")
        if app:
            rows.append((app, title))
    return rows


def _visible_frame() -> tuple[int, int, int, int]:
    """(x, y, w, h) of the main screen without the menu bar and Dock, top-left origin, in points."""
    try:
        from AppKit import NSScreen
        s = NSScreen.mainScreen()
        full, vis = s.frame(), s.visibleFrame()
        top = full.size.height - (vis.origin.y + vis.size.height)
        return int(vis.origin.x), int(top), int(vis.size.width), int(vis.size.height)
    except Exception:
        code, out = osascript('tell application "Finder" to get bounds of window of desktop', 5)
        try:
            _, _, w, h = (int(v) for v in out.split(","))
            return 0, 25, w, h - 25
        except ValueError:
            return 0, 25, 1440, 875


def window(action: str, app: str = "", width: int = 0, height: int = 0, x: int = 0, y: int = 0) -> str:
    """maximize|unmaximize|minimize|close|focus|resize|move|list, through System Events (Accessibility)."""
    try:
        wins = list_windows()
    except PermissionError as e:
        return _perm_error(str(e), "window control")
    if action == "list":
        return "\n".join(f"{a} | {t[:70]}" for a, t in wins)[:3000] or "no windows open"
    ql = app.lower().strip()
    hit = next(((a, t) for a, t in wins if ql and ql == a.lower()), None) or \
        next(((a, t) for a, t in wins if ql and ql in f"{a} {t}".lower()), None)
    if not hit:
        return f"no window matching '{app}'"
    proc, title = hit
    w = f"(first window of process {q(proc)} whose name is {q(title)})"
    if action == "focus":
        body = f'set frontmost of process {q(proc)} to true\n perform action "AXRaise" of {w}'
    elif action == "close":
        body = f'click (first button of {w} whose subrole is "AXCloseButton")'
    elif action == "minimize":
        body = f'set value of attribute "AXMinimized" of {w} to true'
    elif action == "maximize":
        vx, vy, vw, vh = _visible_frame()
        body = (f'set value of attribute "AXMinimized" of {w} to false\n set frontmost of process {q(proc)} to true\n'
                f' set position of {w} to {{{vx}, {vy}}}\n set size of {w} to {{{vw}, {vh}}}')
    elif action == "unmaximize":
        vx, vy, vw, vh = _visible_frame()
        body = (f'set position of {w} to {{{vx + vw // 8}, {vy + vh // 8}}}\n'
                f' set size of {w} to {{{vw * 3 // 4}, {vh * 3 // 4}}}')
    elif action == "resize":
        body = f"set size of {w} to {{{int(width)}, {int(height)}}}"
    elif action == "move":
        body = f"set position of {w} to {{{int(x)}, {int(y)}}}"
    else:
        return f"unknown window action '{action}'"
    code, out = osascript(f'tell application "System Events"\n {body}\nend tell', 10)
    return f"{action} done on {proc}" if code == 0 else _perm_error(out, f"{action} on {proc}")


# ---- what he is looking at -------------------------------------------------------------------------
def focused() -> dict:
    """{app, title, pid, fullscreen} of the window in front."""
    script = ('tell application "System Events"\n'
              ' set p to first process whose frontmost is true\n'
              ' set out to (name of p) & tab & (unix id of p)\n'
              ' try\n'
              '  set w to front window of p\n'
              '  set out to out & tab & (name of w) & tab & (value of attribute "AXFullScreen" of w)\n'
              ' end try\n'
              'end tell\n'
              'return out')
    code, out = osascript(script, 2)
    if code != 0 or not out:
        return {}
    parts = out.split("\t")
    try:
        pid = int(parts[1])
    except (IndexError, ValueError):
        pid = 0
    return {"app": parts[0], "title": parts[2] if len(parts) > 2 else "", "pid": pid,
            "fullscreen": len(parts) > 3 and parts[3].strip() == "true"}


def _children(pid: int) -> list[int]:
    try:
        out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True, timeout=1).stdout
        return [int(x) for x in out.split()]
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def cwd_of(pid: int) -> str:
    try:
        out = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True,
                             timeout=1).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return next((ln[1:] for ln in out.splitlines() if ln.startswith("n")), "")


def deepest_cwd(pid: int) -> str:
    """Terminal -> login -> shell -> program: follow the newest child, as deskctx does through /proc on Linux."""
    for _ in range(5):
        kids = _children(pid)
        if not kids:
            break
        pid = max(kids)
    return cwd_of(pid)


# ---- typing (dictation) ----------------------------------------------------------------------------
def type_text(text: str) -> str:
    """Paste into the focused app (Cmd+V), then put his clipboard back. Typing key by key mangles non-ASCII text."""
    old = subprocess.run(["pbpaste"], capture_output=True, timeout=5).stdout
    subprocess.run(["pbcopy"], input=text.encode(), timeout=5)
    code, out = osascript('tell application "System Events" to keystroke "v" using command down', 5)
    time.sleep(0.25)                                       # let the app read the clipboard before restoring it
    subprocess.run(["pbcopy"], input=old, timeout=5)
    if code == 0:
        return "typed"
    subprocess.run(["pbcopy"], input=text.encode(), timeout=5)
    notify("Clove dictation", "Copied: press Cmd+V to paste (allow Accessibility to type for you)")
    return "copied"


# ---- screenshots -----------------------------------------------------------------------------------
def screenshot():
    """Full-resolution screenshot of the main display as a PIL image. Needs the Screen Recording permission."""
    from PIL import Image
    fd, path = tempfile.mkstemp(prefix="clove-shot-", suffix=".png")
    os.close(fd)
    try:
        r = subprocess.run(["screencapture", "-x", "-m", "-t", "png", path], capture_output=True, text=True, timeout=20)
        if r.returncode != 0 or os.path.getsize(path) == 0:
            raise RuntimeError("screenshot denied: allow Screen Recording for the app CLOVE runs in "
                               f"({PERMISSION['screen']}). {r.stderr.strip()[:100]}")
        img = Image.open(path)
        img.load()
        return img.convert("RGB")
    finally:
        Path(path).unlink(missing_ok=True)


# ---- presence --------------------------------------------------------------------------------------
def lock_screen():
    osascript('tell application "System Events" to keystroke "q" using {control down, command down}', 5)


def connected_bluetooth() -> int:
    if shutil.which("blueutil"):
        out = subprocess.run(["blueutil", "--connected", "--format", "json"], capture_output=True, text=True,
                             timeout=6).stdout
        try:
            return len(json.loads(out or "[]"))
        except ValueError:
            return 0
    out = subprocess.run(["system_profiler", "SPBluetoothDataType", "-json"], capture_output=True, text=True,
                         timeout=15).stdout
    try:
        data = json.loads(out)["SPBluetoothDataType"][0]
        return len(data.get("device_connected") or [])
    except (ValueError, KeyError, IndexError):
        return 0


# ---- this Mac --------------------------------------------------------------------------------------
def describe() -> str:
    import platform
    ver = platform.mac_ver()[0] or "?"
    chip = "Apple silicon" if platform.machine() == "arm64" else "Intel"
    return f"macOS {ver} ({chip}){', packages with Homebrew' if brew() else ''}"


def memory_bytes() -> tuple[int, int]:
    """(total, used) like Activity Monitor: used = app memory + wired + compressed."""
    total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3).stdout or 0)
    out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
    page = int(re.search(r"page size of (\d+)", out).group(1)) if "page size of" in out else 16384
    v = {k.strip(): int(n) for k, n in re.findall(r'^"?([^:"]+)"?:\s+(\d+)\.?$', out, re.M)}
    used = (v.get("Anonymous pages", v.get("Pages active", 0)) - v.get("Pages purgeable", 0)
            + v.get("Pages wired down", 0) + v.get("Pages occupied by compressor", 0)) * page
    return total, max(0, min(used, total))


def cpu_percent() -> float:
    """All processes' CPU added up, over the core count (ps is cheap; top -l would take a second)."""
    out = subprocess.run(["ps", "-A", "-o", "%cpu="], capture_output=True, text=True, timeout=3).stdout
    total = sum(float(x) for x in out.split() if re.fullmatch(r"[\d.]+", x))
    return round(min(100.0, total / (os.cpu_count() or 1)), 1)


def net_bytes() -> tuple[int, int]:
    out = subprocess.run(["netstat", "-ibn"], capture_output=True, text=True, timeout=3).stdout
    rx = tx = 0
    seen = set()
    for line in out.splitlines()[1:]:
        f = line.split()
        if len(f) < 10 or not f[2].startswith("<Link") or f[0] in seen or f[0].startswith(("lo", "utun", "awdl", "llw", "bridge", "gif", "stf", "anpi", "ap")):
            continue
        seen.add(f[0])
        try:
            rx, tx = rx + int(f[-5]), tx + int(f[-2])
        except ValueError:
            pass
    return rx, tx


def uptime_s() -> float:
    out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=3).stdout
    m = re.search(r"sec = (\d+)", out)
    return time.time() - int(m.group(1)) if m else 0.0


def start_ollama() -> bool:
    """Brew service, the Ollama app, or a bare `ollama serve`, whichever exists."""
    b = brew()
    if b and subprocess.run([b, "services", "start", "ollama"], capture_output=True, timeout=30).returncode == 0:
        return True
    if (Path("/Applications/Ollama.app")).exists():
        _detach(["open", "-g", "-a", "Ollama"])
        return True
    exe = shutil.which("ollama")
    if exe:
        _detach([exe, "serve"])
        return True
    return False


def stop_ollama() -> bool:
    b = brew()
    if b and subprocess.run([b, "services", "stop", "ollama"], capture_output=True, timeout=30).returncode == 0:
        return True
    return subprocess.run(["pkill", "-x", "ollama"], capture_output=True).returncode == 0
