"""TTS provider interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ...core.subtitles import Word

if TYPE_CHECKING:
    from ...voices import VoiceProfile, VoiceRegistry


@dataclass
class TTSResult:
    audio_path: Path
    words: list[Word] | None  # None -> caller aligns (faster-whisper) or estimates
    cost_usd: float = 0.0


class TTSProvider:
    name = "base"
    extension = ".wav"

    def __init__(self, registry: VoiceRegistry):
        self.registry = registry

    def check(self, profile: VoiceProfile) -> str | None:
        """Return None if usable now, else a human-readable reason."""
        return None

    def synthesize(self, text: str, profile: VoiceProfile, out_path: Path) -> TTSResult:
        raise NotImplementedError
