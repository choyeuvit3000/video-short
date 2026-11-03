"""Voice registry: loads voices/{free,api,local}/*.yaml, picks a profile, installs local models."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .core.cache import file_sha256
from .core.config import Settings, load_yaml
from .core.errors import ValidationError
from .core.logging_utils import get_logger

log = get_logger()
TIER_DIRS = ("free", "api", "local")


@dataclass
class VoiceProfile:
    id: str
    lang: str
    tier: str
    provider: str
    status: str = "ready"
    location: str = "any"
    params: dict[str, Any] = field(default_factory=dict)
    cost_per_1k_chars: float = 0.0
    fallback: str | None = None
    files: list[dict[str, Any]] = field(default_factory=list)
    license: str | None = None
    source_file: str = ""

    @property
    def usable(self) -> bool:
        return self.status in ("ready", "experimental")

    def estimate_cost(self, text: str) -> float:
        return len(text) / 1000 * float(self.cost_per_1k_chars or 0)


@dataclass
class VoiceRegistry:
    root: Path
    profiles: dict[str, VoiceProfile]
    defaults: dict[str, str]
    offline_fallback: dict[str, str]

    def get(self, voice_id: str) -> VoiceProfile:
        if voice_id not in self.profiles:
            raise ValidationError(f"Unknown voice '{voice_id}'. See `studio voices list`.", code="unknown_voice")
        return self.profiles[voice_id]

    def default_for(self, lang: str) -> VoiceProfile:
        vid = self.defaults.get(lang)
        if not vid:
            raise ValidationError(f"No default voice for language '{lang}' in voices/registry.yaml",
                                  code="unknown_voice")
        return self.get(vid)

    def fallback_for(self, profile: VoiceProfile) -> VoiceProfile | None:
        fid = profile.fallback or self.offline_fallback.get(profile.lang)
        if fid and fid != profile.id and fid in self.profiles:
            return self.profiles[fid]
        return None

    def model_dir(self, profile: VoiceProfile) -> Path:
        return self.root / "local" / "models" / profile.id


def load_registry(settings: Settings) -> VoiceRegistry:
    root = settings.path("voices")
    reg = load_yaml(root / "registry.yaml")
    profiles: dict[str, VoiceProfile] = {}
    for tier in TIER_DIRS:
        d = root / tier
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.yaml")):
            for raw in load_yaml(f).get("profiles", []) or []:
                known = {k: raw[k] for k in VoiceProfile.__dataclass_fields__ if k in raw}
                prof = VoiceProfile(**known, source_file=str(f.relative_to(root)))
                if prof.id in profiles:
                    raise ValidationError(f"Duplicate voice id '{prof.id}' in {f}", code="config_error")
                profiles[prof.id] = prof
    return VoiceRegistry(root=root, profiles=profiles, defaults=dict(reg.get("defaults", {})),
                         offline_fallback=dict(reg.get("offline_fallback", {})))


def is_installed(reg: VoiceRegistry, profile: VoiceProfile) -> bool:
    if not profile.files:
        return True
    d = reg.model_dir(profile)
    return all((d / Path(f["url"]).name).is_file() for f in profile.files)


def install(reg: VoiceRegistry, profile: VoiceProfile, *, force: bool = False) -> Path:
    """Download a local model's files from the official URLs in its manifest entry."""
    if not profile.files:
        raise ValidationError(f"Voice '{profile.id}' has no downloadable files", code="not_installable")
    d = reg.model_dir(profile)
    d.mkdir(parents=True, exist_ok=True)
    sums = []
    for f in profile.files:
        url = f["url"]
        name = Path(url).name
        target = d / name
        if target.is_file() and not force:
            log.info("already present: %s", target)
        else:
            tmp = target.with_suffix(target.suffix + ".part")
            log.info("downloading %s", url)
            with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
                r.raise_for_status()
                with tmp.open("wb") as out:
                    for chunk in r.iter_bytes(1 << 20):
                        out.write(chunk)
            os.replace(tmp, target)
        digest = file_sha256(target)
        expected = f.get("sha256")
        if expected and expected != digest:
            target.unlink()
            raise ValidationError(f"sha256 mismatch for {name}", code="checksum_error")
        sums.append(f"{digest}  {name}")
    (d / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    return d
