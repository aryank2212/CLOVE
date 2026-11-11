"""His agenda: reminders that survive a restart, the to-do list (memory.py's, with editing), and the events of a real
calendar read from its iCal address. One place for it, used the same way by voice (tools.py: reminder, todo) and by
Clove Notch (ctl.py: `agenda <json>`), so what he adds by hand can be changed by voice and the other way round.

Reminders live in the memory database (table `reminders`): a text and the moment it is due. `run()` looks every
fifteen seconds and hands what is due to Clove, who shows a notification and says it.

The calendar is optional: Google Calendar, Outlook, Nextcloud and the rest all give a private iCal address
("Secret address in iCal format"). It is kept in the state folder, fetched every fifteen minutes, and read here:
plain events and the usual repeats (daily, weekly on given days, monthly, yearly; with an interval, an end date or a
count). Nothing is ever written to that calendar.
"""
import asyncio
import datetime
import json
import logging
import re
import time
import urllib.request

import config
import memory

log = logging.getLogger("clove.agenda")
ICS_FILE = config.STATE_DIR / "calendar.url"
FETCH_EVERY_S = 15 * 60
_ics = {"url": "", "at": 0.0, "events": [], "error": ""}


def _db():
    db = memory._conn()
    db.execute("CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY, text TEXT, at REAL, fired INTEGER DEFAULT 0, ts REAL)")
    return db


# ---- when ----------------------------------------------------------------------------------------------------------
_CLOCK = r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"


def _clock(text: str) -> tuple[int, int] | None:
    """'9', '9am', '9:30 pm', '21:15', 'noon', 'midnight' -> (hour, minute)."""
    t = text.strip().lower()
    if t in ("noon", "midday"):
        return 12, 0
    if t == "midnight":
        return 0, 0
    m = re.fullmatch(_CLOCK, t)
    if not m:
        return None
    hour, minute, half = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").replace(".", "")
    if half == "pm" and hour < 12:
        hour += 12
    if half == "am" and hour == 12:
        hour = 0
    return (hour, minute) if hour < 24 and minute < 60 else None


def parse_when(text: str, now: datetime.datetime | None = None) -> float | None:
    """A moment as he says or types it -> epoch seconds, or None.

    'in 20 minutes', 'in 2 hours', '18:30', '9am', 'tomorrow', 'tomorrow 9am', 'friday at 6pm', '25 nov 10:00',
    '2026-11-12 09:00', '2026-11-12T09:00'. A day without a time means 9 in the morning; a time that has passed
    today means tomorrow."""
    now = now or datetime.datetime.now()
    t = (text or "").lower().strip(" .,")
    t = re.sub(r"\b(at|on|by|around|about)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return None
    if m := re.fullmatch(r"in (?:(\d+(?:\.\d+)?)|an?|half an?) ?(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)", t):
        n = float(m.group(1)) if m.group(1) else (0.5 if "half" in t else 1.0)
        unit = m.group(2)[0]
        seconds = n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        return now.timestamp() + seconds
    if m := re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ t](\d{1,2}):(\d{2})(?::\d{2})?", t):
        try:
            return datetime.datetime.fromisoformat(f"{m.group(1)} {int(m.group(2)):02d}:{m.group(3)}").timestamp()
        except ValueError:
            return None
    # A day, a time, or both (in either order).
    day, clock = None, None
    words = t.split(" ")
    for cut in range(len(words), -1, -1):
        head, tail = " ".join(words[:cut]), " ".join(words[cut:])
        for d_text, c_text in ((head, tail), (tail, head)):
            d = memory.parse_due(d_text) if d_text else ""
            c = _clock(c_text) if c_text else None
            if (d or not d_text) and (c or not c_text) and (d or c):
                day, clock = d, c
                break
        if day or clock:
            break
    if not day and not clock:
        return None
    date = datetime.date.fromisoformat(day) if day else now.date()
    hour, minute = clock or (9, 0)
    at = datetime.datetime.combine(date, datetime.time(hour, minute))
    if not day and at <= now:                      # "at 7" said at 8: tomorrow's 7
        at += datetime.timedelta(days=1)
    return at.timestamp()


def say_when(at: float, now: float | None = None) -> str:
    """'today 18:30', 'tomorrow 09:00', 'Fri 14 Nov 10:00'."""
    d = datetime.datetime.fromtimestamp(at)
    today = datetime.datetime.fromtimestamp(now or time.time()).date()
    day = "today" if d.date() == today else "tomorrow" if d.date() == today + datetime.timedelta(days=1) else d.strftime("%a %-d %b")
    return f"{day} {d:%H:%M}"


# ---- reminders -----------------------------------------------------------------------------------------------------
def reminder_add(text: str, when: str = "", at: float | None = None) -> str:
    text = (text or "").strip()
    moment = at if at else parse_when(when)
    if not text:
        return "error: what should the reminder say?"
    if not moment:
        return f"error: couldn't tell when '{when}' is; say it like 'in 20 minutes', 'tomorrow 9am' or '2026-11-12 09:00'"
    if moment < time.time() - 60:
        return "error: that moment has already passed"
    with memory._lock:
        db = _db()
        db.execute("INSERT INTO reminders(text, at, ts) VALUES (?,?,?)", (text, moment, time.time()))
        db.commit()
    return f"reminder set for {say_when(moment)}: {text}"


def reminder_rows(include_fired: bool = False) -> list:
    with memory._lock:
        q = "SELECT * FROM reminders" + ("" if include_fired else " WHERE fired=0") + " ORDER BY at"
        return _db().execute(q).fetchall()


def _find(rows, match: str):
    match = str(match or "").strip()
    if match.isdigit():
        by_id = [r for r in rows if r["id"] == int(match)]
        if by_id:
            return by_id
        if 0 < int(match) <= len(rows):
            return [rows[int(match) - 1]]
    words = [w for w in re.findall(r"\w+", match.lower()) if len(w) > 2]
    return [r for r in rows if words and all(w in r["text"].lower() for w in words)] or \
           [r for r in rows if words and any(w in r["text"].lower() for w in words)][:1]


def reminder_remove(match: str) -> str:
    hit = _find(reminder_rows(), match)
    with memory._lock:
        db = _db()
        for r in hit:
            db.execute("DELETE FROM reminders WHERE id=?", (r["id"],))
        db.commit()
    return "removed: " + "; ".join(r["text"][:60] for r in hit) if hit else f"no reminder matching '{match}'"


def reminder_edit(match: str, text: str = "", when: str = "") -> str:
    hit = _find(reminder_rows(), match)[:1]
    if not hit:
        return f"no reminder matching '{match}'"
    r = hit[0]
    moment = parse_when(when) if when else r["at"]
    if when and not moment:
        return f"error: couldn't tell when '{when}' is"
    with memory._lock:
        db = _db()
        db.execute("UPDATE reminders SET text=?, at=?, fired=0 WHERE id=?", ((text or r["text"]).strip(), moment, r["id"]))
        db.commit()
    return f"reminder now {say_when(moment)}: {(text or r['text']).strip()}"


def reminder_list() -> str:
    rows = reminder_rows()
    return "\n".join(f"{i}. {say_when(r['at'])}: {r['text']}" for i, r in enumerate(rows, 1)) if rows else "no reminders set"


def todo_edit(match: str, text: str = "", due: str = "") -> str:
    """Change a to-do's words or its date ('none' clears the date)."""
    rows = memory.todo_rows("open")
    hit = _find(rows, match)[:1]
    if not hit:
        return f"no matching to-do for '{match}'"
    r = hit[0]
    new_due = r["due"]
    if due:
        new_due = None if due.strip().lower() in ("none", "no date", "clear") else (memory.parse_due(due) or None)
        if due.strip().lower() not in ("none", "no date", "clear") and not new_due:
            return f"error: couldn't tell which day '{due}' is"
    with memory._lock:
        db = memory._conn()
        db.execute("UPDATE todos SET text=?, due=? WHERE id=?", ((text or r["text"]).strip(), new_due, r["id"]))
        db.commit()
    return f"to-do now: {(text or r['text']).strip()}" + (f" (due {new_due})" if new_due else "")


async def run(a):
    """Says the reminders that are due. One that came due while Clove was off is said when it starts."""
    while True:
        try:
            now = time.time()
            due = [r for r in reminder_rows() if r["at"] <= now]
            for r in due:
                with memory._lock:
                    db = _db()
                    db.execute("UPDATE reminders SET fired=1 WHERE id=?", (r["id"],))
                    db.commit()
                late = now - r["at"] > 300
                await a._remind(r["text"] + (f" (it was due {say_when(r['at'])})" if late else ""))
        except Exception:
            log.exception("reminder check failed")
        await asyncio.sleep(15)


# ---- the calendar (iCal) -------------------------------------------------------------------------------------------
def calendar_url() -> str:
    try:
        return ICS_FILE.read_text().strip()
    except OSError:
        return ""


def set_calendar(url: str) -> str:
    url = (url or "").strip().replace("webcal://", "https://", 1)
    if not url:
        ICS_FILE.unlink(missing_ok=True)
        _ics.update(url="", at=0.0, events=[], error="")
        return "calendar disconnected"
    if not url.startswith("https://"):
        return "error: paste the calendar's https iCal address (in Google Calendar: Settings, your calendar, 'Secret address in iCal format')"
    events, error = _fetch(url)
    if error:
        return f"error: {error}"
    ICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ICS_FILE.write_text(url)
    ICS_FILE.chmod(0o600)                                  # the address is the key to the calendar
    _ics.update(url=url, at=time.time(), events=events, error="")
    return f"calendar connected: {len(events)} events"


def _unfold(text: str) -> list[str]:
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def _stamp(value: str, params: str) -> tuple[datetime.datetime, bool] | None:
    """An iCal date or date-time -> (local naive datetime, all-day?)."""
    value = value.strip()
    try:
        if re.fullmatch(r"\d{8}", value):
            return datetime.datetime.strptime(value, "%Y%m%d"), True
        d = datetime.datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    if value.endswith("Z"):
        return d.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None), False
    if m := re.search(r"TZID=([^;:]+)", params):
        try:
            import zoneinfo
            return d.replace(tzinfo=zoneinfo.ZoneInfo(m.group(1))).astimezone().replace(tzinfo=None), False
        except Exception:
            pass                                           # an unknown zone: taken as local time
    return d, False


def parse_ics(text: str) -> list[dict]:
    """The events of an iCal file: {title, start, end, all_day, rrule, where}; times local."""
    events, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"title": "", "where": "", "rrule": "", "start": None, "end": None, "all_day": False, "ex": []}
        elif line == "END:VEVENT":
            if cur and cur["start"] and cur.get("status") != "CANCELLED":
                cur["end"] = cur["end"] or cur["start"]
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            name, _, params = head.partition(";")
            if name == "SUMMARY":
                cur["title"] = value.replace("\\,", ",").replace("\\n", " ").replace("\\;", ";").strip()
            elif name == "LOCATION":
                cur["where"] = value.replace("\\,", ",").replace("\\n", " ").strip()
            elif name in ("DTSTART", "DTEND"):
                if got := _stamp(value, params):
                    cur["start" if name == "DTSTART" else "end"] = got[0]
                    if name == "DTSTART":
                        cur["all_day"] = got[1]
            elif name == "RRULE":
                cur["rrule"] = value
            elif name == "STATUS":
                cur["status"] = value.strip()
            elif name == "EXDATE":
                cur["ex"] += [g[0].date() for v in value.split(",") if (g := _stamp(v, params))]
    return events


_BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def occurrences(ev: dict, first: datetime.date, last: datetime.date) -> list[datetime.datetime]:
    """When an event starts between two days (inclusive), repeats included."""
    start: datetime.datetime = ev["start"]
    if not ev["rrule"]:
        return [start] if first <= start.date() <= last else []
    rule = dict(p.split("=", 1) for p in ev["rrule"].split(";") if "=" in p)
    freq, interval = rule.get("FREQ", ""), max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = None
    if rule.get("UNTIL") and (g := _stamp(rule["UNTIL"], "")):
        until = g[0].date()
    days = [_BYDAY[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d[-2:] in _BYDAY]
    out, n, day = [], 0, start.date()
    limit = min(last, until) if until else last
    guard = 0
    while day <= limit and guard < 20000:
        guard += 1
        weeks = (day - start.date()).days // 7
        months = (day.year - start.year) * 12 + day.month - start.month
        hit = False
        if freq == "DAILY":
            hit = (day - start.date()).days % interval == 0
        elif freq == "WEEKLY":
            hit = weeks % interval == 0 and (day.weekday() in days if days else day.weekday() == start.weekday())
        elif freq == "MONTHLY":
            hit = months % interval == 0 and day.day == start.day
        elif freq == "YEARLY":
            hit = (day.year - start.year) % interval == 0 and (day.month, day.day) == (start.month, start.day)
        if hit:
            n += 1
            if count is not None and n > count:
                break
            if day >= first and day not in ev["ex"]:
                out.append(datetime.datetime.combine(day, start.time()))
        day += datetime.timedelta(days=1)
    return out


def _fetch(url: str) -> tuple[list[dict], str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "clove-agenda"})
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read(8 * 1024 * 1024).decode("utf-8", "replace")
    except Exception as e:
        return [], f"couldn't read the calendar: {str(e)[:120]}"
    if "BEGIN:VCALENDAR" not in text:
        return [], "that address doesn't give a calendar (it should end in .ics)"
    return parse_ics(text), ""


def events_between(first: datetime.date, last: datetime.date) -> list[dict]:
    """The connected calendar's events in a span of days, fetched again when the copy is old."""
    url = calendar_url()
    if not url:
        return []
    if _ics["url"] != url or time.time() - _ics["at"] > FETCH_EVERY_S:
        events, error = _fetch(url)
        if not error or _ics["url"] != url:
            _ics.update(url=url, events=events)
        _ics.update(at=time.time(), error=error)
    out = []
    for ev in _ics["events"]:
        length = ev["end"] - ev["start"]
        for at in occurrences(ev, first, last):
            out.append({"title": ev["title"] or "(no title)", "day": at.date().isoformat(),
                        "time": "" if ev["all_day"] else f"{at:%H:%M}", "end": "" if ev["all_day"] else f"{at + length:%H:%M}",
                        "where": ev["where"]})
    return sorted(out, key=lambda e: (e["day"], e["time"]))


def events_text(when: str = "today") -> str:
    """What is on the calendar, for the voice: today, tomorrow, week, or a day."""
    today = datetime.date.today()
    if not calendar_url():
        return "no calendar is connected (paste its iCal address in Clove Notch's calendar, or say 'connect my calendar')"
    if when == "week":
        first, last = today, today + datetime.timedelta(days=7)
    else:
        day = memory.parse_due(when) or today.isoformat()
        first = last = datetime.date.fromisoformat(day)
    evs = events_between(first, last)
    if _ics["error"]:
        return f"error: {_ics['error']}"
    return "\n".join(f"{e['day']} {e['time'] or 'all day'}: {e['title']}" + (f" ({e['where']})" if e["where"] else "") for e in evs) or "nothing on the calendar then"


# ---- Clove Notch (ctl.py: `agenda <json>`) -------------------------------------------------------------------------
def snapshot(month: str = "") -> dict:
    """Everything the notch shows: open to-dos, pending reminders, and the month's calendar events."""
    today = datetime.date.today()
    try:
        y, m = (int(x) for x in month.split("-")) if month else (today.year, today.month)
        first = datetime.date(y, m, 1)
    except ValueError:
        first = today.replace(day=1)
    last = (first + datetime.timedelta(days=40)).replace(day=1) - datetime.timedelta(days=1)
    return {
        "todos": [{"id": r["id"], "text": r["text"], "due": r["due"] or ""} for r in memory.todo_rows("open")],
        "reminders": [{"id": r["id"], "text": r["text"], "at": int(r["at"] * 1000)} for r in reminder_rows()],
        "events": events_between(first, last),
        "calendar": bool(calendar_url()),
        "calendarError": _ics["error"],
        "month": first.strftime("%Y-%m"),
    }


def handle(arg: str) -> str:
    """One request from the notch, one JSON line back: {"ok": bool, "say": str, ...snapshot}."""
    try:
        q = json.loads(arg or "{}")
    except ValueError:
        return json.dumps({"ok": False, "say": "bad request"})
    op, say = q.get("op", "list"), ""
    ident = str(q.get("id", ""))
    if op == "todo_add":
        say = memory.todo_add([str(q.get("text", ""))], "notch", str(q.get("due", "")))
    elif op in ("todo_done", "todo_remove"):
        with memory._lock:
            db = memory._conn()
            if op == "todo_remove":
                db.execute("DELETE FROM todos WHERE id=?", (ident,))
            else:
                db.execute("UPDATE todos SET status='done', done_ts=? WHERE id=?", (time.time(), ident))
            db.commit()
        say = "done"
    elif op == "todo_edit":
        say = todo_edit(ident, str(q.get("text", "")), str(q.get("due", "")))
    elif op == "reminder_add":
        say = reminder_add(str(q.get("text", "")), str(q.get("when", "")))
    elif op == "reminder_remove":
        say = reminder_remove(ident)
    elif op == "reminder_edit":
        say = reminder_edit(ident, str(q.get("text", "")), str(q.get("when", "")))
    elif op == "calendar":
        say = set_calendar(str(q.get("url", "")))
    return json.dumps({"ok": not say.startswith("error"), "say": say, **snapshot(str(q.get("month", "")))})
