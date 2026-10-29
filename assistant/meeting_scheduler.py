"""Meeting scheduler: create calendar events + send invites."""
import subprocess, logging, datetime
log = logging.getLogger("clove.meeting_scheduler")
def schedule(title, when, attendees="", duration=30):
    # Try gcalcli
    try:
        cmd = ["gcalcli","add","--title",title,"--when",when,"--duration",str(duration)]
        if attendees: cmd += ["--who",attendees]
        out = subprocess.run(cmd,capture_output=True,text=True,timeout=20).stdout.strip()
        return out or "scheduled (gcalcli)"
    except FileNotFoundError:
        return f"scaffold: would schedule '{title}' at {when} for {duration}min with {attendees}. Install gcalcli."
