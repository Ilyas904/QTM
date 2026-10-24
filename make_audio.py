"""Synthesizes the soundtrack for the demo: a calm ambient bed, mouse clicks, key presses.
Everything is generated here (no downloaded samples), so there are no licensing questions.
"""
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, lfilter
import pathlib, sys

SR = 44100
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/home/claude/audio"); OUT.mkdir(exist_ok=True, parents=True)
rng = np.random.default_rng(7)

def lowpass(x, cutoff, order=2):
    b, a = butter(order, cutoff / (SR / 2), btype="low"); return lfilter(b, a, x)

def highpass(x, cutoff, order=2):
    b, a = butter(order, cutoff / (SR / 2), btype="high"); return lfilter(b, a, x)

def env_asr(n, a, r):
    e = np.ones(n); na, nr = int(a * SR), int(r * SR)
    e[:na] = np.linspace(0, 1, na); e[-nr:] *= np.linspace(1, 0, nr); return e

def note(freq, dur, detune=0.0):
    t = np.arange(int(dur * SR)) / SR
    return np.sin(2 * np.pi * (freq + detune) * t)

# ---------------- music: 72 s, 80 bpm, slow four-chord loop -------------------
DUR = 72.0
bpm = 80; beat = 60 / bpm; bar = 4 * beat
A3, C4, E4, G4, B4, D5 = 220.0, 261.63, 329.63, 392.0, 493.88, 587.33
F3, A4 = 174.61, 440.0
G3, D4 = 196.0, 293.66
chords = [  # (root for bass, pad notes) — Am9, Fmaj7, Cmaj7, G6 — 2 bars each
    (A3 / 2, [A3, C4, E4, G4, B4]),
    (F3 / 2, [F3, A3, C4, E4, G4]),
    (C4 / 4, [C4 / 2, E4 / 2, G4, B4, D5]),
    (G3 / 2, [G3, B4 / 2, D4, G4, A4]),
]
music = np.zeros(int(DUR * SR))
chord_len = 2 * bar
t_cursor = 0.0
i = 0
while t_cursor < DUR:
    root, notes = chords[i % 4]
    n = int(min(chord_len, DUR - t_cursor) * SR)
    pad = np.zeros(n)
    for f in notes:
        for det in (-0.25, 0.0, 0.25):
            pad += note(f, n / SR, det) * 0.18
    pad += note(root, n / SR) * 0.35  # sub bass
    pad *= env_asr(n, 1.4, 1.6)
    start = int(t_cursor * SR)
    music[start:start + n] += pad[: len(music) - start]
    t_cursor += chord_len; i += 1
music = lowpass(music, 1800)

# soft pluck on beats 1 and 3, very quiet
pluck_len = int(0.6 * SR)
tp = np.arange(pluck_len) / SR
plk_env = np.exp(-tp * 6)
t_cursor = 0.0; i = 0
while t_cursor + 0.7 < DUR:
    root, notes = chords[(int(t_cursor // chord_len)) % 4]
    f = notes[2] * (2 if (i % 2) else 1)
    plk = (np.sin(2 * np.pi * f * tp) + 0.3 * np.sin(2 * np.pi * 2 * f * tp)) * plk_env * 0.09
    start = int(t_cursor * SR)
    music[start:start + pluck_len] += plk
    t_cursor += 2 * beat; i += 1

music *= env_asr(len(music), 2.0, 4.0)
music /= np.max(np.abs(music)) + 1e-9
wavfile.write(OUT / "music.wav", SR, (music * 0.5 * 32767).astype(np.int16))

# ---------------- mouse click: short filtered noise burst, down + up -----------
def click_sound():
    def tick(dur, f_hp, f_lp, gain):
        n = int(dur * SR); t = np.arange(n) / SR
        x = rng.standard_normal(n) * np.exp(-t * 180)
        x = lowpass(highpass(x, f_hp), f_lp)
        x += np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 400) * 0.4
        return x * gain
    down = tick(0.05, 900, 6000, 1.0)
    up = tick(0.04, 1200, 7000, 0.6)
    gap = np.zeros(int(0.07 * SR))
    x = np.concatenate([down, gap, up])
    return x / (np.max(np.abs(x)) + 1e-9)

wavfile.write(OUT / "click.wav", SR, (click_sound() * 0.6 * 32767).astype(np.int16))

# ---------------- key press: three variants of a soft thock --------------------
for k in range(3):
    n = int(0.045 * SR); t = np.arange(n) / SR
    x = rng.standard_normal(n) * np.exp(-t * (220 + 40 * k))
    x = lowpass(highpass(x, 600 + 150 * k), 4500 + 600 * k)
    x += np.sin(2 * np.pi * (1500 + 200 * k) * t) * np.exp(-t * 500) * 0.3
    x /= np.max(np.abs(x)) + 1e-9
    wavfile.write(OUT / f"key{k}.wav", SR, (x * 0.45 * 32767).astype(np.int16))

print("audio assets written to", OUT)
