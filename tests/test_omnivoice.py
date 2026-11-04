"""Protocol and admission checks without GPU, downloads or real synthesis."""

import hashlib
import json
import sys
from dataclasses import replace

import pytest

from studio.core.errors import ValidationError
from studio.core.voice_policy import assert_voice_allowed
from studio.providers.tts import get_provider, omnivoice
from studio.voices import VoiceProfile, VoiceRegistry

FAKE = r"""
import json,sys,wave
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
assert "--revision" in sys.argv
print(json.dumps({"ok":True,"cuda":False}),flush=True)
for line in sys.stdin:
    req=json.loads(line)
    assert req["language"]=="vi" and req["ref_text"]=="Xin chào."
    with wave.open(req["out"],"wb") as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000)
        w.writeframes(b"\x00\x10"*24000)
    print(json.dumps({"ok":True}),flush=True)
"""


@pytest.fixture
def omni_profile(tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"reference")
    profile = VoiceProfile(
        "omni-test",
        "vi",
        "local",
        "omnivoice",
        params={
            "ref_audio": str(ref),
            "ref_sha256": hashlib.sha256(b"reference").hexdigest(),
            "ref_text": "Xin chào.",
            "model": "test-model",
            "revision": "test-revision",
        },
    )
    reg = VoiceRegistry(tmp_path, {profile.id: profile}, {"vi": profile.id}, {})
    return reg, profile


def test_omni_protocol_and_quarantine(omni_profile, tmp_path, monkeypatch):
    reg, p = omni_profile
    runner = tmp_path / "fake.py"
    runner.write_text(FAKE, encoding="utf-8")
    monkeypatch.setattr(omnivoice, "RUNNER", runner)
    monkeypatch.setenv("STUDIO_OMNIVOICE_PYTHON", sys.executable)
    provider = get_provider("omnivoice", reg)
    with pytest.raises(ValidationError):
        provider.synthesize("Xin chào.", p, tmp_path / "not-approved.wav")
    assert not (tmp_path / "not-approved.wav").exists()
    try:
        result = provider.audition("Xin chào.", p, tmp_path / "audition.wav")
        assert result.audio_path.is_file() and result.words is None
        assert len(omnivoice._workers) == 1
    finally:
        omnivoice._close_all()
        omnivoice._workers.clear()


def test_changed_reference_blocks_even_audition(omni_profile):
    reg, p = omni_profile
    from pathlib import Path

    Path(p.params["ref_audio"]).write_bytes(b"changed")
    with pytest.raises(ValidationError, match="reference"):
        assert_voice_allowed(p, reg.root, audition=True)


def test_banned_clone_reference_identity(omni_profile):
    reg, p = omni_profile
    p = replace(p, params={**p.params, "speaker": "Mai Anh"})
    with pytest.raises(ValidationError, match="blacklisted"):
        assert_voice_allowed(p, reg.root, audition=True)


def test_social_selects_omni_not_stale_vieneu(omni_profile, monkeypatch):
    reg, p = omni_profile
    monkeypatch.setattr("studio.voices.load_registry", lambda settings: reg)
    from studio.core.voice_policy import social_profile

    chosen, _ = social_profile(
        {"engines": ["omnivoice"], "omnivoice": {"profile": p.id}, "vieneu": {"voice": "Mai Anh"}}
    )
    assert chosen.id == p.id
    with pytest.raises(ValidationError):
        social_profile({"engines": ["omnivoice", "edge"]})


def test_audition_reuses_unchanged_audio(omni_profile, monkeypatch):
    reg, p = omni_profile
    from studio.core import voice_audition

    calls = []

    class FakeProvider:
        def audition(self, text, profile, out):
            calls.append(text)
            out.write_bytes(text.encode())

    monkeypatch.setattr(voice_audition, "get_provider", lambda *a: FakeProvider())
    a = voice_audition.audition_sample(reg, p, "first")
    voice_audition.audition_sample(reg, p, "first")
    assert calls == ["first"]
    assert json.loads(a.with_suffix(".json").read_text())["status"] == "QUARANTINED"
    voice_audition.audition_sample(reg, p, "changed")
    assert calls == ["first", "changed"]


def test_native_route_uses_omni_and_audio_cache(omni_profile, tmp_path, monkeypatch):
    import math
    import struct
    import wave
    from types import SimpleNamespace

    from studio.core.voice_policy import signature
    from studio.social_video import tts
    from tests.conftest import HAS_FFMPEG

    if not HAS_FFMPEG:
        pytest.skip("ffmpeg required")
    reg, p = omni_profile
    sample = tmp_path / "listened.wav"
    sample.write_bytes(b"fixture")
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    (reviews / (p.id + ".json")).write_text(
        json.dumps(
            {
                "status": "APPROVED",
                "reviewer": "test fixture",
                "voice_signature": signature(p),
                "test_audio_path": str(sample),
                "test_audio_sha256": hashlib.sha256(b"fixture").hexdigest(),
                "checks": dict.fromkeys(
                    ["intelligible", "natural", "pronunciation", "not_similar_to_maianh", "no_artifacts"], True
                ),
            }
        )
    )
    monkeypatch.setattr("studio.voices.load_registry", lambda settings: reg)
    monkeypatch.setattr(tts, "TTS_CACHE", tmp_path / "tts-cache")
    calls = []

    class Provider:
        def synthesize(self, text, profile, out):
            assert profile.provider == "omnivoice" and profile.params["speed"] == 1.1
            calls.append(text)
            with wave.open(str(out), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(24000)))
            return SimpleNamespace(audio_path=out)

    monkeypatch.setattr("studio.providers.tts.get_provider", lambda *a: Provider())
    cfg = {"engines": ["omnivoice"], "omnivoice": {"profile": p.id, "speed": 1.1}}
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    assert tts.synth("Xin chào.", first, cfg)
    assert tts.synth("Xin chào.", second, cfg)
    assert calls == ["Xin chào."] and first.read_bytes() == second.read_bytes()


def test_default_engine_and_explicit_engine_are_respected(tmp_path, monkeypatch, settings):
    from studio.social_video import util
    from studio.voices import load_registry

    assert load_registry(settings).default_for("vi").id == "omnivoice-vi-thaison"
    monkeypatch.setattr(util, "ROOT", tmp_path)
    assert util.load_config()["tts"]["engines"] == ["omnivoice"]
    (tmp_path / "config.json").write_text(json.dumps({"tts": {"engines": ["vieneu"]}}))
    assert util.load_config()["tts"]["engines"] == ["vieneu"]


def test_reference_cadence_and_project_multiplier():
    from studio.providers.tts.omnivoice import target_duration

    text = " ".join(["một"] * 54)
    assert target_duration(text, {"target_space_tokens_per_second": 5.4}) == pytest.approx(10)
    assert target_duration(text, {"target_space_tokens_per_second": 5.4, "speed": 1.2}) == pytest.approx(10 / 1.2)
    assert target_duration(text, {}) is None
    for rate in (0, -1, float("nan"), float("inf"), 20):
        with pytest.raises(ValidationError):
            target_duration(text, {"target_space_tokens_per_second": rate})


def test_workflow_default_preserves_language_and_other_modes(settings):
    from studio.voices import load_registry

    reg = load_registry(settings)
    assert reg.default_for("vi", "knowledge_explainer").id == "omnivoice-vi-knowledge-under30"
    assert reg.default_for("vi", "longform_explainer").id == "omnivoice-vi-knowledge-under30"
    assert reg.default_for("vi", "story_reader").id == "omnivoice-vi-thaison"
    assert reg.default_for("en", "knowledge_explainer").id == "piper-en-lessac"


@pytest.mark.parametrize(
    ("lang", "voice", "expected"),
    [("vi", None, "omnivoice-vi-knowledge-under30"), ("en", None, "piper-en-lessac"), ("vi", "mock-vi", "mock-vi")],
)
def test_new_knowledge_project_selects_voice_without_double_speed(tmp_path, lang, voice, expected):
    from typer.testing import CliRunner

    from studio.cli import app

    args = ["new", "knowledge_explainer", "voice default", "--dir", str(tmp_path / "project"), "--lang", lang]
    if voice:
        args.extend(["--voice", voice])
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "project/project.json").read_text(encoding="utf-8"))
    assert data["audio"]["voice_profile"] == expected
    assert data["audio"]["speed"] == 1.0
