"""Clove Notch's Work / DND / Sleep slider (ctl "mode"): what CLOVE does in each."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import base  # noqa: E402
import ctl  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


told, focus = [], {"on": False}


class Brain:
    async def notify(self, note):
        told.append(note)


a = SimpleNamespace(muted=False, mode="off", _mode_muted=False, held_notes=[], pending_notes=[], brain=Brain(),
                    connected=True, ui=SimpleNamespace(send=lambda **k: None),
                    notch=SimpleNamespace(event=lambda *x, **k: None), speaker=SimpleNamespace(clear=lambda: None),
                    focus=SimpleNamespace(active=False))
a.focus.start = lambda m: (focus.__setitem__("on", True), setattr(a.focus, "active", True))
a.focus.stop = lambda: (focus.__setitem__("on", False), setattr(a.focus, "active", False))
a.set_muted = lambda on: base.Assistant.set_muted(a, on)
a.set_mode = lambda m: base.Assistant.set_mode(a, m)
a.notify = lambda note: base.Assistant.notify(a, note)


async def main():
    check("status", await ctl.command(a, "mode status") == "off")
    check("work starts a focus session", await ctl.command(a, "mode work") == "work" and focus["on"])
    check("dnd ends it", await ctl.command(a, "mode dnd") == "dnd" and not focus["on"])
    await a.notify("Sam messaged")
    check("dnd: nothing said, kept", told == [] and a.held_notes == ["Sam messaged"])
    await ctl.command(a, "mode off")
    await asyncio.sleep(0)
    check("off: one summary of what came in", len(told) == 1 and "Sam messaged" in told[0] and not a.held_notes)
    await ctl.command(a, "mode sleep")
    check("sleep: not listening", a.muted)
    await a.notify("Riya messaged")
    check("sleep: nothing said", len(told) == 1)
    await ctl.command(a, "mode off")
    await asyncio.sleep(0)
    check("waking up: listening again, and told", not a.muted and len(told) == 2 and "Riya" in told[-1])
    a.muted = True
    await ctl.command(a, "mode sleep")
    await ctl.command(a, "mode off")
    check("muted before sleep: stays muted after", a.muted)
    check("nonsense is off", await ctl.command(a, "mode party") == "off")


asyncio.run(main())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
