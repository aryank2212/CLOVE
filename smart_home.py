"""Smart home scenes via shell commands."""
import subprocess, logging
log = logging.getLogger("clove.smart_home")
SCENES = {
  "movie": ["playerctl pause 2>/dev/null", "brightnessctl set 20% 2>/dev/null", "notify-send 'Movie mode'"],
  "work": ["brightnessctl set 80% 2>/dev/null", "notify-send 'Work mode'"],
  "sleep": ["systemctl suspend 2>/dev/null"],
}
def run_scene(name):
    cmds = SCENES.get(name.lower())
    if not cmds: return f"unknown scene '{name}'. Available: {', '.join(SCENES)}"
    out = []
    for c in cmds:
        subprocess.run(c, shell=True, capture_output=True, timeout=10)
        out.append(c)
    return f"ran scene '{name}': " + "; ".join(out)
def list_scenes():
    return "scenes: " + ", ".join(SCENES)
