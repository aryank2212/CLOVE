"""Windows versions of the desktop actions in desktop.py, deskctx.py, dictate.py and screen.py.

Clove on Windows uses built-in tools (PowerShell, ctypes, win32 APIs) plus optional helpers (pywin32, psutil,
pycaw). Install optional helpers with: pip install pywin32 psutil pycaw
"""
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CHROME_APP = "Google Chrome"
CHROME_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
APP_DIRS = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"]
PERMISSION = {}

def add_brew_to_path():
    """No-op on Windows; ensure common tool dirs are on PATH."""
    parts = os.environ.get("PATH", "").split(os.pathsep)
    extra = [str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"),
             r"C:\Program Files\Ollama",
             str(Path.home() / ".local" / "bin")]
    for p in extra:
        if p and os.path.isdir(p) and p not in parts:
            parts.insert(0, p)
    os.environ["PATH"] = os.pathsep.join(x for x in parts if x)

# ---- helpers ----
def _detach(argv):
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    except Exception:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _run(argv, timeout=10):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout if r.returncode == 0 else r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "timed out"
    except OSError as e:
        return 1, str(e)

def _powershell(script, timeout=15):
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)

# ---- open ----
def open_target(target: str):
    if "://" in target:
        os.startfile(target) if hasattr(os, "startfile") else _detach(["cmd", "/c", "start", "", target])
    else:
        target = os.path.expanduser(target)
        if not os.path.exists(target):
            return
        os.startfile(target)

# ---- volume (Core Audio via ctypes) ----
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

def _volume_interface():
    # Returns IAudioEndpointVolume pointer or None
    try:
        from ctypes import wintypes
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        # IMMDeviceEnumerator
        CLSID_MMDeviceEnumerator = _GUID(0xBCDE0395, 0xE52F, 0x467C, (0x8E, 0x38, 0xC6, 0x57, 0x79, 0x29, 0x1A, 0xE9))
        IID_IMMDeviceEnumerator = _GUID(0xA95664D2, 0x9614, 0x4F35, (0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6))
        # Use comtypes if available for simplicity
    except Exception:
        pass
    return None

def volume(action: str, percent: int = 0) -> str:
    # Try pycaw first
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from comtypes import CLSCTX_ALL
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = ctypes.cast(interface, ctypes.POINTER(IAudioEndpointVolume))
        cur = vol.GetMasterVolumeLevelScalar()
        muted = bool(vol.GetMute())
        step = (percent or 10) / 100.0
        if action == "up":
            vol.SetMasterVolumeLevelScalar(min(1.0, cur + step), None)
        elif action == "down":
            vol.SetMasterVolumeLevelScalar(max(0.0, cur - step), None)
        elif action == "set":
            vol.SetMasterVolumeLevelScalar(max(0.0, min(1.0, percent / 100.0)), None)
        elif action == "mute":
            vol.SetMute(1, None)
        elif action == "unmute":
            vol.SetMute(0, None)
        elif action == "get":
            pass
        cur = vol.GetMasterVolumeLevelScalar()
        muted = bool(vol.GetMute())
        return f"volume {int(cur*100)}%{' (muted)' if muted else ''}"
    except Exception:
        # Fallback: nircmd
        if shutil.which("nircmd"):
            if action == "up":
                subprocess.run(["nircmd", "changesysvolume", str(int((percent or 10) * 655.35))], capture_output=True)
            elif action == "down":
                subprocess.run(["nircmd", "changesysvolume", str(-int((percent or 10) * 655.35))], capture_output=True)
            elif action == "mute":
                subprocess.run(["nircmd", "mutesysvolume", "1"], capture_output=True)
            elif action == "unmute":
                subprocess.run(["nircmd", "mutesysvolume", "0"], capture_output=True)
            return f"volume {action}"
        return "error: volume control needs pycaw (pip install pycaw) or nircmd on Windows"

# ---- media keys ----
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

def _keybd_event(vk):
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, 2, 0)

def media(action: str) -> str:
    mapping = {"next": VK_MEDIA_NEXT_TRACK, "previous": VK_MEDIA_PREV_TRACK,
               "prev": VK_MEDIA_PREV_TRACK, "toggle": VK_MEDIA_PLAY_PAUSE,
               "play": VK_MEDIA_PLAY_PAUSE, "pause": VK_MEDIA_PLAY_PAUSE}
    if action not in mapping:
        return "error: action must be play, pause, toggle, next or previous"
    _keybd_event(mapping[action])
    return f"media: {action}"

# ---- clipboard ----
def clipboard(action: str, text: str = "") -> str:
    if action == "get":
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    if action == "set":
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value {text!r}"], capture_output=True, text=True, timeout=5)
        return "clipboard set"
    return "error: action must be get or set"

# ---- notify ----
def notify(title: str, body: str = ""):
    script = (f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; '
              f'$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); '
              f'$t.GetElementsByTagName("text")[0].AppendChild($t.CreateTextNode("{title}")) | Out-Null; '
              f'$t.GetElementsByTagName("text")[1].AppendChild($t.CreateTextNode("{body}")) | Out-Null; '
              f'$n = [Windows.UI.Notifications.ToastNotification]::new($t); '
              f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Clove").Show($n)')
    _powershell(script, timeout=8)

# ---- apps ----
def installed_apps() -> dict[str, Path]:
    apps = {}
    # Start Menu shortcuts
    roots = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
             Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"]
    for root in roots:
        if not root.exists():
            continue
        for lnk in root.rglob("*.lnk"):
            apps[lnk.stem] = lnk
    return apps

def find_app(name: str, apps=None) -> str:
    apps = installed_apps() if apps is None else apps
    q_ = name.lower().strip()
    if q_ in {n.lower(): n for n in apps}:
        return next(n for n in apps if n.lower() == q_)
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
        try:
            os.startfile(str(installed_apps()[app]))
            return f"opened {app}"
        except Exception as e:
            return f"error: {e}"
    # fallback: start command
    _detach(["cmd", "/c", "start", "", name])
    return f"opened {name}"

def terminal_app() -> str:
    for c in ["wt.exe", "WindowsTerminal.exe", "powershell.exe", "cmd.exe"]:
        if shutil.which(c):
            return c
    return "cmd.exe"

def run_in_terminal(command: str, keep_open: bool = True) -> str:
    term = terminal_app()
    if "wt" in term.lower() or "windowsterminal" in term.lower():
        argv = [term, "cmd", "/k", command] if keep_open else [term, "cmd", "/c", command]
    elif "powershell" in term.lower():
        argv = [term, "-NoExit", "-Command", command] if keep_open else [term, "-Command", command]
    else:
        argv = [term, "/k", command] if keep_open else [term, "/c", command]
    _detach(argv)
    return f"ran in terminal: {command[:60]}"

CHROME_BINARY_PATHS = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
]

def chrome_binary() -> str:
    for p in CHROME_BINARY_PATHS:
        if p.exists():
            return str(p)
    return shutil.which("chrome") or shutil.which("chrome.exe") or ""

def brew() -> str:
    for c in ["winget", "choco", "scoop"]:
        if shutil.which(c):
            return c
    return ""

def install_argv(packages: list[str], source: str) -> list[str]:
    pm = brew()
    if pm == "winget":
        return ["winget", "install", "--id", packages[0] if packages else "", "-e", "--silent",
                "--accept-package-agreements", "--accept-source-agreements"]
    if pm == "choco":
        return ["choco", "install", *(packages or []), "-y"]
    if pm == "scoop":
        return ["scoop", "install", *(packages or [])]
    return ["winget", "install", *(packages or [])]

# ---- window management via ctypes ----
try:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
except AttributeError:
    user32 = None
    kernel32 = None

def _enum_windows():
    results = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                results.append((hwnd, buf.value, pid.value))
        return True
    user32.EnumWindows(cb, 0)
    return results

def list_windows() -> list[tuple[str, str]]:
    out = []
    for hwnd, title, pid in _enum_windows():
        # process name
        name = ""
        try:
            import psutil
            name = psutil.Process(pid).name()
        except Exception:
            name = str(pid)
        out.append((name, title))
    return out

def _find_window(app: str, title_hint: str = ""):
    ql = (app or "").lower().strip()
    for hwnd, title, pid in _enum_windows():
        pname = ""
        try:
            import psutil
            pname = psutil.Process(pid).name()
        except Exception:
            pname = str(pid)
        if ql and (ql == pname.lower() or ql in pname.lower() or ql in title.lower()):
            return hwnd
    return None

def window(action: str, app: str = "", width: int = 0, height: int = 0, x: int = 0, y: int = 0) -> str:
    hwnd = _find_window(app)
    if not hwnd:
        return f"window not found: {app}"
    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    if action in ("focus", "raise", "maximize"):
        user32.SetForegroundWindow(hwnd)
        if action == "maximize":
            user32.ShowWindow(hwnd, 3)
    elif action == "close":
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    elif action == "minimize":
        user32.ShowWindow(hwnd, 6)
    elif action == "restore":
        user32.ShowWindow(hwnd, 9)
    elif action in ("move", "resize", "set"):
        # get current rect
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        w = width or (r.right - r.left)
        h = height or (r.bottom - r.top)
        xx = x if x else r.left
        yy = y if y else r.top
        user32.SetWindowPos(hwnd, 0, xx, yy, w, h, 0x0040)  # SWP_NOZORDER... actually 0x0040 = SWP_SHOWWINDOW
    return f"window {action}: {app}"

def focused() -> dict:
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ""
    try:
        import psutil
        name = psutil.Process(pid.value).name()
    except Exception:
        name = str(pid.value)
    return {"app": name, "title": buf.value, "pid": pid.value}

# ---- processes / cwd ----
def _children(pid: int) -> list[int]:
    try:
        import psutil
        return [c.pid for c in psutil.Process(pid).children(recursive=False)]
    except Exception:
        return []

def cwd_of(pid: int) -> str:
    try:
        import psutil
        return psutil.Process(pid).cwd()
    except Exception:
        return ""

def deepest_cwd(pid: int) -> str:
    kids = _children(pid)
    if not kids:
        return cwd_of(pid)
    # pick the deepest (most descendants)
    best = pid
    # simple: try children
    for k in kids:
        c = deepest_cwd(k)
        if c:
            return c
    return cwd_of(pid)

# ---- type text ----
def type_text(text: str) -> str:
    # clipboard + paste
    clipboard("set", text)
    # send Ctrl+V
    VK_CONTROL = 0x11
    VK_V = 0x56
    ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_V, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_V, 0, 2, 0)
    ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 2, 0)
    return "typed"

# ---- screenshot ----
def screenshot():
    from PIL import ImageGrab
    img = ImageGrab.grab()
    fd, path = tempfile.mkstemp(prefix="clove-shot-", suffix=".png")
    os.close(fd)
    img.save(path)
    return img, path

# ---- lock ----
def lock_screen():
    ctypes.windll.user32.LockWorkStation()

def connected_bluetooth() -> int:
    # count connected Bluetooth devices via PowerShell
    code, out = _powershell("(Get-PnpDevice -Class Bluetooth | Where-Object {$_.Status -eq 'OK' -and $_.InstanceId -match 'BTHENUM'}).Count", timeout=10)
    try:
        return int(out.strip() or "0")
    except Exception:
        return 0

# ---- describe ----
def describe() -> str:
    return f"Windows {platform.release()} ({platform.version()}) on {platform.machine()}, {platform.processor()}"

# ---- memory/cpu/net/uptime ----
def memory_bytes() -> tuple[int, int]:
    try:
        import psutil
        vm = psutil.virtual_memory()
        return vm.total, vm.used
    except Exception:
        return 0, 0

def cpu_percent() -> float:
    try:
        import psutil
        return psutil.cpu_percent(interval=0.5)
    except Exception:
        return 0.0

def net_bytes() -> tuple[int, int]:
    try:
        import psutil
        c = psutil.net_io_counters()
        return c.bytes_recv, c.bytes_sent
    except Exception:
        return 0, 0

def uptime_s() -> float:
    try:
        import psutil
        return time.time() - psutil.boot_time()
    except Exception:
        return 0.0

# ---- ollama ----
def start_ollama() -> bool:
    exe = shutil.which("ollama")
    if not exe:
        return False
    try:
        subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(1)
        return True
    except Exception:
        return False

def stop_ollama() -> bool:
    try:
        subprocess.run(["taskkill", "/IM", "ollama.exe", "/F"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False

# ---- terminal apps / aliases ----
APP_ALIASES = {
    "chrome": "Google Chrome", "firefox": "Mozilla Firefox", "edge": "Microsoft Edge",
    "notepad": "Notepad", "explorer": "File Explorer", "terminal": "Windows Terminal",
    "powershell": "Windows PowerShell", "cmd": "Command Prompt", "code": "Visual Studio Code",
}

# ---- screenshot portal not needed ----
def needs_permission(err: str) -> str:
    return ""

def _perm_error(err: str, what: str) -> str:
    return f"error: {what} failed ({str(err)[:150]})"

# keep q/osascript stubs for compatibility
def q(s: str) -> str:
    return s

def osascript(script: str, timeout: float = 10):
    return 1, "not available on Windows"
