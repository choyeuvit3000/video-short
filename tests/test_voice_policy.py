import hashlib
import json

import pytest

from studio.core.errors import ValidationError
from studio.core.voice_policy import assert_voice_allowed, blocked, signature
from studio.voices import VoiceProfile, VoiceRegistry


@pytest.mark.parametrize(
    "provider,name",
    [
        ("edge", "anything"),
        ("Edge-TTS", "Nam Minh"),
        ("", "edge-vi-HoaiMy"),
        ("vieneu", "Mai Anh"),
        ("vieneu", "MÁI-ANH"),
        ("vieneu", "Quang Sơn"),
        ("", "vieneu-gallery-quang-son"),
    ],
)
def test_blacklist_aliases(provider, name):
    assert blocked(provider, name)


def test_audition_never_bypasses_blacklist(tmp_path):
    with pytest.raises(ValidationError):
        assert_voice_allowed(
            VoiceProfile("x", "vi", "local", "vieneu", params={"voice": "Mai Anh"}), tmp_path, audition=True
        )
    with pytest.raises(ValidationError, match="blacklisted"):
        assert_voice_allowed(
            VoiceProfile("alternate-id", "vi", "local", "vieneu", params={"voice": "QUANG SƠN"}),
            tmp_path,
            audition=True,
        )


def test_review_is_bound_to_audio(tmp_path):
    p = VoiceProfile("new", "vi", "local", "vieneu", params={"voice": "Thái Sơn"})
    with pytest.raises(ValidationError):
        assert_voice_allowed(p, tmp_path)
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"sample")
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    data = {
        "status": "APPROVED",
        "voice_signature": signature(p),
        "reviewer": "creator",
        "test_audio_path": str(audio),
        "test_audio_sha256": hashlib.sha256(b"sample").hexdigest(),
        "checks": dict.fromkeys(
            ["intelligible", "natural", "pronunciation", "not_similar_to_maianh", "no_artifacts"], True
        ),
    }
    (reviews / "new.json").write_text(json.dumps(data))
    assert_voice_allowed(p, tmp_path)
    audio.write_bytes(b"changed")
    with pytest.raises(ValidationError):
        assert_voice_allowed(p, tmp_path)


def test_random_and_fallback_exclude_banned_and_unreviewed(tmp_path):
    banned = VoiceProfile("bad", "vi", "free", "edge")
    pending = VoiceProfile("pending", "vi", "local", "vieneu", fallback="bad")
    reg = VoiceRegistry(tmp_path, {"bad": banned, "pending": pending}, {"vi": "pending"}, {})
    assert reg.fallback_for(pending) is None
    with pytest.raises(ValidationError):
        reg.random_for("vi")
