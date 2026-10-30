"""Generates branding/sounds/*.wav: the fork's own sounds, one for each name in src/core/sound.ts. Run it with any
Python that has numpy: python3 branding/make_sounds.py"""
import wave
from pathlib import Path

import numpy as np

RATE = 44100
OUT = Path(__file__).parent / "sounds"


def tone(f, d, vol=0.5, decay=9.0, f2=None):
    n = int(RATE * d)
    t = np.arange(n) / RATE
    if f <= 0:
        return np.zeros(n)
    freq = f if f2 is None else f + (f2 - f) * t / d          # optional glide
    ph = 2 * np.pi * np.cumsum(np.broadcast_to(freq, t.shape)) / RATE
    w = np.sin(ph) + 0.22 * np.sin(2 * ph)
    return w * np.minimum(1, t / 0.005) * np.exp(-t * decay) * vol


def seq(*notes):
    return np.concatenate([tone(*n) for n in notes] + [np.zeros(int(RATE * 0.04))])


def noise(d, vol=0.25, decay=40):
    n = int(RATE * d)
    return np.random.default_rng(7).standard_normal(n) * np.exp(-np.arange(n) / RATE * decay) * vol


SOUNDS = {
    "peek": seq((660, .07), (880, .1)), "open": seq((587, .07), (784, .07), (988, .12)), "close": seq((784, .07), (587, .12)),
    "hover": seq((1568, .03, .25, 30)), "blip": seq((1175, .05, .35, 25)), "tick": seq((2093, .02, .3, 60)),
    "slap": np.concatenate([noise(.06, .5, 60), tone(180, .08, .4, 30)]), "annoyed": seq((330, .08), (311, .14)),
    "dizzy": seq((660, .35, .35, 4, 440)), "greet": seq((523, .08), (659, .08), (784, .16)),
    "greeting": seq((392, .12), (523, .12), (659, .12), (784, .3, .5, 4)),
    "work": seq((440, .06, .3), (554, .09, .3)), "finish": seq((784, .08), (1047, .08), (1319, .16)),
    "error": seq((440, .12), (330, .2)), "approval": seq((880, .1), (0, .05), (880, .14)),
    "question": seq((587, .18, .45, 7, 880)), "approve": seq((659, .06), (988, .14)),
    "gulp": seq((220, .09, .5, 18, 140)), "send": seq((523, .12, .35, 10, 1046)), "love": seq((784, .09), (988, .09), (1175, .14)),
    "pop": seq((880, .04, .4, 45)), "proud": seq((523, .1), (784, .1), (1047, .18)), "wink": seq((988, .05), (1319, .08)),
    "yawn": seq((523, .4, .35, 3, 330)), "attach": seq((740, .06), (988, .08)), "think": seq((494, .1, .3), (587, .12, .3)),
    "search": seq((659, .05, .3), (740, .05, .3), (831, .08, .3)), "rate": seq((392, .15), (349, .25)),
    "sleep": seq((880, .07), (587, .14)),
}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, x in SOUNDS.items():
        pcm = (np.clip(x, -1, 1) * 32767 * 0.9).astype(np.int16)
        with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm.tobytes())
    print(len(SOUNDS), "sounds in", OUT)
