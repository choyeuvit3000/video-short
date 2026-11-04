from types import SimpleNamespace

import pytest

from studio.core.errors import ProviderUnavailable
from studio.core.speech_checks import audit_numbers, critical_numbers, save_audit
from studio.core.subtitles import Word
from studio.providers.align import map_onto_text
from studio.voices import load_registry


def test_short_default_preserves_long_language_and_explicit_choices(settings):
    reg = load_registry(settings)
    assert reg.default_for("vi", "knowledge_explainer", "short_9x16").id == "vieneu-vi-short"
    assert reg.default_for("vi", "newspaper", "short_9x16").id == "vieneu-vi-short"
    assert reg.default_for("vi", "longform_explainer", "long_16x9").id == "omnivoice-vi-knowledge-under30"
    assert reg.default_for("en", "knowledge_explainer", "short_9x16").id == "piper-en-lessac"
    profile = reg.get("vieneu-vi-short")
    assert profile.params["speed"] == 1 and "target_space_tokens_per_second" not in profile.params
    assert profile.params["revision"] and profile.params["preset_sha256"]
    assert profile.status == "experimental"  # the agent must not admit the generated sample itself


def test_numeric_asr_is_not_pronunciation_proof():
    report = audit_numbers("Có năm phẩy hai người trung gian.", [Word("5,2", 0, 700)])
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["checks"][0]["evidence"] == "ASR_NUMERIC_AMBIGUOUS"
    assert report["raw_transcript"] == "5,2"


def test_symbolic_percentage_is_ambiguous_instead_of_a_false_missing_word():
    report = audit_numbers("năm phần trăm", [Word("5%", 0, 700)])
    assert report["checks"][0]["evidence"] == "ASR_NUMERIC_AMBIGUOUS"
    assert map_onto_text("năm phần trăm", [Word("5%", 0, 700)], 700, strict=True)


def test_omitted_decimal_cannot_be_hidden_by_high_overall_match():
    text = "Những chuỗi thành công có trung bình năm phẩy hai người trung gian."
    raw = [Word(t, i * 100, (i + 1) * 100) for i, t in enumerate(text.replace("phẩy ", "").split())]
    with pytest.raises(ProviderUnavailable, match="speech_number"):
        map_onto_text(text, raw, 2000, strict=True)
    assert audit_numbers(text, raw)["checks"][0]["evidence"] == "MISSING_MARKER"


def test_decimal_fraction_and_raw_marker_remain_reviewable():
    text = "Năm phẩy hai người. Điểm năm trên mười."
    raw = [Word(t, i * 100, (i + 1) * 100) for i, t in enumerate(text.split())]
    report = audit_numbers(text, raw)
    assert [c["marker"] for c in critical_numbers(text)] == ["phẩy", "trên"]
    assert all(c["evidence"] == "ASR_MARKER_PRESENT" for c in report["checks"])
    assert report["status"] == "REVIEW_REQUIRED"


def test_native_vieneu_uses_same_provider_and_one_speed_setting(tmp_path, monkeypatch):
    from studio.social_video.local_voice import generate

    p = SimpleNamespace(id="fixture", provider="vieneu", params={"voice": "Minh Triết", "speed": 1})
    # dataclass replacement is used by the bridge, use a real profile here.
    from studio.voices import VoiceProfile

    p = VoiceProfile(p.id, "vi", "local", p.provider, params=p.params)
    monkeypatch.setattr("studio.core.voice_policy.assert_social_config", lambda cfg: None)
    monkeypatch.setattr("studio.core.voice_policy.social_profile", lambda cfg: (p, tmp_path))
    calls = []
    provider = SimpleNamespace(synthesize=lambda text, profile, out: calls.append((text, profile.params["speed"])))
    monkeypatch.setattr("studio.providers.tts.get_provider", lambda *args: provider)
    generate("Một đoạn ý đầy đủ.", tmp_path / "take.wav", {"profile": "fixture", "speed": 1.1})
    assert calls == [("Một đoạn ý đầy đủ.", 1.1)]


def test_numeric_audit_is_bound_to_actual_audio(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"audio fixture")
    first = save_audit(tmp_path, "s1", audio, "năm phẩy hai", [Word("5,2", 0, 700)])
    audio.write_bytes(b"changed")
    second = save_audit(tmp_path, "s1", audio, "năm phẩy hai", [Word("5,2", 0, 700)])
    assert first["audio_sha256"] != second["audio_sha256"]
    assert (tmp_path / "work/speech_checks/s1.json").is_file()


def test_reddit_render_only_reads_prepared_speech(tmp_path, monkeypatch):
    from studio.core.errors import ManualGateRequired
    from studio.core.user_review import write
    from studio.social_video.reddit_edit import approved_audio

    with pytest.raises(ManualGateRequired):
        approved_audio(tmp_path, 1)
    wav = tmp_path / "approved.wav"
    wav.write_bytes(b"fixture")
    monkeypatch.setattr("studio.social_video.util.media_duration", lambda path: 1.0)
    write(tmp_path / "voice_manifest.json", {"body": [{"path": str(wav), "seconds": 1.0}], "hooks": [None]})
    body, hooks = approved_audio(tmp_path, 1)
    assert body == [(wav, 1.0)] and hooks == [None]
    wav.unlink()
    with pytest.raises(ManualGateRequired):
        approved_audio(tmp_path, 1)


def test_native_cache_cannot_return_an_older_approved_voice(tmp_path, monkeypatch):
    from studio.core import creative_brief as cb
    from studio.core.user_review import write

    accepted = {"fingerprint": "first accepted audio"}
    profile = SimpleNamespace(id="fixture", provider="mock", params={})
    monkeypatch.setattr(cb, "apply_social", lambda *a: {"approved_fingerprint": "script"})
    monkeypatch.setattr("studio.core.user_review.checkpoint", lambda *a: None)
    monkeypatch.setattr("studio.core.user_review.require", lambda *a: accepted)
    monkeypatch.setattr("studio.core.voice_policy.assert_social_config", lambda *a: None)
    monkeypatch.setattr("studio.core.voice_policy.social_profile", lambda *a: (profile, tmp_path))
    renders = []
    monkeypatch.setattr(cb, "reserve_render", lambda *a: renders.append(a))
    cfg = {"tts": {}}
    first, _ = cb.begin_social(tmp_path, cfg)
    out = tmp_path / "old.mp4"
    out.write_bytes(b"old audio")
    write(
        tmp_path / "native_render_cache.json", {"key": first, "outputs": [{"path": str(out), "sha256": cb._sha(out)}]}
    )
    accepted["fingerprint"] = "repaired accepted audio"
    second, cached = cb.begin_social(tmp_path, cfg)
    assert second != first and cached == [] and len(renders) == 2


def test_voice_checkpoint_requires_current_numeric_audit(tmp_path):
    from studio.core import creative_brief as cb
    from studio.core import user_review as r
    from studio.core.errors import ValidationError

    r.write(
        tmp_path / "project.json",
        {
            "project_id": "numeric_review",
            "workflow": "knowledge_explainer",
            "language": "vi",
            "audio": {"voice_profile": "mock-vi"},
            "scenes": [{"scene_id": "s1", "narration": "Có năm phẩy hai người trung gian."}],
        },
    )
    cb.prepare(tmp_path, {"goal": "Explain", "audience": "Vietnamese", "voice": "mock-vi"})
    r.prepare(tmp_path, "script")
    r.approve(tmp_path, "script", "User fixture: accepted script")
    p = r.read(tmp_path / "project.json")
    p["scenes"][0]["audio_path"] = "take.wav"
    r.write(tmp_path / "project.json", p)
    audio = tmp_path / "take.wav"
    audio.write_bytes(b"first audio")
    r.write(tmp_path / "work/timeline.json", {"scenes": []})
    with pytest.raises(ValidationError, match="review_number_check"):
        r.prepare(tmp_path, "voice")
    save_audit(tmp_path, "s1", audio, p["scenes"][0]["narration"], [Word("5,2", 0, 700)])
    assert r.prepare(tmp_path, "voice")["status"] == "WAITING_USER"
    audio.write_bytes(b"different audio")
    with pytest.raises(ValidationError, match="review_number_check"):
        r.prepare(tmp_path, "voice")
