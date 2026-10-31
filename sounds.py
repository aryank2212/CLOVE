"""Earcons: tiny synthesized chimes so you know Clove heard you, finished something, or went to sleep, without
words. Made with numpy at start-up (no files, no downloads), played through the same speaker as his voice."""
import numpy as np

import config

RATE = 24000
_cache: dict[str, bytes] = {}

# name -> list of (frequency Hz, seconds); 0 Hz is a rest
TUNES = {
    "wake": [(660, 0.07), (990, 0.11)],             # rising: "I'm listening"
    "done": [(784, 0.08), (1047, 0.08), (1319, 0.14)],
    "fail": [(440, 0.12), (330, 0.18)],             # falling
    "sleep": [(880, 0.07), (587, 0.12)],
    "dictate_on": [(523, 0.06), (0, 0.03), (784, 0.09)],
    "dictate_off": [(784, 0.06), (0, 0.03), (523, 0.09)],
}


def _tone(freq: float, secs: float, volume: float) -> np.ndarray:
    n = int(RATE * secs)
    if freq <= 0:
        return np.zeros(n, dtype=np.float32)
    t = np.arange(n) / RATE
    wave = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(4 * np.pi * freq * t)      # a soft bell-ish overtone
    env = np.minimum(1.0, t / 0.006) * np.exp(-t * 9)                             # quick attack, gentle decay
    return (wave * env * volume).astype(np.float32)


def pcm(name: str) -> bytes:
    if name not in _cache:
        notes = TUNES.get(name, TUNES["done"])
        x = np.concatenate([_tone(f, s, config.EARCON_VOLUME) for f, s in notes] + [np.zeros(int(RATE * 0.05), np.float32)])
        _cache[name] = (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()
    return _cache[name]


def play(a, name: str):
    """Play an earcon unless he is talking, Clove is speaking, or earcons are off."""
    if not config.EARCONS or not getattr(a, "speaker", None) or a.speaking():
        return
    a.speaker.write(pcm(name))
