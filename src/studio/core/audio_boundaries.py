"""Protect consonant onsets without deleting any generated PCM samples."""

import wave
from pathlib import Path

import numpy as np

VERSION = "protected-pcm-v3"
LEAD_MS = 100
TAIL_MS = 125  # lead + previous tail = 225 ms minimum sentence boundary


def protect_pcm(src: Path, dst: Path, lead_ms=LEAD_MS, tail_ms=TAIL_MS):
    """Only add missing silence. Quiet consonants and model breaths are never cut."""
    with wave.open(str(src), "rb") as stream:
        params = stream.getparams()
        raw = stream.readframes(params.nframes)
    if params.sampwidth != 2:
        raise ValueError("Boundary protection requires PCM s16 WAV")
    samples = np.frombuffer(raw, dtype="<i2").reshape(-1, params.nchannels)
    active = np.flatnonzero(np.max(np.abs(samples.astype(np.int32)), axis=1) > 32768 * 10 ** (-50 / 20))
    if not len(active):
        raise ValueError("TTS returned silence; do not render it")
    lead = max(0, round(params.framerate * lead_ms / 1000) - int(active[0]))
    tail = max(0, round(params.framerate * tail_ms / 1000) - (len(samples) - 1 - int(active[-1])))
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as stream:
        stream.setparams(params)
        stream.writeframes(b"\0" * lead * 2 * params.nchannels + raw + b"\0" * tail * 2 * params.nchannels)
    return {
        "version": VERSION,
        "lead_added_ms": lead * 1000 / params.framerate,
        "tail_added_ms": tail * 1000 / params.framerate,
        "samples_removed": 0,
    }
