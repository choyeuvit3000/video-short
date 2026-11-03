from __future__ import annotations

from ...core.errors import ProviderUnavailable
from .base import TTSProvider, TTSResult
from .edge import EdgeTTS
from .mock import MockTTS
from .paid import ElevenLabsTTS, OpenAITTS
from .piper_tts import PiperTTS

PROVIDERS: dict[str, type[TTSProvider]] = {
    p.name: p for p in (EdgeTTS, PiperTTS, MockTTS, ElevenLabsTTS, OpenAITTS)
}


def get_provider(name: str, registry) -> TTSProvider:
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ProviderUnavailable(
            f"TTS provider '{name}' is not implemented on this machine yet (planned for the GPU node)",
            code="tts_unavailable",
        )
    return cls(registry)


__all__ = ["PROVIDERS", "TTSProvider", "TTSResult", "get_provider"]
