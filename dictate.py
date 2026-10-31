"""Dictation into any app: while it is on, what he says is written by local Whisper and typed into the focused
window (wtype on Hyprland/wlroots; on GNOME, where apps can't be typed into, it goes to the clipboard and a
notification says to paste). Nothing reaches a brain or the cloud meanwhile.

Turn it on with a hotkey (scripts/clove-ctl dictate), the window, or by saying "start dictation"; "stop
dictation" (or the hotkey again) ends it. So does a sentence that starts with CLOVE's name ("Clove, what time is
it?"): dictation ends and CLOVE answers it. Two minutes without speech end it too. Spoken "new line" / "new
paragraph" become line breaks.
"""
import logging
import re
import shutil
import subprocess
import threading
import time

import config

log = logging.getLogger("clove.dictate")
RATE = 16000
END_SILENCE_S = 0.8
IDLE_STOP_S = 120                     # dictation left on by mistake ends after this long without speech
STOP = re.compile(r"^\W*(?:stop|end|finish|cancel|exit|quit) (?:the )?dictation\W*$|^\W*(?:clove|rose),? stop\W*$", re.I)
SPOKEN = [(re.compile(r"\s*\bnew paragraph\b[.,]?\s*", re.I), "\n\n"), (re.compile(r"\s*\bnew line\b[.,]?\s*", re.I), "\n")]


def type_text(text: str) -> str:
    """Type text into the focused window; falls back to the clipboard."""
    if config.IS_MAC or config.IS_WINDOWS:
        import macos
    elif config.IS_WINDOWS:
        import windows as macos
        return macos.type_text(text)
    if shutil.which("wtype"):
        try:
            if subprocess.run(["wtype", "-"], input=text, text=True, timeout=20).returncode == 0:
                return "typed"
        except (OSError, subprocess.SubprocessError):
            pass
    if shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=text, text=True)
        subprocess.run(["notify-send", "Clove dictation", "Copied: press Ctrl+V to paste"], check=False)
        return "copied"
    return "error: neither wtype nor wl-copy is installed"


def addressed(text: str) -> bool:
    """The sentence starts with CLOVE's name (the wake word's spellings), so it is meant for CLOVE."""
    from wake import NAMES
    alts = "|".join(NAMES.get(n, re.escape(n)) for n in config.WAKE_NAMES)
    return bool(re.match(rf"^\W*(?:(?:hey|hi|ok|okay|hello|oi|yo|listen)\W+)?(?:{alts})\b", text, re.I))


class Dictation:
    def __init__(self, a):
        self.a = a
        self.on = False
        self.utt = bytearray()
        self.in_utt = False
        self.last_voice = 0.0
        self.stt = None
        self.lock = threading.Lock()
        self.words = 0

    # ---- control ------------------------------------------------------------------------
    def start(self) -> str:
        if self.on:
            return "Dictation is already on."
        self.on, self.words, self.last_voice = True, 0, 0.0
        self.a.stop_speaking()
        threading.Thread(target=self._load, daemon=True).start()
        import sounds
        sounds.play(self.a, "dictate_on")
        self.a.ui.send(type="notice", text="Dictating: speak, and it types where your cursor is. Say \"stop dictation\" to end.")
        log.info("dictation on")
        return "Dictation on. Speak and I'll type it where your cursor is; say stop dictation to end."

    def stop(self) -> str:
        if not self.on:
            return "Dictation isn't on."
        self.on = False
        if self.in_utt and len(self.utt) > RATE:
            self._submit(bytes(self.utt))
        self.in_utt = False
        import sounds
        self.a.loop.call_soon_threadsafe(sounds.play, self.a, "dictate_off")
        self.a.ui.send(type="notice", text="")
        log.info("dictation off (%d words)", self.words)
        return f"Dictation off, {self.words} words typed."

    def _hand_over(self, text: str):
        """Dictation off, and the words go to CLOVE as if typed in its window."""
        self.stop()
        self.a.on_ui({"type": "text", "text": text})

    def toggle(self) -> str:
        return self.stop() if self.on else self.start()

    def _load(self):
        """Reuse the brain's Whisper when it has one loaded (Hybrid/Qwen); otherwise load our own."""
        brain = self.a.brain
        if getattr(brain, "stt", None) is not None:
            self.stt = brain.stt
            return
        if self.stt is None:
            from prompt import vocabulary
            from stt import STT
            self.stt = STT(vocabulary())

    # ---- audio thread ---------------------------------------------------------------------
    def on_audio(self, data: bytes, voice: bool, now: float) -> bool:
        """True when dictation consumed this chunk (it must not reach the brain)."""
        if not self.on:
            return False
        if not self.last_voice:
            self.last_voice = now
        if not voice and not self.in_utt and now - self.last_voice > IDLE_STOP_S:
            log.info("no speech for %d s: dictation off", IDLE_STOP_S)
            self.a.loop.call_soon_threadsafe(self.stop)
            return True
        if voice:
            if not self.in_utt:
                self.in_utt, self.utt = True, bytearray()
            self.last_voice = now
        if self.in_utt:
            self.utt.extend(data)
            if now - self.last_voice > END_SILENCE_S or len(self.utt) > RATE * 2 * 25:
                self.in_utt = False
                if len(self.utt) > RATE * 2 * 0.3:
                    self._submit(bytes(self.utt))
        return True

    def _submit(self, pcm: bytes):
        threading.Thread(target=self._write, args=(pcm,), daemon=True).start()

    def _write(self, pcm: bytes):
        with self.lock:                                   # keep pieces in the order they were spoken
            for _ in range(100):
                if self.stt is not None:
                    break
                time.sleep(0.1)
            if self.stt is None:
                return
            text = self.stt.transcribe(pcm).strip()
            if not text:
                return
            if STOP.match(text):
                self.a.loop.call_soon_threadsafe(self.stop)
                return
            if addressed(text):                           # "Clove, ..." is for CLOVE, not for the page
                log.info("addressed while dictating: dictation off, answering %r", text[:80])
                self.a.loop.call_soon_threadsafe(self._hand_over, text)
                return
            for rx, rep in SPOKEN:
                text = rx.sub(rep, text)
            out = type_text(text if text.endswith("\n") else text + " ")
            self.words += len(text.split())
            log.info("dictated %d words (%s)", len(text.split()), out)
