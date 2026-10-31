"""./run.sh --doctor : one screen that says what works and what doesn't, with the fix for each problem."""
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import config

OK, BAD, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m!\033[0m"


def _row(mark: str, what: str, detail: str = "", fix: str = ""):
    print(f" {mark} {what:<22} {detail}")
    if fix and mark != OK:
        print(f"   {'':<22} -> {fix}")


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _log_last(*needles: str) -> str:
    try:
        lines = (config.STATE_DIR / "clove.log").read_text(errors="replace").splitlines()[-4000:]
    except OSError:
        return ""
    return next((ln for ln in reversed(lines) if any(n in ln for n in needles)), "")


def mac_checks():
    """The macOS permissions and helpers CLOVE relies on, each with where to turn it on."""
    import macos
    _row(OK if macos.brew() else WARN, "Homebrew", macos.brew() or "not installed", "https://brew.sh (installs need it)")
    code, out = macos.osascript('tell application "System Events" to get name of first process whose frontmost is true', 5)
    _row(OK if code == 0 else BAD, "Accessibility", "allowed" if code == 0 else "not allowed (windows, typing, media keys)",
         f"{macos.PERMISSION['accessibility']}: turn on Terminal (or Python for the login agent)")
    try:
        macos.screenshot()
        _row(OK, "Screen Recording", "allowed")
    except Exception as e:
        _row(BAD, "Screen Recording", str(e)[:60], f"{macos.PERMISSION['screen']}, then restart CLOVE")
    try:
        import objc  # noqa: F401
        _row(OK, "PyObjC", "installed (pointer, media keys)")
    except ImportError:
        _row(WARN, "PyObjC", "missing: no on-screen pointer or media keys", ".venv/bin/pip install pyobjc")
    _row(OK if macos.chrome_binary() else BAD, "Google Chrome", macos.chrome_binary() or "not found",
         "brew install --cask google-chrome")


def windows_checks():
    """Windows helpers CLOVE relies on."""
    import windows as macos
    _row(OK if macos.brew() else WARN, "Package manager", macos.brew() or "none (winget/choco/scoop)", "install winget or choco")
    try:
        macos.screenshot()
        _row(OK, "Screen capture", "ok")
    except Exception as e:
        _row(BAD, "Screen capture", str(e)[:60], "grant screen capture permission")
    _row(OK if macos.chrome_binary() else BAD, "Google Chrome", macos.chrome_binary() or "not found",
         "install Google Chrome")
    try:
        import psutil  # noqa: F401
        _row(OK, "psutil", "installed")
    except ImportError:
        _row(WARN, "psutil", "missing", "pip install psutil")
    try:
        import pycaw  # noqa: F401
        _row(OK, "pycaw", "installed (volume control)")
    except ImportError:
        _row(WARN, "pycaw", "missing: volume control limited", "pip install pycaw")


def run():
    print("Clove doctor\n")
    running = (config.RUNTIME_DIR / "clove.url").exists()
    _row(OK if running else WARN, "Clove app", "running" if running else "not running", "./run.sh")

    # Gemini
    if not config.GEMINI_API_KEY:
        _row(BAD, "Gemini key", "GEMINI_API_KEY missing", "put it in .env")
    else:
        try:
            from google import genai
            t0 = time.time()
            client = genai.Client(api_key=config.GEMINI_API_KEY)          # keep a reference: a temporary one is closed mid-call
            client.models.get(model=config.BRAIN_MODELS[0])
            _row(OK, "Gemini key", f"works ({(time.time() - t0) * 1000:.0f} ms)")
        except Exception as e:
            _row(BAD, "Gemini key", str(e)[:70], "check the key / internet")

    # audio
    try:
        from audio import pick_route
        r = pick_route()
        bt = r.source.startswith("bluez")
        _row(WARN if bt else OK, "Audio", r.label, "Bluetooth mics hear worse; a USB/wired mic is best" if bt else "")
    except Exception as e:
        _row(BAD, "Audio", str(e)[:70], "./run.sh --devices")

    # Chrome extension
    if running:
        last = _log_last("Chrome extension connected", "Chrome extension disconnected")
        on = "disconnected" not in last and bool(last)
        _row(OK if on else BAD, "Chrome extension", "connected" if on else "not connected",
             "chrome://extensions -> reload Clove Hands (or ./install_extension.sh)")
    else:
        _row(WARN, "Chrome extension", "start Clove to check")
    ext = json.loads((config.ROOT / "chrome_extension/manifest.json").read_text())
    last_hello = _log_last("Chrome extension is out of date", "Chrome extension connected")
    stale = "out of date" in last_hello
    _row(BAD if stale else OK, "Extension version", f"files v{ext.get('version', '?')}" + (" - Chrome has an OLDER one loaded" if stale else ""),
         "chrome://extensions -> click reload on Clove Hands" if stale else "")

    # calls
    if config.IS_MAC or config.IS_WINDOWS:
        from call_audio_mac import FROM_CALL, TO_CALL, devices_present
        voice, sound = devices_present()
        _row(OK if voice and sound else BAD, "Call audio devices",
             f"{TO_CALL} + {FROM_CALL} found" if voice and sound else f"missing {', '.join(n for n, ok in ((TO_CALL, voice), (FROM_CALL, sound)) if not ok)}",
             "brew install blackhole-2ch blackhole-16ch, then restart CLOVE")
    else:
        pa = shutil.which("pactl") and shutil.which("pacat") and shutil.which("parec")
        _row(OK if pa else BAD, "Call audio tools", "pactl / pacat / parec found" if pa else "missing",
             "install libpulse (Arch) / pulseaudio-utils (Fedora, Debian)" if not pa else "")
        left = [ln for ln in subprocess.run(["pactl", "list", "short", "modules"], capture_output=True, text=True).stdout.splitlines() if "clove_" in ln] if pa else []
        if left and not running:
            _row(WARN, "Call audio devices", "left over from a crashed call", "python -c 'import call_audio; call_audio.CallAudio.teardown_leftovers()'")
    _row(OK, "Calls", f"AI disclosure {'on' if config.CALL_DISCLOSE else 'OFF'}, limit {config.CALL_MAX_MINUTES} min")

    # local brain
    oll = shutil.which("ollama") or str(Path.home() / ".local/bin/ollama")
    if not Path(oll).exists():
        _row(WARN, "Ollama (Qwen)", "not installed", "scripts/install_local.sh")
    else:
        up = _port_open(11434)
        loaded = ""
        if up:
            import ollama_ctl
            loaded = ", ".join(ollama_ctl.loaded()) or "no model loaded"
        _row(OK, "Ollama (Qwen)", f"{'running: ' + loaded if up else 'stopped (starts on demand)'}")
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader"],
                         capture_output=True, text=True).stdout.strip() if shutil.which("nvidia-smi") else ""
    if gpu:
        _row(OK, "GPU memory", gpu)
    if config.IS_MAC:
        mac_checks()
    elif config.IS_WINDOWS:
        try:
            windows_checks()
        except NameError:
            pass

    # coding agents
    import delegate
    try:
        _row(OK, "Claude Code", delegate.claude_bin())
    except RuntimeError as e:
        _row(BAD, "Claude Code", str(e))
    try:
        oc = delegate.opencode_bin()
        km = getattr(config, "KILO_MODEL", config.OPENCODE_MODEL)
        _row(OK, "Kilo", f"{oc} · {km}")
    except RuntimeError as e:
        _row(WARN, "Kilo", str(e))

    # memory
    try:
        import memory
        _row(OK, "Memory", memory.stats())
    except Exception as e:
        _row(BAD, "Memory", str(e)[:70])
    err = _log_last("ERROR", "Traceback")
    if err:
        _row(WARN, "Last error in log", err[:90], f"see {config.STATE_DIR / 'clove.log'}")
    print()
