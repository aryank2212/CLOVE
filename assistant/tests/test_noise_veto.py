"""Noise is not speech: a hissing microphone, a fan, a click or a hum never starts a turn, never reaches the recogniser
(a whole CPU core while it runs) and never goes to Gemini; real speech still starts a turn, first word included.
Run: .venv/bin/python tests/test_noise_veto.py"""
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import turn_taking as T  # noqa: E402
import wake as W  # noqa: E402
from tts import TTS  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


tts = TTS(); tts.voice = tts.k.get_voice_style("am_adam")


def speech(text):
    x = np.frombuffer(tts.synth(text), dtype=np.int16).astype(np.float32)
    return np.interp(np.linspace(0, len(x) - 1, int(len(x) * 16000 / 24000)), np.arange(len(x)), x).astype(np.int16)


rng = np.random.default_rng(7)
calls = []
rec = SimpleNamespace(model=object(), text=lambda pcm, language=None: (calls.append(len(pcm)), "Open YouTube.")[1])


def run(audio: np.ndarray):
    """Feeds 40 ms frames in simulated time; returns (events, taker)."""
    tt = T.TurnTaker(rec)
    events = []
    pcm = audio.astype(np.int16).tobytes()
    t = 1000.0
    for i in range(0, len(pcm) - 1279, 1280):
        events += tt.on_frame(pcm[i:i + 1280], False, t)
        t += 0.04
        if tt._deciding:                         # let a started read finish before the clock moves on
            threading.Event().wait(0.02)
    return events, tt


quiet = lambda s: rng.normal(0, 40, int(16000 * s))
hiss = lambda s: rng.normal(0, 700, int(16000 * s))                      # a loud hissing microphone
click = np.zeros(16000); click[4000:4500] = rng.normal(0, 9000, 500)     # a keyboard click or a bump
hum = 1200 * np.sin(2 * np.pi * 110 * np.arange(32000) / 16000) + rng.normal(0, 500, 32000)

for name, noise in [("a loud hiss", hiss(3)), ("a click", click), ("a hum", hum)]:
    calls.clear()
    ev, tt = run(np.concatenate([quiet(1), noise, quiet(2)]))
    check(f"{name}: no turn starts or ends", not ev)
    check(f"{name}: the recogniser is never run", not calls)

calls.clear()
voice = speech("Open YouTube and play some music.")
ev, tt = run(np.concatenate([quiet(1), voice, quiet(2.5)]))
check("speech: the turn starts", ev.count("start") == 1)
check("speech: and ends", ev.count("end") == 1)
check("speech: the recogniser reads the ending (at most twice)", 1 <= len(calls) <= 2)
check("speech: nothing was sent before the start", ev.index("start") <= ev.index("audio") if "audio" in ev else True)

# The first word is not lost: the start carries what was said before the turn was confirmed.
tt = T.TurnTaker(rec)
pcm = np.concatenate([quiet(1), voice]).astype(np.int16).tobytes()
t, started_with = 1000.0, 0
for i in range(0, len(pcm) - 1279, 1280):
    ev = tt.on_frame(pcm[i:i + 1280], False, t)
    t += 0.04
    if "start" in ev and not started_with:
        started_with = len(tt.utterance)
check("the first word is kept (start carries the held-back audio, >= 0.4 s)", started_with >= 16000 * 2 * 0.4)

# Nothing of the words is lost, however the sentence begins: the start carries what was held back, and the audio events
# carry the rest. (A slow, breathy start must not be judged noise and dropped with its first word.)
for label, lead in [("a clean start", quiet(0.5)), ("a breathy start", np.concatenate([quiet(0.5), rng.normal(0, 600, int(16000 * 0.35))])),
                    ("a bump, then words", np.concatenate([quiet(0.5), click[:3000], quiet(0.2)]))]:
    tt = T.TurnTaker(rec)
    pcm = np.concatenate([lead, voice, quiet(2.5)]).astype(np.int16).tobytes()
    t, sent, started = 1000.0, 0, False
    for i in range(0, len(pcm) - 1279, 1280):
        frame = pcm[i:i + 1280]
        ev = tt.on_frame(frame, False, t)
        t += 0.04
        if "start" in ev:
            sent += len(tt.utterance)
            started = True
        elif "audio" in ev and started:
            sent += len(frame)
        if "end" in ev:
            break
    check(f"{label}: all of the words are sent (nothing clipped)", started and sent >= len(voice) * 2)

# A hiss in front of speech: the hiss is dropped, the words still count.
calls.clear()
ev, tt = run(np.concatenate([quiet(0.5), hiss(0.6), quiet(1.0), voice, quiet(2.5)]))
check("a hiss and then speech: exactly one turn", ev.count("start") == 1 and ev.count("end") == 1)

# The wake gate does not read noise either.
calls.clear()
g = W.WakeGate.__new__(W.WakeGate)
g.recogniser = SimpleNamespace(model=SimpleNamespace(transcribe=lambda *a, **k: (calls.append(1), ([], None))[1]))
g.pattern = W.wake_pattern(["clove"]); g.strict = W.strict_pattern(["clove"]); g.busy = False
g.a = SimpleNamespace(media=None); g.replay = None; g.replay_text = ""
g._check(hiss(2).astype(np.int16).tobytes())
check("the wake gate skips noise without running the recogniser", not calls and not g.busy)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
