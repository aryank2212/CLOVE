"""routines/local/ replaces a default routine with the same key, and adds new ones."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import routines  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


def write(path, key, title, body):
    path.write_text(f"---\nkey: {key}\ntitle: {title}\ntrigger_id:\n---\n{body}\n")


with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    (base / "local").mkdir()
    write(base / "night_log.md", "night_log", "Night Log", "default questions")
    write(base / "morning_plan.md", "morning_plan", "Morning Plan", "default brief")
    write(base / "local" / "night_log.md", "night_log", "Night Log", "my own questions")
    write(base / "local" / "reading.md", "reading", "Reading", "what I read")
    routines.DIR, routines.LOCAL_DIR = base, base / "local"
    got = routines.load()
    check("a local routine replaces the default with the same key", got["night_log"].prompt == "my own questions")
    check("defaults without a local copy stay", got["morning_plan"].prompt == "default brief")
    check("a new local routine is added", got["reading"].title == "Reading")

    routines.LOCAL_DIR = base / "missing"
    check("no local folder: just the defaults", routines.load()["night_log"].prompt == "default questions")

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
