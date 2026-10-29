"""What he is doing right now, without a screenshot: the focused window (Hyprland, or GNOME's Window Calls
extension), and for a terminal or editor the folder it is in and its git branch. Instant and free, so
"fix this", "commit this" and "what's this error" know what "this" is before any vision call is needed."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

TERMINALS = {"alacritty", "kitty", "foot", "ghostty", "wezterm", "org.wezfurlong.wezterm", "com.mitchellh.ghostty",
             "gnome-terminal-server", "org.gnome.terminal", "org.gnome.ptyxis", "konsole", "xterm", "tilix"}
_cache: tuple[float, dict] = (0.0, {})


def _run(*argv: str, timeout: float = 1.0) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _focused() -> dict:
    if shutil.which("hyprctl") and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        try:
            w = json.loads(_run("hyprctl", "activewindow", "-j") or "{}")
            return {"app": w.get("class", ""), "title": w.get("title", ""), "pid": w.get("pid") or 0,
                    "fullscreen": bool(w.get("fullscreen"))}
        except ValueError:
            return {}
    out = _run("gdbus", "call", "--session", "--dest", "org.gnome.Shell", "--object-path",
               "/org/gnome/Shell/Extensions/Windows", "--method", "org.gnome.Shell.Extensions.Windows.List")
    try:
        wins = json.loads(out[out.index("["):out.rindex("]") + 1].replace("\\'", "'")) if "[" in out else []
    except ValueError:
        return {}
    w = next((x for x in wins if x.get("focus")), {})
    return {"app": w.get("wm_class", ""), "title": w.get("title", ""), "pid": w.get("pid") or 0, "fullscreen": False}


def _deepest_cwd(pid: int) -> str:
    """A terminal's shell (or the program running in it) is a child of the terminal: follow the newest child."""
    for _ in range(4):
        try:
            kids = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        except OSError:
            break
        if not kids:
            break
        pid = int(kids[-1])
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def _git(folder: str) -> str:
    if not folder or not Path(folder).is_dir():
        return ""
    branch = _run("git", "-C", folder, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if not branch:
        return ""
    dirty = _run("git", "-C", folder, "status", "--porcelain").strip()
    n = len(dirty.splitlines()) if dirty else 0
    return f"git branch {branch}" + (f", {n} changed files" if n else ", clean")


def current(max_age: float = 1.5) -> dict:
    global _cache
    if time.monotonic() - _cache[0] < max_age:
        return _cache[1]
    w = _focused()
    if w.get("pid") and w.get("app", "").lower() in TERMINALS:
        w["folder"] = _deepest_cwd(int(w["pid"]))
    w.pop("pid", None)
    if w.get("folder"):
        w["git"] = _git(w["folder"])
    _cache = (time.monotonic(), w)
    return w


def note() -> str:
    """One line for the model, e.g. 'Focused window: kitty "nvim tools.py" in ~/clove (git branch main, clean)'."""
    w = current()
    if not w.get("app"):
        return ""
    s = f'Focused window: {w["app"]} "{w.get("title", "")[:90]}"'
    if w.get("folder"):
        s += f" in {w['folder'].replace(str(Path.home()), '~')}"
        if w.get("git"):
            s += f" ({w['git']})"
    return s


def busy_fullscreen() -> bool:
    """A fullscreen video or game: Clove should not interrupt with proactive remarks."""
    return bool(current().get("fullscreen"))
