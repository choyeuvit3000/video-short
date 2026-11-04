"""Copyright-free horror background music, synthesized from scratch (numpy).

Each track: a slow minor/dissonant pad that drifts between chords, a detuned music box
playing sparse phrases, a heartbeat that comes and goes, rare high "string" swells, all
through a long reverb. `python -m tr.horrormusic [count]` writes assets/horror_music/*.wav.
"""
from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

from .util import ASSETS, log

SR = 48000
DIR = ASSETS / "horror_music"
MINOR = [0, 2, 3, 5, 7, 8, 11]          # harmonic minor: the raised 7th sounds uneasy
# chord roots (scale degrees, semitones) and their tones; b2 / tritone keep it unresolved
CHORDS = [(0, [0, 3, 7]), (8, [0, 4, 7]), (5, [0, 3, 7]), (7, [0, 4, 7, 13]),
          (1, [0, 4, 7]), (6, [0, 3, 6])]


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(spec, len(x))


def _pad(n: int, root: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(n) / SR
    out = np.zeros((2, n))
    seg = int(SR * rng.uniform(10, 14))
    order = [0] + list(rng.choice(range(1, len(CHORDS)), size=n // seg + 1))
    fade = int(SR * 3)
    for i, start in enumerate(range(0, n, seg)):
        off, tones = CHORDS[order[i]]
        a, b = max(0, start - fade), min(n, start + seg + fade)
        env = np.ones(b - a)
        env[:min(fade, b - a)] = np.linspace(0, 1, min(fade, b - a))
        env[-min(fade, b - a):] *= np.linspace(1, 0, min(fade, b - a))
        for tone in tones:
            f0 = _hz(root + off + tone)
            for ch in range(2):
                det = 1 + rng.uniform(-0.004, 0.004)
                ph = rng.uniform(0, 6.28)
                wave_ = sum(np.sin(2 * np.pi * f0 * det * k * t[a:b] + ph * k) / k for k in range(1, 7))
                out[ch, a:b] += wave_ * env / len(tones)
    swell = 0.6 + 0.4 * np.sin(2 * np.pi * t / rng.uniform(17, 26) + rng.uniform(0, 6))
    return np.stack([_lowpass(out[c], 650) for c in range(2)]) * swell * 0.5


def _music_box(n: int, root: int, rng: np.random.Generator) -> np.ndarray:
    out = np.zeros((2, n))
    note_len = int(SR * 2.2)
    tt = np.arange(note_len) / SR
    pos, deg = int(SR * rng.uniform(6, 12)), 0
    while pos < n - note_len:
        for _ in range(int(rng.integers(4, 9))):          # one phrase
            deg = int(np.clip(deg + rng.choice([-2, -1, -1, 1, 1, 2, 3, -3]), -3, 10))
            octave, idx = divmod(deg, len(MINOR))
            midi = root + 36 + 12 * octave + MINOR[idx]
            f = _hz(midi) * (1 + 0.006 * np.sin(2 * np.pi * 0.7 * tt))   # warped, old box
            tone = (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * 2.01 * f * tt)
                    + 0.12 * np.sin(2 * np.pi * 5.4 * f * tt)) * np.exp(-tt * 2.6)
            tone[:200] *= np.linspace(0, 1, 200)
            pan = rng.uniform(0.3, 0.7)
            end = min(n, pos + note_len)
            out[0, pos:end] += tone[:end - pos] * (1 - pan)
            out[1, pos:end] += tone[:end - pos] * pan
            pos += int(SR * rng.choice([0.45, 0.6, 0.6, 0.9, 1.2]))
            if pos >= n - note_len:
                break
        pos += int(SR * rng.uniform(5, 14))               # silence between phrases
    return out * 0.22


def _heartbeat(n: int, rng: np.random.Generator) -> np.ndarray:
    out = np.zeros(n)
    beat = int(SR * 0.16)
    tb = np.arange(beat) / SR
    thump = np.sin(2 * np.pi * 48 * tb) * np.exp(-tb * 28) * np.minimum(1, tb / 0.012)
    pos = int(SR * rng.uniform(20, 40))
    while pos < n - SR * 12:
        bpm = rng.uniform(58, 76)
        for k in range(int(rng.integers(8, 18))):
            p = pos + int(k * SR * 60 / bpm)
            if p + beat + int(SR * 0.22) >= n:
                break
            g = min(1, (k + 1) / 4)
            out[p:p + beat] += thump * g
            q = p + int(SR * 0.22)
            out[q:q + beat] += thump * 0.7 * g
        pos += int(SR * rng.uniform(35, 60))
    out = _lowpass(out, 140)
    return np.stack([out, out]) * 0.55


def _swells(n: int, root: int, rng: np.random.Generator) -> np.ndarray:
    out = np.zeros((2, n))
    pos = int(SR * rng.uniform(25, 45))
    while pos < n - SR * 10:
        ln = int(SR * rng.uniform(5, 8))
        t = np.arange(ln) / SR
        env = np.sin(np.pi * t / t[-1]) ** 2
        base = _hz(root + 48 + rng.choice([1, 6, 11]))
        cluster = sum(np.sin(2 * np.pi * base * (1 + d) * t) for d in (0, 0.03, 0.061))
        cluster *= 1 + 0.3 * np.sin(2 * np.pi * 6.5 * t)       # trembling bow
        for ch in range(2):
            out[ch, pos:pos + ln] += cluster * env * 0.06 * (0.7 if ch else 1)
        pos += int(SR * rng.uniform(40, 70))
    return out


def _reverb(x: np.ndarray, rng: np.random.Generator, secs: float = 3.2) -> np.ndarray:
    m = int(SR * secs)
    t = np.arange(m) / SR
    out = np.empty_like(x)
    size = 1 << int(np.ceil(np.log2(x.shape[1] + m)))
    for ch in range(2):
        ir = rng.standard_normal(m) * np.exp(-t * 6.5 / secs)
        ir /= np.sqrt(np.sum(ir ** 2))
        wet = np.fft.irfft(np.fft.rfft(x[ch], size) * np.fft.rfft(ir, size), size)[:x.shape[1]]
        out[ch] = 0.55 * x[ch] + 0.8 * wet
    return out


def make_track(path: Path, seed: int, seconds: int = 150) -> Path:
    rng = np.random.default_rng(seed)
    n = SR * seconds
    root = int(rng.integers(36, 44))                      # C2..G#2
    mix = (_pad(n, root, rng) + _music_box(n, root, rng) + _swells(n, root, rng))
    mix = _reverb(mix, rng) + _heartbeat(n, rng)
    fade = SR * 4
    mix[:, :fade] *= np.linspace(0, 1, fade)
    mix[:, -fade:] *= np.linspace(1, 0, fade)
    mix *= 0.89 / np.max(np.abs(mix))
    pcm = (mix.T * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(pcm.tobytes())
    return path


def tracks() -> list[Path]:
    return sorted(p for p in DIR.glob("*") if p.suffix.lower() in {".wav", ".mp3", ".m4a", ".ogg"})


def ensure(count: int = 6) -> list[Path]:
    have = tracks()
    for i in range(len(have), count):
        p = make_track(DIR / f"horror_{i + 1:02d}.wav", seed=1000 + i)
        log(f"Nhạc nền kinh dị: {p.name}")
    return tracks()


if __name__ == "__main__":
    ensure(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
