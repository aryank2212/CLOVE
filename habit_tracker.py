"""Habit tracker: log habits, streaks."""
import json, time
from pathlib import Path
import config
log = None
import logging
log = logging.getLogger("clove.habit_tracker")
_DIR = Path(config.DATA_DIR)/"habits"
def _p(name): _DIR.mkdir(parents=True,exist_ok=True); return _DIR/(name+".json")
def log_habit(name, note=""):
    p=_p(name); data=json.loads(p.read_text()) if p.exists() else {"name":name,"entries":[]}
    data["entries"].append({"ts":time.time(),"note":note})
    p.write_text(json.dumps(data,indent=2))
    streak = len(data["entries"])
    return f"Logged '{name}'. Total: {streak}."
def status(name):
    p=_p(name)
    if not p.exists(): return f"no data for '{name}'"
    data=json.loads(p.read_text())
    return f"'{name}': {len(data['entries'])} entries. Last: {data['entries'][-1]['ts'] if data['entries'] else 'never'}"
def list_habits():
    if not _DIR.exists(): return "no habits tracked"
    return ", ".join(p.stem for p in _DIR.glob("*.json")) or "no habits"
