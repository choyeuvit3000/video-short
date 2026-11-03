"""Offline deterministic TTS for tests: a quiet tone per word, exact word timings. No network, no models."""

from __future__ import annotations

import math
import struct
import wave

from ...core.subtitles import estimate_words
from .base import TTSProvider, TTSResult

RATE = 24000


class MockTTS(TTSProvider):
    name = "mock"
    extension = ".wav"

    def synthesize(self, text, profile, out_path):
        cps = float(profile.params.get("chars_per_sec", 14))
        dur_ms = max(400, int(len(text) / cps * 1000))
        words = estimate_words(text, dur_ms)
        frames = bytearray()
        total = int(RATE * dur_ms / 1000)
        spans = [(int(w.start_ms * RATE / 1000), int((w.end_ms - 40) * RATE / 1000)) for w in words]
        si = 0
        for i in range(total):
            while si < len(spans) and i > spans[si][1]:
                si += 1
            on = si < len(spans) and spans[si][0] <= i <= spans[si][1]
            v = int(3000 * math.sin(2 * math.pi * 220 * i / RATE)) if on else 0
            frames += struct.pack("<h", v)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(RATE)
            wf.writeframes(bytes(frames))
        return TTSResult(out_path, words)
