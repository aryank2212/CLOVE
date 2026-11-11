"""The agenda: moments as he says them, reminders that are kept, to-dos edited, and a calendar read from iCal."""
import datetime
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()

import memory  # noqa: E402

memory.PATH = Path(tempfile.mkdtemp()) / "memory.db"
memory._db = None
import agenda  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    fails += not ok


NOW = datetime.datetime(2026, 11, 11, 14, 0)          # a Wednesday afternoon
when = lambda s: (lambda t: datetime.datetime.fromtimestamp(t) if t else None)(agenda.parse_when(s, NOW))
D = datetime.datetime
check("in 20 minutes", when("in 20 minutes") == D(2026, 11, 11, 14, 20))
check("in an hour", when("in an hour") == D(2026, 11, 11, 15, 0))
check("a time later today", when("18:30") == D(2026, 11, 11, 18, 30))
check("a time already passed is tomorrow's", when("at 9am") == D(2026, 11, 12, 9, 0))
check("tomorrow means 9 in the morning", when("tomorrow") == D(2026, 11, 12, 9, 0))
check("tomorrow 7pm", when("tomorrow at 7pm") == D(2026, 11, 12, 19, 0))
check("a weekday and a time", when("friday 6:15 pm") == D(2026, 11, 13, 18, 15))
check("the time first", when("10am on 25 nov") == D(2026, 11, 25, 10, 0))
check("an ISO moment", when("2026-12-01 08:05") == D(2026, 12, 1, 8, 5))
check("nonsense is refused", when("whenever") is None)

out = agenda.reminder_add("call the bank", "in 30 minutes")
check("a reminder is kept", out.startswith("reminder set") and len(agenda.reminder_rows()) == 1, out)
check("no text is refused", agenda.reminder_add("", "in 5 minutes").startswith("error"))
check("no moment is refused", agenda.reminder_add("x", "sometime").startswith("error"))
agenda.reminder_add("water the plants", "tomorrow 8am")
check("they list in order", agenda.reminder_list().splitlines()[0].endswith("call the bank"), agenda.reminder_list())
out = agenda.reminder_edit("bank", "call the bank about the card", "in 2 hours")
row = [r for r in agenda.reminder_rows() if "card" in r["text"]]
check("a reminder is edited", len(row) == 1 and abs(row[0]["at"] - time.time() - 7200) < 5, out)
check("a reminder is removed by words", agenda.reminder_remove("plants").startswith("removed") and len(agenda.reminder_rows()) == 1)

memory.todo_add(["buy milk", "renew passport by friday"])
out = agenda.todo_edit("milk", "buy oat milk", "tomorrow")
rows = {r["text"]: r["due"] for r in memory.todo_rows("open")}
check("a to-do is edited", rows.get("buy oat milk") == (datetime.date.today() + datetime.timedelta(days=1)).isoformat(), out)
agenda.todo_edit("oat milk", "", "none")
check("its date is cleared", {r["text"]: r["due"] for r in memory.todo_rows("open")}["buy oat milk"] is None)

snap = json.loads(agenda.handle(json.dumps({"op": "todo_add", "text": "book tickets"})))
check("the notch adds a to-do", snap["ok"] and any(t["text"] == "book tickets" for t in snap["todos"]))
tid = next(t["id"] for t in snap["todos"] if t["text"] == "book tickets")
snap = json.loads(agenda.handle(json.dumps({"op": "todo_done", "id": tid})))
check("and ticks it off", not any(t["id"] == tid for t in snap["todos"]))
snap = json.loads(agenda.handle(json.dumps({"op": "reminder_add", "text": "stand up", "when": "in 10 minutes"})))
check("the notch adds a reminder", snap["ok"] and any(r["text"] == "stand up" for r in snap["reminders"]))
snap = json.loads(agenda.handle(json.dumps({"op": "reminder_add", "text": "x", "when": "gibberish"})))
check("and is told when it can't", not snap["ok"] and "couldn't tell" in snap["say"])

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Dentist
DTSTART:20261112T103000
DTEND:20261112T110000
LOCATION:Clinic\\, Sector 18
END:VEVENT
BEGIN:VEVENT
SUMMARY:Standup
DTSTART:20261102T093000
DTEND:20261102T094500
RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR
EXDATE:20261113T093000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Mom's birthday
DTSTART;VALUE=DATE:20200320
RRULE:FREQ=YEARLY
END:VEVENT
BEGIN:VEVENT
SUMMARY:Rent
DTSTART:20261101T090000
RRULE:FREQ=MONTHLY;COUNT=2
END:VEVENT
BEGIN:VEVENT
SUMMARY:Called off
DTSTART:20261112T150000
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""
evs = agenda.parse_ics(ICS)
check("events are read, cancelled ones left out", [e["title"] for e in evs] == ["Dentist", "Standup", "Mom's birthday", "Rent"])
check("an escaped comma is a comma", evs[0]["where"] == "Clinic, Sector 18")
d = datetime.date
occ = lambda i, a, b: [x.strftime("%m-%d") for x in agenda.occurrences(evs[i], a, b)]
check("a single event falls on its day", occ(0, d(2026, 11, 1), d(2026, 11, 30)) == ["11-12"])
check("a weekly one repeats on its days, minus the exception",
      occ(1, d(2026, 11, 9), d(2026, 11, 15)) == ["11-09", "11-11"], str(occ(1, d(2026, 11, 9), d(2026, 11, 15))))
check("a yearly one comes back", occ(2, d(2027, 3, 1), d(2027, 3, 31)) == ["03-20"] and evs[2]["all_day"])
check("a count ends it", occ(3, d(2026, 11, 1), d(2027, 2, 1)) == ["11-01", "12-01"])

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
