"""Call audio on a Mac: the same job as call_audio.py (PipeWire), with two BlackHole virtual devices.

    Clove's voice  ->  output "BlackHole 2ch"   ->  the call tab records input "BlackHole 2ch" as its microphone
    the call tab's sound  ->  output "BlackHole 16ch"  ->  Clove listens to input "BlackHole 16ch"
    and CLOVE itself plays both sides to your speakers/headphones, so you hear the call live

macOS can't move one app's audio to another device from outside, so the Chrome extension does it inside the call tab
(chrome_extension/call_route.js): the page's microphone track is swapped for BlackHole 2ch and its speakers are
pointed at BlackHole 16ch (setSinkId). Only the call tab is touched; your music and other tabs keep your real devices,
and everything is put back when the call ends.

One-time setup: brew install blackhole-2ch blackhole-16ch (scripts/setup_mac.sh does it), then restart CLOVE."""
import asyncio
import logging
import os
import queue
import re
import threading
import time

import numpy as np
import sounddevice as sd

import audio

log = logging.getLogger("clove.call.audio")
TO_CALL = os.environ.get("MAC_CALL_VOICE_DEVICE", "BlackHole 2ch")      # Clove's voice into the call
FROM_CALL = os.environ.get("MAC_CALL_SOUND_DEVICE", "BlackHole 16ch")   # the call's sound to Clove
IN_RATE, OUT_RATE = 16000, 24000
SETUP_HINT = ("calls on a Mac need two BlackHole virtual audio devices: run `brew install blackhole-2ch blackhole-16ch` "
              "(or scripts/setup_mac.sh), then restart CLOVE")


def _bridge_call(loop, cmd: str, timeout: float = 10, **args) -> str:
    """Ask the extension from a worker thread (CallAudio's methods run in asyncio.to_thread)."""
    from browser_bridge import bridge
    if loop is None or not bridge.connected:
        return "error: the Chrome extension isn't connected"
    fut = asyncio.run_coroutine_threadsafe(bridge.call(cmd, timeout=timeout, **args), loop)
    try:
        return fut.result(timeout + 3)
    except Exception as e:
        return f"error: {e}"


def devices_present() -> tuple[bool, bool]:
    return audio.pa_index(TO_CALL, "output") is not None, audio.pa_index(FROM_CALL, "input") is not None


class Monitor:
    """Plays the call to his speakers: Clove's side and the caller's side, mixed (24 kHz mono)."""

    def __init__(self):
        self.bufs = {"mouth": bytearray(), "ear": bytearray()}
        self.lock = threading.Lock()
        dev = audio.pa_index(audio.mac_default("output"), "output")
        self.stream = sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", device=dev, blocksize=480,
                                         latency="low", callback=self._cb)
        self.stream.start()

    def push(self, side: str, pcm24: bytes):
        with self.lock:
            b = self.bufs[side]
            b.extend(pcm24)
            if len(b) > OUT_RATE * 2:                    # never fall more than a second behind
                del b[:len(b) - OUT_RATE // 5 * 2]

    def _cb(self, outdata, frames, t, status):
        n = frames * 2
        with self.lock:
            parts = []
            for b in self.bufs.values():
                parts.append(np.frombuffer(bytes(b[:n]).ljust(n, b"\0"), dtype=np.int16).astype(np.int32))
                del b[:n]
        outdata[:] = np.clip(sum(parts), -32768, 32767).astype(np.int16).tobytes()

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass


_monitor: Monitor | None = None


class CallAudio:
    def __init__(self, loop_to_speakers: bool = True, speaker_sink: str = "", match=None):
        self.loop_to_speakers = loop_to_speakers
        self.moved_in: dict[int, str] = {}       # call-tab speakers pointed at BlackHole (counted for the log)
        self.moved_out: dict[int, str] = {}      # call-tab microphones swapped for BlackHole
        self.owner_mic = False
        self.active = False
        self.adopted = False
        self.scope_of = lambda: {}               # CallManager sets this: which tab IS the call
        self._watch: threading.Thread | None = None
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None

    def setup(self, attach: bool = False):
        global _monitor
        voice, sound = devices_present()
        if not (voice and sound):
            raise RuntimeError(SETUP_HINT)
        if self.loop_to_speakers and _monitor is None:
            _monitor = Monitor()
        self.adopted = not attach                   # attach: the call's streams already exist; take them over on the first pass
        self.active = True
        self.route_once()
        self._watch = threading.Thread(target=self._keep_routed, daemon=True)
        self._watch.start()
        log.info("call audio ready (%s -> call, call -> %s)", TO_CALL, FROM_CALL)

    @staticmethod
    def teardown_leftovers():
        """Nothing to clean on a Mac: the BlackHole devices are permanent and the page hooks end with the tab."""

    def teardown(self):
        global _monitor
        self.active = False
        out = _bridge_call(self.loop, "call_audio_route", 10, release=True, **self.scope_of())
        log.info("call audio released (%s)", out[:120])
        if _monitor is not None:
            _monitor.close()
            _monitor = None
        self.moved_in.clear()
        self.moved_out.clear()

    def route_once(self) -> tuple[int, int]:
        """Point the call tab's microphone and speakers at the BlackHole devices (idempotent; run every 1.5 s)."""
        out = _bridge_call(self.loop, "call_audio_route", 12, mic=TO_CALL, speaker=FROM_CALL, owner=self.owner_mic,
                           adopt=not self.adopted, **self.scope_of())
        if out.startswith("error"):
            log.warning("call audio: %s", out[:200])
            return 0, 0
        self.adopted = True
        mics = int(m.group(1)) if (m := re.search(r"mic (\d+)", out)) else 0
        spk = int(m.group(1)) if (m := re.search(r"speaker (\d+)", out)) else 0
        self.moved_out = {i: TO_CALL for i in range(mics)}
        self.moved_in = {i: FROM_CALL for i in range(spk)}
        if "err:" in out:
            log.info("call audio: %s", out[:200])
        return spk, mics

    def _keep_routed(self):
        while self.active:
            time.sleep(1.5)
            if not self.active:
                break
            try:
                self.route_once()
            except Exception:
                log.exception("routing")

    def give_back_streams(self):
        _bridge_call(self.loop, "call_audio_route", 10, release=True, **self.scope_of())

    def adopt_all(self):
        """He joined before Clove arrived: take over the media the call page already has (the extension finds it)."""
        self.adopted = False
        n_in, n_out = self.route_once()
        log.info("call audio: took over %d speaker and %d microphone stream(s)", n_in, n_out)
        return n_in, n_out

    def hand_mic_to_owner(self, on: bool):
        """True: the call hears his real microphone (he talks himself); False: it hears Clove."""
        self.owner_mic = on
        self.route_once()


class Mouth:
    """Plays 24 kHz mono PCM into the call (BlackHole 2ch, both channels), paced by the device, so an interruption
    cuts the speech off at once. He hears it too, through the Monitor."""

    def __init__(self, sink: str = TO_CALL):
        self._buf = bytearray()
        self._lock = threading.Lock()
        self.last_sound = 0.0
        self.held = False
        self.stream = sd.RawOutputStream(samplerate=OUT_RATE, channels=2, dtype="int16",
                                         device=audio.pa_index(sink, "output"), blocksize=480, latency="low",
                                         callback=self._cb)
        audio.OPEN_EXTRA.add(self)
        self.stream.start()

    def hold(self, on: bool):
        self.held = on

    def write(self, pcm: bytes):
        with self._lock:
            self._buf.extend(pcm)

    def clear(self):
        with self._lock:
            self._buf.clear()

    @property
    def speaking(self) -> bool:
        return bool(self._buf) or time.monotonic() - self.last_sound < 0.3

    def _cb(self, outdata, frames, t, status):
        n = frames * 2
        if self.held:
            data = b""
        else:
            with self._lock:
                data = bytes(self._buf[:n])
                del self._buf[:n]
        if data:
            self.last_sound = time.monotonic()
            if _monitor is not None:
                _monitor.push("mouth", data)
        mono = np.frombuffer(data.ljust(n, b"\0"), dtype=np.int16)
        outdata[:] = np.repeat(mono, 2).tobytes()             # same voice on both channels

    def close(self):
        audio.OPEN_EXTRA.discard(self)
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass


def _to_24k(pcm16k: bytes) -> bytes:
    x = np.frombuffer(pcm16k, dtype=np.int16).astype(np.float32)
    if not x.size:
        return b""
    t = np.arange(0, x.size, 2 / 3)
    return np.interp(t, np.arange(x.size), x).astype(np.int16).tobytes()


class Ear:
    """What the call sounds like (16 kHz mono int16), from BlackHole 16ch. read() blocks like the Linux version."""

    def __init__(self, source: str = FROM_CALL):
        self.q: queue.Queue = queue.Queue(maxsize=400)
        self.pending = bytearray()
        self.stream = sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16",
                                        device=audio.pa_index(source, "input"), blocksize=640, latency="low",
                                        callback=self._cb)
        audio.OPEN_EXTRA.add(self)
        self.stream.start()

    def _cb(self, indata, frames, t, status):
        data = bytes(indata)
        if _monitor is not None:
            _monitor.push("ear", _to_24k(data))
        try:
            self.q.put_nowait(data)
        except queue.Full:
            pass

    def read(self, ms: int = 40) -> bytes:
        need = IN_RATE * 2 * ms // 1000
        while len(self.pending) < need:
            try:
                self.pending.extend(self.q.get(timeout=2))
            except queue.Empty:
                return b""
        out = bytes(self.pending[:need])
        del self.pending[:need]
        return out

    def close(self):
        audio.OPEN_EXTRA.discard(self)
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass
