"""CLOVE's microphone follows the system's devices, but never on one reading: a device that blinks while headphones
are plugged in, or a pactl that doesn't answer, must not close and reopen the microphone."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import audio  # noqa: E402
from audio import MicFollower, Route  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    fails += not ok


MIC, HEADSET = "alsa_input.pci.HiFi__Mic1__source", "bluez_input.AA_BB"
seen = lambda src, ok=True: Route(source=src, ok=ok)  # noqa: E731

f = MicFollower()
check("the same mic: nothing to do", f.step(MIC, seen(MIC)) is None)
check("the mic vanishes for one look: kept", f.step(MIC, seen("")) is None)
check("and is back on the next: still kept", f.step(MIC, seen(MIC)) is None)
check("one blink later: still kept", f.step(MIC, seen("")) is None)
check("an unanswered look decides nothing", f.step(MIC, seen("", ok=False)) is None)
check("gone on a second answered look: follow it", f.step(MIC, seen("")) == "")

f = MicFollower()
check("headphones plugged in: not on the first look", f.step(MIC, seen(HEADSET)) is None)
check("their mic on the second look: switch", f.step(MIC, seen(HEADSET)) == HEADSET)
check("then settled", f.step(HEADSET, seen(HEADSET)) is None)

f = MicFollower()
f.step(MIC, seen(HEADSET))
check("a different choice starts the count again", f.step(MIC, seen("usb_mic")) is None)
check("and needs its own second look", f.step(MIC, seen("usb_mic")) == "usb_mic")

# pick_route marks a reading it could not complete, instead of reporting "no microphone".
real_json, real_default = audio._pactl_json, audio._default
try:
    audio._pactl_json = lambda *a: None
    audio._default = lambda kind: MIC if kind == "source" else ""
    r = audio.pick_route(prefer_headset=False)
    check("pactl failing: the reading is marked not ok", r.ok is False)
    sources = [{"name": MIC, "description": "Mic", "properties": {}, "state": "RUNNING"}]
    audio._pactl_json = lambda *a: sources if "sources" in a else []
    audio._default = lambda kind: MIC if kind == "source" else ""
    r = audio.pick_route(prefer_headset=False)
    check("pactl answering: ok, with the default mic", r.ok and r.source == MIC, str(r))
    audio._default = lambda kind: None
    check("no answer for the default: not ok", audio.pick_route(prefer_headset=False).ok is False)
finally:
    audio._pactl_json, audio._default = real_json, real_default

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
