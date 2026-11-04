"""Native social speech uses Studio's pinned VieNeu provider and admission checks."""

from dataclasses import replace
from pathlib import Path


def generate(text: str, wav: Path, cfg: dict):
    from ..core.voice_policy import assert_social_config, social_profile
    from ..providers.tts import get_provider
    from ..voices import VoiceRegistry

    assert_social_config({"engines": ["vieneu"], "vieneu": cfg})
    profile, root = social_profile({"engines": ["vieneu"], "vieneu": cfg})
    profile = replace(profile, params={**profile.params, "speed": float(cfg.get("speed", 1.0))})
    provider = get_provider("vieneu", VoiceRegistry(root, {profile.id: profile}, {}, {}))
    wav.parent.mkdir(parents=True, exist_ok=True)
    return provider.synthesize(text, profile, wav)
