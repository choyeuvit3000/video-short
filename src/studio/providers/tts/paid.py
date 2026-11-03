"""Paid TTS APIs (disabled by default in voices/api/paid.yaml). Budget is checked by the caller."""

from __future__ import annotations

import base64
import os

import httpx

from ...core.errors import ProviderUnavailable
from ...core.subtitles import Word
from .base import TTSProvider, TTSResult


def _key(profile) -> str:
    env = profile.params.get("key_env", "")
    key = os.environ.get(env, "")
    if not key:
        raise ProviderUnavailable(f"{env} is not set in .env", code="tts_no_key")
    return key


class ElevenLabsTTS(TTSProvider):
    name = "elevenlabs"
    extension = ".mp3"

    def check(self, profile):
        return None if os.environ.get(profile.params.get("key_env", "")) else "API key missing in .env"

    def synthesize(self, text, profile, out_path):
        key = _key(profile)
        p = profile.params
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{p['voice_id']}/with-timestamps"
        try:
            r = httpx.post(url, headers={"xi-api-key": key},
                           json={"text": text, "model_id": p.get("model_id", "eleven_multilingual_v2")},
                           params={"output_format": "mp3_44100_128"}, timeout=120)
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"ElevenLabs request failed: {e}", code="tts_offline") from e
        if r.status_code != 200:
            raise ProviderUnavailable(f"ElevenLabs HTTP {r.status_code}: {r.text[:300]}", code="tts_api_error")
        data = r.json()
        out_path.write_bytes(base64.b64decode(data["audio_base64"]))
        return TTSResult(out_path, _chars_to_words(data.get("alignment")), profile.estimate_cost(text))


def _chars_to_words(al: dict | None) -> list[Word] | None:
    if not al:
        return None
    words, cur, start, end = [], "", None, 0.0
    for ch, s, e in zip(al["characters"], al["character_start_times_seconds"],
                        al["character_end_times_seconds"], strict=False):
        if ch.isspace():
            if cur:
                words.append(Word(cur, int(start * 1000), int(end * 1000)))
            cur, start = "", None
            continue
        if start is None:
            start = s
        cur += ch
        end = e
    if cur:
        words.append(Word(cur, int(start * 1000), int(end * 1000)))
    return words


class OpenAITTS(TTSProvider):
    name = "openai"
    extension = ".mp3"

    def check(self, profile):
        return None if os.environ.get(profile.params.get("key_env", "")) else "API key missing in .env"

    def synthesize(self, text, profile, out_path):
        key = _key(profile)
        p = profile.params
        try:
            r = httpx.post("https://api.openai.com/v1/audio/speech",
                           headers={"Authorization": f"Bearer {key}"},
                           json={"model": p.get("model", "gpt-4o-mini-tts"), "voice": p.get("voice", "alloy"),
                                 "input": text, "response_format": "mp3"}, timeout=120)
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"OpenAI TTS request failed: {e}", code="tts_offline") from e
        if r.status_code != 200:
            raise ProviderUnavailable(f"OpenAI TTS HTTP {r.status_code}: {r.text[:300]}", code="tts_api_error")
        out_path.write_bytes(r.content)
        return TTSResult(out_path, None, profile.estimate_cost(text))
