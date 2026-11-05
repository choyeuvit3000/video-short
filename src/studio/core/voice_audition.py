"""Cacheable local auditions isolated from production admission."""

import hashlib
import json

from ..providers.tts import get_provider
from .audio_boundaries import VERSION
from .errors import ValidationError
from .voice_policy import assert_voice_allowed, signature

DEFAULT_TEXT = (
    "Chào buổi sáng, hôm nay mình cùng xem nhanh một bài trên Threads. "
    "Giữ đúng ý người đăng, đọc rõ từng câu và nghỉ một chút ở dấu chấm. "
    "Chiếc ví thì muốn nghỉ ngơi, còn công nghệ lại ra mắt mỗi ngày. "
    "Một trăm hai mươi nghìn đồng, ngày ba mươi mốt tháng mười."
)


def audition_sample(registry, profile, text=DEFAULT_TEXT):
    assert_voice_allowed(profile, registry.root, audition=True)
    provider = get_provider(profile.provider, registry)
    if not hasattr(provider, "audition"):
        raise ValidationError("Quarantined auditions support local VieNeu and OmniVoice", code="voice_audition")
    folder = registry.root / "candidates" / profile.id
    folder.mkdir(parents=True, exist_ok=True)
    sample = folder / "audition.wav"
    meta = folder / "audition.json"
    old = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
    if not (
        sample.is_file()
        and old.get("voice_signature") == signature(profile)
        and old.get("text") == text
        and old.get("synthesis_params") == profile.params
        and old.get("processing_version") == VERSION
        and old.get("sha256") == hashlib.sha256(sample.read_bytes()).hexdigest()
    ):
        provider.audition(text, profile, sample)
    meta.write_text(
        json.dumps(
            {
                "status": "QUARANTINED",
                "provider": profile.provider,
                "voice_signature": signature(profile),
                "text": text,
                "synthesis_params": profile.params,
                "processing_version": VERSION,
                "sha256": hashlib.sha256(sample.read_bytes()).hexdigest(),
                "preference": (
                    "user-provided knowledge reference cadence"
                    if profile.params.get("target_space_tokens_per_second")
                    else f"selected profile: {profile.id}"
                ),
                "training": "not started",
                "human_listening": "required",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return sample
