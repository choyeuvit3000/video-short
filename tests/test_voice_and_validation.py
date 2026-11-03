import json

import pytest

from studio.core.cost import CostLedger
from studio.core.errors import BudgetExceeded, StudioError, ValidationError
from studio.core.validator import validate_project
from studio.pipeline.voice import run_voice

from .conftest import make_project, needs_ffmpeg


def _scenes(*texts, **extra):
    return [{"scene_id": f"s{i}", "narration": t, **extra} for i, t in enumerate(texts, 1)]


def test_validation_reports_missing_clip(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, timing_mode="fixed", scenes=[
        {"scene_id": "scene_01", "duration_sec": 4, "visual": {"type": "color", "color": "#ff0000"}},
        {"scene_id": "scene_02", "duration_sec": 4, "visual": {"type": "clip", "path": "clips/scene_02.mp4"}},
    ])
    issues = validate_project(ctx)
    errs = [i for i in issues if i.level == "error"]
    assert len(errs) == 1
    assert errs[0].code == "missing_clip" and errs[0].scene_id == "scene_02"
    assert "clips/scene_02.mp4" in errs[0].message


def test_validation_refuses_traversal(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, scenes=[
        {"scene_id": "s1", "visual": {"type": "still", "path": "../../secret.png"}}])
    assert any(i.code == "path_traversal" for i in validate_project(ctx))


@needs_ffmpeg
def test_voice_audio_driven_timeline(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, scenes=_scenes("Xin chào các bạn.", "Hôm nay trời đẹp quá."))
    tl = run_voice(ctx)
    assert [s["scene_id"] for s in tl["scenes"]] == ["s1", "s2"]
    frame = 1000 / 30
    for s in tl["scenes"]:
        assert s["duration_ms"] >= s["voice_ms"] + 200  # tail pad
        assert abs(s["duration_ms"] / frame - round(s["duration_ms"] / frame)) < 0.05  # frame aligned
        assert s["timing_source"] == "provider"
    assert tl["scenes"][1]["start_ms"] == tl["scenes"][0]["duration_ms"]
    assert (ctx.dir / "subtitles" / "s1.srt").exists()
    assert (ctx.dir / "audio" / "s1.wav").exists()
    words = json.loads((ctx.work / "words.json").read_text(encoding="utf-8"))
    assert words["words"][0]["text"] == "Xin"


@needs_ffmpeg
def test_voice_does_not_overwrite_and_uses_cache(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, scenes=_scenes("Một câu ngắn thôi."))
    run_voice(ctx)
    audio = ctx.dir / "audio" / "s1.wav"
    mtime = audio.stat().st_mtime_ns
    run_voice(ctx)
    assert audio.stat().st_mtime_ns == mtime  # unchanged text -> file kept


@needs_ffmpeg
def test_voice_too_long_fails_in_fixed_mode(tmp_path, settings):
    long_text = "Đây là một câu rất dài " * 10
    ctx = make_project(tmp_path / "p", settings, timing_mode="fixed",
                       scenes=[{"scene_id": "s1", "duration_sec": 2, "narration": long_text,
                                "visual": {"type": "color"}}])
    with pytest.raises(ValidationError) as e:
        run_voice(ctx)
    assert e.value.code == "voice_too_long" and "s1" in str(e.value)


@needs_ffmpeg
def test_manual_audio_needs_no_network(tmp_path, settings, monkeypatch):
    import httpx

    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(httpx, "post", boom)
    from studio.providers.tts.mock import MockTTS
    from studio.voices import load_registry

    reg = load_registry(settings)
    ctx = make_project(tmp_path / "p", settings, audio={"source": "manual", "voice_profile": None},
                       scenes=[{"scene_id": "s1", "narration": "Giọng tự thu.", "audio_path": "audio/my_take.wav"}])
    MockTTS(reg).synthesize("Giọng tự thu.", reg.get("mock-vi"), ctx.dir / "audio" / "my_take.wav")
    tl = run_voice(ctx)
    assert tl["voice_profile"] == "manual"
    assert tl["scenes"][0]["audio"] == "audio/my_take.wav"
    assert tl["scenes"][0]["timing_source"] == "estimate"


def test_disabled_paid_voice_refused(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, audio={"voice_profile": "elevenlabs-multilingual"},
                       scenes=_scenes("x"))
    with pytest.raises(ValidationError) as e:
        run_voice(ctx)
    assert e.value.code == "voice_disabled"


def test_budget_ledger(tmp_path):
    led = CostLedger(tmp_path, 0.05)
    led.ensure(0.0, "free")  # free never blocks
    led.ensure(0.04, "ok")
    led.record(stage="voice", provider="x", usd=0.04)
    with pytest.raises(BudgetExceeded) as e:
        led.ensure(0.02, "too much")
    assert e.value.exit_code == 4
    assert json.loads((tmp_path / "cost.json").read_text(encoding="utf-8"))["total_usd"] == 0.04
    assert CostLedger(tmp_path, 0).total == 0.04


def test_unknown_voice(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, audio={"voice_profile": "nope"}, scenes=_scenes("x"))
    with pytest.raises(StudioError):
        run_voice(ctx)
