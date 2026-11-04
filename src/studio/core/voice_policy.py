"""Non-overridable voice blacklist and fail-closed quality admission."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

from .errors import ValidationError


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value)).replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in value.lower() if not unicodedata.combining(c)))


def blocked(provider, voice_id="", params=None):
    provider = normalize(provider)
    if provider.startswith(("edge", "microsoftedge")):
        return True
    if normalize(voice_id).startswith(("edge", "microsoftedge")):
        return True
    names = [voice_id, (params or {}).get("voice", ""), (params or {}).get("speaker", "")]
    return any("maianh" in normalize(name) for name in names)


def assert_not_blocked(provider, voice_id="", params=None):
    if blocked(provider, voice_id, params):
        raise ValidationError(
            "Edge and Mai Anh are permanently blacklisted, including aliases, random and fallback",
            code="voice_blacklisted",
        )


def signature(profile):
    params = {k: v for k, v in profile.params.items() if k not in ("speed", "rate", "pitch")}
    return hashlib.sha256(json.dumps([profile.id, profile.provider, params], sort_keys=True).encode()).hexdigest()


def assert_voice_allowed(profile, root=None, *, audition=False):
    assert_not_blocked(profile.provider, profile.id, profile.params)
    if profile.provider == "mock":
        return
    if profile.provider == "omnivoice":
        from .paths import find_repo_root

        ref = Path(profile.params.get("ref_audio", "__missing__"))
        if not ref.is_absolute():
            ref = (Path(root) if root else find_repo_root() / "voices") / ref
        assert_not_blocked("", ref.stem)
        if not ref.is_file() or hashlib.sha256(ref.read_bytes()).hexdigest() != profile.params.get("ref_sha256"):
            raise ValidationError(
                "OmniVoice reference missing or changed; audition and review again", code="voice_reference"
            )
    if audition:
        return  # audition files are quarantined and cannot be selected for production
    if root is None:
        from .paths import find_repo_root

        root = find_repo_root() / "voices"
    review = Path(root) / "reviews" / (profile.id + ".json")
    data = json.loads(review.read_text(encoding="utf-8")) if review.is_file() else {}
    checks = data.get("checks", {})
    audio = Path(data.get("test_audio_path", "__missing__"))
    audio_ok = False
    if audio.is_file():
        with audio.open("rb") as stream:
            audio_ok = hashlib.file_digest(stream, "sha256").hexdigest() == data.get("test_audio_sha256")
    required = ("intelligible", "natural", "pronunciation", "not_similar_to_maianh", "no_artifacts")
    if (
        data.get("status") != "APPROVED"
        or data.get("voice_signature") != signature(profile)
        or not data.get("reviewer")
        or not audio_ok
        or not all(checks.get(k) is True for k in required)
    ):
        raise ValidationError(
            f"Voice {profile.id} is quarantined pending quality and Mai Anh similarity review",
            code="voice_quality_pending",
        )


def social_profile(cfg):
    from ..voices import load_registry
    from .config import get_settings

    engines = cfg.get("engines", [])
    if len(engines) != 1 or engines[0] not in {"vieneu", "omnivoice"}:
        raise ValidationError("Select exactly one reviewed local voice engine", code="voice_quality_pending")
    engine = engines[0]
    options = cfg.get(engine, {})
    reg = load_registry(get_settings())
    if options.get("profile"):
        profile = reg.get(options["profile"])
        if profile.provider != engine:
            raise ValidationError("Voice profile and engine differ", code="voice_config")
        return profile, reg.root
    voice = options.get("voice", "")
    for profile in reg.profiles.values():
        if profile.provider == engine and normalize(profile.params.get("voice")) == normalize(voice):
            return profile, reg.root
    raise ValidationError("Configured local voice is absent from the voice registry", code="unknown_voice")


def assert_social_config(cfg):
    engines = cfg.get("engines", [])
    if not engines or any(blocked(e) for e in engines):
        raise ValidationError(
            "Remove blacklisted Edge from every primary/fallback engine list", code="voice_blacklisted"
        )
    profile, root = social_profile(cfg)
    assert_voice_allowed(profile, root)
