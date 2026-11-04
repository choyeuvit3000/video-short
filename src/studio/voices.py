"""Voice registry: loads voices/{free,api,local}/*.yaml, picks a profile, installs local models."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx

from .core.cache import file_sha256
from .core.config import Settings, deep_merge, load_yaml
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
    estimated_space_tokens_per_second: float | None = None

    @property
    def usable(self) -> bool:
        from .core.voice_policy import blocked

        return self.status in ("ready", "experimental") and not blocked(self.provider, self.id, self.params)

    def estimate_cost(self, text: str) -> float:
        return len(text) / 1000 * float(self.cost_per_1k_chars or 0)


def with_speed(prof: VoiceProfile, speed: float) -> VoiceProfile:
    """The profile with its pace multiplied by `speed`, in each provider's own parameter."""
    if abs(speed - 1.0) < 1e-6:
        return prof
    params = dict(prof.params)
    if prof.provider == "edge":
        base = float(str(params.get("rate", "+0%")).rstrip("%") or 0)
        params["rate"] = f"{round(((1 + base / 100) * speed - 1) * 100):+d}%"
    elif prof.provider == "piper":
        params["length_scale"] = round(float(params.get("length_scale", 1.0)) / speed, 4)
    elif prof.provider == "mock":
        params["chars_per_sec"] = float(params.get("chars_per_sec", 14)) * speed
    else:
        params["speed"] = round(float(params.get("speed", 1.0)) * speed, 4)
    return replace(prof, params=params)


@dataclass
class VoiceRegistry:
    root: Path
    profiles: dict[str, VoiceProfile]
    defaults: dict[str, str]
    offline_fallback: dict[str, str]
    workflow_defaults: dict[str, dict[str, str]] = field(default_factory=dict)
    format_defaults: dict[str, dict[str, str]] = field(default_factory=dict)

    def get(self, voice_id: str) -> VoiceProfile:
        if voice_id not in self.profiles:
            raise ValidationError(f"Unknown voice '{voice_id}'. See `studio voices list`.", code="unknown_voice")
        from .core.voice_policy import assert_not_blocked

        p = self.profiles[voice_id]
        assert_not_blocked(p.provider, p.id, p.params)
        return p

    def default_for(self, lang: str, workflow: str | None = None, format_name: str | None = None) -> VoiceProfile:
        vid = (
            self.format_defaults.get(format_name, {}).get(lang)
            or self.workflow_defaults.get(workflow, {}).get(lang)
            or self.defaults.get(lang)
        )
        if not vid:
            raise ValidationError(
                f"No default voice for language '{lang}' in voices/registry.yaml", code="unknown_voice"
            )
        return self.get(vid)

    def fallback_for(self, profile: VoiceProfile) -> VoiceProfile | None:
        fid = profile.fallback or self.offline_fallback.get(profile.lang)
        if fid and fid != profile.id and fid in self.profiles:
            candidate = self.profiles[fid]
            if not candidate.usable:
                return None
            from .core.voice_policy import assert_voice_allowed

            try:
                assert_voice_allowed(candidate, self.root)
            except ValidationError:
                return None
            return candidate
        return None

    def random_for(self, lang: str, rng=None) -> VoiceProfile:
        import random

        from .core.voice_policy import assert_voice_allowed

        pool = []
        for p in self.profiles.values():
            if p.lang != lang or not p.usable or p.provider == "mock":
                continue
            try:
                assert_voice_allowed(p, self.root)
            except ValidationError:
                continue
            pool.append(p)
        if not pool:
            raise ValidationError("No reviewed non-blacklisted voices available", code="voice_quality_pending")
        return (rng or random).choice(pool)

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
    # config/local.yaml `voice_defaults: {vi: vieneu-vi-thaison}` - this machine's default voice per language
    defaults = {**dict(reg.get("defaults", {})), **dict(settings.get("voice_defaults", {}) or {})}
    return VoiceRegistry(
        root=root,
        profiles=profiles,
        defaults=defaults,
        offline_fallback=dict(reg.get("offline_fallback", {})),
        workflow_defaults=deep_merge(
            reg.get("workflow_defaults", {}), settings.get("voice_workflow_defaults", {}) or {}
        ),
        format_defaults=deep_merge(reg.get("format_defaults", {}), settings.get("voice_format_defaults", {}) or {}),
    )


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
