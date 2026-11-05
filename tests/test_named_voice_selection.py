import pytest

from studio.core import user_review as review
from studio.core import voice_policy as policy
from studio.core.errors import ManualGateRequired, ValidationError
from studio.core.speech_checks import file_sha
from studio.voices import VoiceProfile


def selected_voice(tmp_path, monkeypatch, *, voice="Ngọc Huyền"):
    profile = VoiceProfile(id="named", lang="vi", tier="local", provider="vieneu", params={"voice": voice})
    monkeypatch.setattr(policy, "social_profile", lambda cfg: (profile, tmp_path))
    audio = tmp_path / "actual.wav"
    audio.write_bytes(b"cached actual speech")
    review.write(
        tmp_path / "continuous_voice.json",
        {
            "voice_signature": policy.signature(profile),
            "files": [{"path": str(audio), "sha256": file_sha(audio)}],
        },
    )
    review.write(
        tmp_path / "named_voice_authorization.json",
        {
            "reviewer": "user",
            "message": "Dùng giọng Ngọc Huyền đi",
            "project_id": tmp_path.name,
            "profile": profile.id,
            "voice_signature": policy.signature(profile),
            "scope": "render_review_from_existing_speech",
        },
    )
    return profile, audio, {"tts": {"engines": ["vieneu"]}}


def test_explicit_named_choice_is_project_scoped_and_not_global_admission(tmp_path, monkeypatch):
    profile, audio, cfg = selected_voice(tmp_path, monkeypatch)
    policy.assert_project_voice(tmp_path, cfg)
    with pytest.raises(ValidationError):
        policy.assert_voice_allowed(profile, tmp_path)
    audio.write_bytes(b"tampered")
    with pytest.raises(ValidationError):
        policy.assert_project_voice(tmp_path, cfg)


def test_named_selection_cannot_bypass_maianh_or_edge_blacklist(tmp_path, monkeypatch):
    _, _, cfg = selected_voice(tmp_path, monkeypatch, voice="Mai Anh")
    with pytest.raises(ValidationError, match="blacklisted"):
        policy.assert_project_voice(tmp_path, cfg)
    _, _, cfg = selected_voice(tmp_path, monkeypatch)
    cfg["tts"]["engines"] = ["edge"]
    with pytest.raises(ValidationError, match="blacklisted"):
        policy.assert_project_voice(tmp_path, cfg)


def test_replacing_voice_before_final_keeps_history_and_three_checkpoint_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "require", lambda *a: None)
    monkeypatch.setattr(review, "payload", lambda *a: {"voice": "new"})
    key = review.digest({"voice": "new"})
    review.write(tmp_path / "review_voice.json", {"fingerprint": key})
    review.write(
        tmp_path / "user_reviews.json",
        {
            "max_approvals": 3,
            "approvals": [
                {"stage": "script", "approval_number": 1, "message": "duyệt kịch bản"},
                {"stage": "voice", "approval_number": 2, "message": "duyệt giọng này", "fingerprint": "old"},
            ],
        },
    )
    item = review.revise_voice_choice(tmp_path, "Dùng giọng Ngọc Huyền đi")
    ledger = review.read(tmp_path / "user_reviews.json")
    assert len(ledger["approvals"]) == 2 and ledger["max_approvals"] == 3
    assert item["approval_number"] == 2 and item["revisions"][0]["fingerprint"] == "old"
    assert item["all_parts_listened_by_user"] is False
    repeated = review.revise_voice_choice(tmp_path, "Dùng giọng Ngọc Huyền đi")
    assert len(repeated["revisions"]) == 1
    ledger["approvals"].append({"stage": "final", "approval_number": 3})
    review.write(tmp_path / "user_reviews.json", ledger)
    with pytest.raises(ManualGateRequired):
        review.revise_voice_choice(tmp_path, "Đổi lần nữa")


def test_cli_exposes_voice_revision_without_authorizing_another_stage(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from studio.cli import app

    calls = []
    monkeypatch.setattr(review, "revise_voice_choice", lambda path, message: calls.append((path, message)) or {})
    args = [
        "review",
        str(tmp_path),
        "--stage",
        "voice",
        "--action",
        "revise-voice",
        "--message",
        "Dùng giọng Ngọc Huyền đi",
    ]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0 and calls == [(tmp_path, "Dùng giọng Ngọc Huyền đi")]
    args[args.index("voice")] = "script"
    result = CliRunner().invoke(app, args)
    assert result.exit_code != 0 and len(calls) == 1
