"""Free Microsoft Edge online TTS (edge-tts). Returns real word timings."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from ...core.errors import ProviderUnavailable
from ...core.subtitles import Word
from .base import TTSProvider, TTSResult

_TICKS_PER_MS = 10_000  # edge-tts offsets are in 100 ns units


class EdgeTTS(TTSProvider):
    name = "edge"
    extension = ".mp3"
    # The free service randomly answers "No audio was received" (~1 in 3 calls at times, independent of the
    # text), so many quick retries beat a few long ones. A real outage still ends in ProviderUnavailable.
    retries = 7
    backoff_sec = (1, 2, 3, 4, 6, 8)

    async def _run(self, text: str, params: dict, out_path: Path) -> list[Word]:
        import edge_tts

        comm = edge_tts.Communicate(
            text,
            params["voice"],
            rate=params.get("rate", "+0%"),
            pitch=params.get("pitch", "+0Hz"),
            volume=params.get("volume", "+0%"),
            boundary="WordBoundary",
        )
        words: list[Word] = []
        with out_path.open("wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = int(chunk["offset"]) // _TICKS_PER_MS
                    dur = int(chunk["duration"]) // _TICKS_PER_MS
                    words.append(Word(chunk["text"], start, start + dur))
        return words

    def synthesize(self, text, profile, out_path):
        from ...core.voice_policy import assert_not_blocked
        assert_not_blocked("edge",profile.id,profile.params)
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                words = asyncio.run(self._run(text, profile.params, out_path))
                if out_path.stat().st_size == 0:
                    raise ProviderUnavailable("edge-tts returned no audio", code="tts_empty")
                return TTSResult(out_path, words or None)
            except ProviderUnavailable as e:
                last = e
            except Exception as e:  # network errors, rate limits, service changes
                last = e
            if attempt < self.retries:
                time.sleep(self.backoff_sec[min(attempt, len(self.backoff_sec)) - 1])
        out_path.unlink(missing_ok=True)
        raise ProviderUnavailable(f"edge-tts failed after {self.retries} attempts: {last}", code="tts_offline")
