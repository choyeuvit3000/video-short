"""Integration: real FFmpeg renders at low resolution (test_9x16 / test_16x9) + QC."""

import json

import pytest

from studio.core.errors import StudioError, ValidationError
from studio.core.media_probe import probe
from studio.pipeline.runner import RunOptions, run_pipeline

from .conftest import color_clip, color_image, make_project, needs_ffmpeg, three_scene_fixed

pytestmark = [needs_ffmpeg, pytest.mark.ffmpeg]


def _qc(ctx):
    return json.loads((ctx.output / "qc_report.json").read_text(encoding="utf-8"))


def test_three_clip_fixed_render_in_unicode_path(tmp_path, settings):
    pdir = tmp_path / "thử nghiệm 01"  # spaces + Vietnamese
    ctx = three_scene_fixed(pdir, settings)
    inputs = {p: p.stat().st_mtime_ns for p in (pdir / "clips").glob("*.mp4")}
    run_pipeline(ctx, RunOptions(only=["validate", "voice", "render", "qc", "package"]))
    rep = _qc(ctx)
    assert rep["status"] == "PASS", rep
    assert abs(rep["actual_duration_sec"] - 24.0) <= 0.3
    info = probe(pdir / "output" / "final.mp4")
    assert (info.width, info.height, info.fps) == (360, 640, 30)
    assert info.vcodec == "h264" and info.acodec == "aac" and info.sample_rate == 48000 and info.channels == 2
    assert (pdir / "output" / "captions.srt").exists()
    assert "AI" in (pdir / "output" / "metadata.md").read_text(encoding="utf-8")
    assert not (pdir / "output" / "final.tmp.mp4").exists()
    # inputs never modified
    assert inputs == {p: p.stat().st_mtime_ns for p in (pdir / "clips").glob("*.mp4")}
    st = json.loads((pdir / "state.json").read_text(encoding="utf-8"))["stages"]
    assert all(st[s]["status"] == "done" for s in ("validate", "voice", "render", "qc", "package"))


def test_short_clip_frozen_and_still_ken_burns(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, timing_mode="fixed", workflow="ai_cinematic",
                       video={"background": "gradient", "subtitle_mode": "none"})
    color_clip(ctx.dir / "clips" / "a.mp4", "orange", 1.0, size="640x360")  # wrong aspect + too short
    color_image(ctx.dir / "images" / "b.png", (20, 80, 160))
    ctx.project.scenes = [
        {"scene_id": "a", "duration_sec": 2, "visual": {"type": "clip", "path": "clips/a.mp4"}},
        {"scene_id": "b", "duration_sec": 2, "visual": {"type": "still", "path": "images/b.png",
                                                       "ken_burns": "pan_left"}},
        {"scene_id": "c", "duration_sec": 1.5, "visual": {"type": "background"}},
    ]
    ctx.save()
    ctx.project = type(ctx.project).model_validate(json.loads((ctx.dir / "project.json").read_text("utf-8")))
    run_pipeline(ctx, RunOptions(only=["voice", "render", "qc"]))
    rep = _qc(ctx)
    assert rep["status"] == "PASS", rep
    assert abs(rep["actual_duration_sec"] - 5.5) <= 0.3


def test_landscape_with_music_ducking(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, video={"format": "test_16x9", "background": "color:#203040",
                                                        "caption_style": "clean_box"},
                       scenes=[{"scene_id": "s1", "narration": "Video ngang mười sáu chín."},
                               {"scene_id": "s2", "narration": "Có nhạc nền giảm âm khi đọc."}])
    color_clip(ctx.dir / "music" / "bgm.mp4", "black", 3.0, size="64x64")
    ctx.project.audio.background_music = "music/bgm.mp4"
    ctx.save()
    run_pipeline(ctx, RunOptions(only=["validate", "voice", "render", "qc"]))
    rep = _qc(ctx)
    assert rep["status"] == "PASS", rep
    assert (rep["video"]["width"], rep["video"]["height"]) == (640, 360)


def test_stale_timeline_detected(tmp_path, settings):
    ctx = three_scene_fixed(tmp_path / "p", settings)
    run_pipeline(ctx, RunOptions(only=["voice"]))
    ctx.project.scenes = ctx.project.scenes[:2]
    with pytest.raises(ValidationError) as e:
        run_pipeline(ctx, RunOptions(only=["render"]))
    assert e.value.code == "stale_timeline"


def test_broken_clip_reports_scene(tmp_path, settings):
    ctx = three_scene_fixed(tmp_path / "p", settings)
    (ctx.dir / "clips" / "scene_02.mp4").write_bytes(b"not a video")
    run_pipeline(ctx, RunOptions(only=["voice"]))
    with pytest.raises(StudioError) as e:
        run_pipeline(ctx, RunOptions(only=["render"]))
    assert e.value.scene_id == "scene_02" and e.value.code == "unreadable_media"
    assert not (ctx.dir / "output" / "final.mp4").exists()
    st = json.loads((ctx.dir / "state.json").read_text(encoding="utf-8"))["stages"]
    assert st["render"]["status"] == "failed"
