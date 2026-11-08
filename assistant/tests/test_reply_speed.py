"""Reply speed: a finished sentence ends the turn sooner; the ending is read earlier, and only counts if nothing was
said since; the sentence that woke CLOVE goes to Gemini as one turn at once (no second wait)."""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import brain_gemini  # noqa: E402
import config  # noqa: E402
import turn_taking as T  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


# ---- how an ending is read ---------------------------------------------------------------------------
c = T.classify
check("a sentence with a full stop is complete", c("Send a message to Aniket saying I'll be late.") == "complete")
check("so is one with an exclamation mark", c("That works for me!") == "complete")
check("a trailing 'and' is still incomplete", c("Can you check my messages and") == "incomplete")
check("'...' is still incomplete", c("Can you check my messages and...") == "incomplete")
check("a full stop after a dangling word is incomplete", c("I was thinking that maybe we could, you know.") == "incomplete")
check("a single word with a full stop is not enough alone", c("Hello.") == "complete")   # greeting: in COMPLETE_SHORT
check("no full stop: still unsure", c("the weather in Mumbai") == "neutral")
check("the waits are shorter", T.WAIT["complete"] <= 0.4 and T.WAIT["neutral"] <= 0.9)
check("'came in' with a full stop is finished", c("Tell me what notifications came in.") == "complete")
check("'came in' without one: wait a little, not three seconds", c("the notifications that came in") == "unsure" and T.WAIT["unsure"] < 2)
check("a command ending in 'in' is complete at once", c("Tell me what notifications came in") == "complete")
check("'turn it on' is a command", c("turn it on") in ("complete",))
check("'send a message to' is still open", c("Send a message to") == "incomplete")
check("'I think that' is still open", c("so I think that") == "incomplete")
check("'because' is still open, with or without a stop", c("I can't because") == "incomplete" and c("I can't because.") == "incomplete")

# ---- a verdict for audio that was followed by more speech is dropped ---------------------------------
rec = SimpleNamespace(model=object(), text=lambda pcm, language=None: (time.sleep(0.25), "Open YouTube.")[1])
tt = T.TurnTaker(rec)
frame_loud = (np.ones(640) * 4000).astype(np.int16).tobytes()
frame_quiet = np.zeros(640, dtype=np.int16).tobytes()
t0 = 1000.0
for i in range(30):
    tt.on_frame(frame_loud, False, t0 + i * 0.04)               # 1.2 s of speech
last = t0 + 29 * 0.04
for i in range(1, 6):                                            # 0.2 s of quiet: the read starts
    tt.on_frame(frame_quiet, False, last + i * 0.04)
tt.on_frame(frame_loud, False, last + 0.3)                       # he talks again before it finishes
time.sleep(0.4)
check("speech resumed before the read finished: no verdict", tt.verdict is None)

tt2 = T.TurnTaker(rec)
for i in range(30):
    tt2.on_frame(frame_loud, False, t0 + i * 0.04)
for i in range(1, 6):
    tt2.on_frame(frame_quiet, False, last + i * 0.04)
time.sleep(0.4)
ev = []
for i in range(6, 40):
    ev += tt2.on_frame(frame_quiet, False, last + i * 0.04)
check("quiet after it: a verdict, and the turn ends", tt2.verdict == "complete" and "end" in ev)
check("the read started after only %.2f s of quiet" % T.CHECK_AFTER_S, T.CHECK_AFTER_S <= 0.2)


# ---- the sentence that woke CLOVE ----------------------------------------------------------------------
async def wake_case():
    loop = asyncio.get_running_loop()
    a = SimpleNamespace(loop=loop, speaker=None, speaking=lambda: False, stop_speaking=lambda: None)
    b = brain_gemini.GeminiBrain(a)
    sent = []
    b._enqueue = lambda d: sent.append(d if isinstance(d, tuple) else "audio")
    pcm = b"\x01\x00" * 16000
    ok_done = b.feed_replay(pcm, "Clove, open YouTube.")
    await asyncio.sleep(0.05)
    check("a finished wake sentence goes as one turn", ok_done and [x[0] if isinstance(x, tuple) else x for x in sent] == ["start", "end"])
    sent.clear()
    check("a trailing one is left to the turn-taker", not b.feed_replay(pcm, "Clove, can you check my messages and"))
    check("nothing sent for it", not sent)
    check("no text: not handled", not b.feed_replay(pcm, ""))

asyncio.run(wake_case())
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
