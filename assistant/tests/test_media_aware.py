"""Music on the speakers (media_aware.py): CLOVE tells it from its own sound, wakes only to its name said clearly
at the start, sleeps sooner, ignores notifications as a reason to listen, and turns the music down while awake."""
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import media_aware as M  # noqa: E402
import wake  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


def stream(i, app, corked=False, pid="1234", node="", media="", vol=65536):
    return {"index": i, "corked": corked, "volume": {"front-left": {"value": vol}, "front-right": {"value": vol}},
            "properties": {"application.name": app, "application.process.id": pid, "node.name": node, "media.name": media}}


raw = json.dumps([
    stream(1, "PipeWire ALSA [python3.14]", pid=None),            # CLOVE's own voice
    stream(2, "clove-notch"),                                       # Clove Notch's sounds
    stream(3, "Zen", corked=True),                                  # a paused video
    stream(4, "Spotify"),                                           # music
    stream(5, "", node="clove_from_call", media="loopback-1"),      # call audio
    stream(6, "Mine", pid=str(os.getpid())),                        # this process
])
found = M.foreign_streams(raw)
check("only other apps' running sound counts", [s["index"] for s in found] == [4])
check("with its volume", found and found[0]["volume"] == [65536, 65536])
check("bad output is nothing", M.foreign_streams("not json") == [])

# ---- playing: a player says so, or a stream that lasts (not a notification ding) --------------------------
a = SimpleNamespace(dashboard=SimpleNamespace(prefs={}), muted=False, speaking=lambda: False)
w = M.MediaWatch(a)
t0 = 100.0
w.update(found, False, t0)
check("a stream that just started is not music yet", not w.playing)
w.update(found, False, t0 + 2.5)
check("after two seconds it is", w.playing)
w.update([], False, t0 + 4)
check("stopped", not w.playing)
w.update([], True, t0 + 5)
check("a player saying Playing is enough", w.playing)
a.dashboard.prefs["musicaware"] = False
w.update(found, True, t0 + 6)
check("the setting off: never", not w.playing)
a.dashboard.prefs["musicaware"] = True

# ---- the wake word with music on ------------------------------------------------------------------------
check("normal: the name at the end wakes", wake.wake_pattern(["clove", "rose"]).search("a song about a rose"))
strict = wake.strict_pattern(["clove", "rose"])
check("music: a name inside a line does not", not strict.search("every rose has its thorn"))
check("music: nor at the end", not strict.search("she gave me a rose"))
check("music: 'Clove, pause the music' does", strict.search("Clove, pause the music"))
check("music: 'hey Rose' does", strict.search("hey Rose what time is it"))

g = wake.WakeGate.__new__(wake.WakeGate)
g.a = SimpleNamespace(media=w)
g.enabled = True
g.awake_until = 0.0
w.playing = True
check("music: a shorter window", g.window() == min(config.WAKE_WINDOW_S, M.MEDIA_WAKE_WINDOW_S))
g.a = SimpleNamespace(media=w, speaking=lambda: False, awaiting=False, busy=False,
                      calls=SimpleNamespace(audible=lambda: False), tools=SimpleNamespace(plan=None))
g.wake("notification")
check("music: a notification doesn't wake CLOVE", g.awake_until == 0.0)
g.wake("ctl")
check("but anything he does does", g.awake_until > time.monotonic())
w.playing = False
check("no music: the usual window", g.window() == config.WAKE_WINDOW_S)

# ---- turning the music down and back ------------------------------------------------------------------
calls = []
M._run = lambda *args, **k: calls.append(args) or ""
w.playing = True
a.wake = SimpleNamespace(enabled=True, awake=lambda: True)
check("awake with music: turn it down", w.want_duck())
w.duck(found)
check("to 30%", calls[-1] == ("pactl", "set-sink-input-volume", "4", str(int(65536 * M.DUCK_TO)), str(int(65536 * M.DUCK_TO))))
n = len(calls)
w.duck(found)
check("once", len(calls) == n)
w.unduck()
check("and back to what it was", calls[-1] == ("pactl", "set-sink-input-volume", "4", "65536", "65536") and not w.ducked)
a.muted = True
check("muted CLOVE doesn't touch the music", not w.want_duck())
a.muted = False
a.wake = SimpleNamespace(enabled=True, awake=lambda: False)
check("asleep: the music stays as it is", not w.want_duck())

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
