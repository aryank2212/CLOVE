"""Wake word: nothing reaches the brain (or the cloud) until he says "Clove" or "Rose".

While asleep, speech is cut into short utterances here and read by the small CPU Whisper that turn-taking already
loads, so no extra model or download is needed and any name works. When an utterance contains the name, Clove
wakes and that same utterance ("Clove, open YouTube") is replayed to the brain, so the command isn't lost. He stays
awake while the conversation goes on and for WAKE_WINDOW_S seconds after the last word from either side, then
falls asleep again. With Gemini that means no audio is streamed (or billed) while nobody is talking to him.
"""
import collections
import logging
import re
import threading
import time

import numpy as np

import config

log = logging.getLogger("clove.wake")
RATE = 16000
END_SILENCE_S = 0.45          # an utterance ends after this much quiet
MAX_UTT_S = 7.0

# Whisper's usual mishearings of the two names, plus "hey/ok/hi" in front.
NAMES = {"clove": r"cl[oa]ve?s?|klove|clover|glove|kloof",
         "rose": r"rose|roz|rosy|rosie"}


def wake_pattern(names: list[str]) -> re.Pattern:
    alts = "|".join(NAMES.get(n, re.escape(n)) for n in names)
    # The name must be near the start ("Clove, ...", "hey Rose ...") or the whole utterance ("... thanks Clove").
    return re.compile(rf"^\W*(?:(?:hey|hi|ok|okay|hello|oi|yo|listen)\W+)?(?:{alts})\b|\b(?:{alts})\W*$", re.I)


def _agent_waiting() -> bool:
    import ctl
    return bool(ctl.QUESTIONS)


class WakeGate:
    def __init__(self, a):
        self.a = a
        self.enabled = config.WAKE_WORD
        self.pattern = wake_pattern(config.WAKE_NAMES)
        self.awake_until = 0.0
        self.preroll = collections.deque(maxlen=12)       # ~380 ms before the first syllable
        self.utt = bytearray()
        self.in_utt = False
        self.last_voice = 0.0
        self.replay: bytes | None = None                  # a woken utterance, handed to the brain from the mic thread
        self.busy = False
        self.recogniser = None
        if self.enabled:
            from turn_taking import Recogniser
            self.recogniser = Recogniser.shared()

    # ---- state ---------------------------------------------------------------------------
    def awake(self, now: float | None = None) -> bool:
        if not self.enabled:
            return True
        a, now = self.a, now or time.monotonic()
        tools = a.tools
        engaged = (a.speaking() or a.awaiting or a.busy or a.calls.audible()
                   or (tools.plan and tools.plan.get("approval") == "pending") or _agent_waiting())
        if engaged:
            self.awake_until = max(self.awake_until, now + config.WAKE_WINDOW_S)
        return now < self.awake_until

    def wake(self, why: str):
        if not self.awake():
            log.info("awake (%s)", why)
        self.awake_until = time.monotonic() + config.WAKE_WINDOW_S

    def sleep(self):
        self.awake_until = 0.0

    # ---- audio thread ----------------------------------------------------------------------
    def take_replay(self) -> list[bytes]:
        """The utterance that woke him, in mic-sized frames (fed to the brain as voice, before new audio)."""
        if self.replay is None:
            return []
        pcm, self.replay = self.replay, None
        return [pcm[i:i + 1024] for i in range(0, len(pcm), 1024)]

    def filter(self, chunks: list[bytes], voice: bool, now: float) -> list[bytes] | None:
        """Called for every mic chunk. Returns the chunks to give the brain, or None while asleep."""
        if self.awake(now):
            if voice:
                self.awake_until = now + config.WAKE_WINDOW_S
            self.in_utt = False
            return chunks
        data = b"".join(chunks)
        if voice:
            if not self.in_utt:
                self.in_utt, self.utt = True, bytearray(b"".join(self.preroll))
                self.preroll.clear()
            self.last_voice = now
        if not self.in_utt:
            self.preroll.append(data)
            return None
        self.utt.extend(data)
        if now - self.last_voice > END_SILENCE_S or len(self.utt) > RATE * 2 * MAX_UTT_S:
            self.in_utt = False
            if len(self.utt) > RATE * 2 * 0.3 and not self.busy:
                self.busy = True
                threading.Thread(target=self._check, args=(bytes(self.utt),), daemon=True).start()
        return None

    def _check(self, pcm: bytes):
        try:
            model = getattr(self.recogniser, "model", None)
            if model is None:                         # recogniser still loading: don't make him wait for it
                self._woken(pcm, "(recogniser loading)")
                return
            x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
            segs, _ = model.transcribe(x, beam_size=1, vad_filter=False, without_timestamps=True,
                                       condition_on_previous_text=False, initial_prompt=", ".join(config.WAKE_NAMES).title())
            text = " ".join(s.text for s in segs).strip()
            if text and self.pattern.search(text):
                self._woken(pcm, repr(text))
            elif text:
                log.debug("asleep, ignored: %r", text)
        except Exception as e:
            log.warning("wake check failed: %s", e)
        finally:
            self.busy = False

    def _woken(self, pcm: bytes, why: str):
        self.wake(why)
        self.replay = pcm                                  # the live silence that follows ends the turn
        try:
            import sounds
            self.a.loop.call_soon_threadsafe(sounds.play, self.a, "wake")
        except Exception:
            pass
