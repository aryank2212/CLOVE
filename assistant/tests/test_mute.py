"""Muting CLOVE from anywhere (the window, Clove Notch's mic button, a phone call): it stops listening, and the window
and the notch both show it."""
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


ui, notch = [], []
a = SimpleNamespace(muted=False, ui=SimpleNamespace(send=lambda **k: ui.append(k)),
                    notch=SimpleNamespace(event=lambda name, **k: notch.append((name, k))))
a.set_muted = lambda on: base.Assistant.set_muted(a, on)


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


asyncio.run(main())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
