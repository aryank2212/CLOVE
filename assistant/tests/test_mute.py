"""Muting CLOVE from anywhere (the window, Clove Notch's mic button, a phone call): it stops listening, and the window
and the notch both show it. It also stops talking at once and says nothing new; what came in is told on unmute."""
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


ui, notch, told, cleared = [], [], [], []


class Brain:
    async def notify(self, note):
        told.append(note)


a = SimpleNamespace(muted=False, ui=SimpleNamespace(send=lambda **k: ui.append(k)),
                    notch=SimpleNamespace(event=lambda name, **k: notch.append((name, k))),
                    speaker=SimpleNamespace(clear=lambda: cleared.append(1)), held_notes=[], pending_notes=[],
                    brain=Brain(), connected=True)
a.set_muted = lambda on: base.Assistant.set_muted(a, on)
a.notify = lambda note: base.Assistant.notify(a, note)


async def main():
    check("the notch's button mutes", await ctl.command(a, "mute toggle") == "muted" and a.muted)
    check("the window is told", ui[-1] == {"type": "muted", "value": True})
    check("the notch is told", notch[-1] == ("CloveMute", {"muted": True}))
    check("and unmutes", await ctl.command(a, "mute toggle") == "listening" and not a.muted)
    n = len(ui)
    check("asking changes nothing", await ctl.command(a, "mute status") == "listening" and len(ui) == n)
    await ctl.command(a, "mute off")
    check("no change: nobody is told again", len(ui) == n)
    check("mute on", await ctl.command(a, "mute on") == "muted")
    check("it stops talking at once", cleared)
    await a.notify("Sam messaged on WhatsApp: hi")
    await a.notify("Riya messaged on Instagram: call me")
    check("nothing is said while muted", told == [] and len(a.held_notes) == 2)
    await ctl.command(a, "mute off")
    await asyncio.sleep(0)
    check("on unmute, one summary of what came in", len(told) == 1 and "Sam" in told[0] and "Riya" in told[0]
          and a.held_notes == [])
    await a.notify("Ali messaged")
    check("unmuted: told as usual", told[-1] == "Ali messaged")


asyncio.run(main())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
