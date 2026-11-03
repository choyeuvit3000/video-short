"""Local Piper TTS (ONNX, CPU). Models live in voices/local/models/<voice id>/."""

from __future__ import annotations

import wave

from ...core.errors import ProviderUnavailable
from .base import TTSProvider, TTSResult

_loaded: dict[str, object] = {}


class PiperTTS(TTSProvider):
    name = "piper"
    extension = ".wav"

    def _model_path(self, profile):
        return self.registry.model_dir(profile) / profile.params["model"]

    def check(self, profile):
        try:
            import piper  # noqa: F401
        except ImportError:
            return "piper-tts not installed (uv pip install -e \".[piper]\")"
        if not self._model_path(profile).is_file():
            return f"model not installed - run: studio voices install {profile.id}"
        return None

    def synthesize(self, text, profile, out_path):
        reason = self.check(profile)
        if reason:
            raise ProviderUnavailable(reason, code="tts_unavailable")
        from piper import PiperVoice, SynthesisConfig

        key = str(self._model_path(profile))
        voice = _loaded.get(key)
        if voice is None:
            voice = PiperVoice.load(key)
            _loaded[key] = voice
        cfg = SynthesisConfig(length_scale=float(profile.params.get("length_scale", 1.0)))
        with wave.open(str(out_path), "wb") as wf:
            voice.synthesize_wav(text, wf, syn_config=cfg)
        return TTSResult(out_path, None)
