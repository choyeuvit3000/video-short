from pathlib import Path

import pytest

from studio.core.errors import ManualGateRequired, StudioError
from studio.core.media_probe import MediaInfo
from studio.workflows.ai_cinematic import stage_media
from studio.workflows.flow_media import check_imported_clip

from .conftest import make_project, needs_ffmpeg


def project(tmp_path, settings):
    return make_project(tmp_path / "flow", settings, workflow="ai_cinematic", timing_mode="fixed",
                        video={"format": "test_9x16"},
                        options={"allow_still_fallback": False, "strict_clip_validation": True,
                                 "clip_min_short_side": 180},
                        scenes=[{"scene_id": "scene_01", "duration_sec": 4,
                                 "visual": {"type": "clip", "path": "clips/scene_01.mp4"}}])


def clip_info(**changes):
    fields = dict(path=Path("clip.mp4"), duration=8, has_video=True, width=180, height=320,
                  fps=30, vcodec="h264", raw={"streams": [{"codec_type": "video", "duration": "4"}]})
    fields.update(changes)
    return MediaInfo(**fields)


def test_images_cannot_complete_real_clip_gate(tmp_path, settings):
    ctx = project(tmp_path, settings)
    (ctx.dir / "images" / "scene_01.png").write_bytes(b"keyframe")
    with pytest.raises(ManualGateRequired) as caught:
        stage_media(ctx, {})
    assert "Still fallback is disabled" in caught.value.instructions
    assert "alone is enough" not in caught.value.instructions
    assert ctx.project.scenes[0].visual.type == "clip"


def test_old_still_fallback_cannot_complete_clip_only_trial(tmp_path, settings):
    ctx = project(tmp_path, settings)
    ctx.project.options["require_video_clips"] = True
    ctx.project.scenes[0].visual.type = "still"
    ctx.project.scenes[0].visual.path = "images/scene_01.png"
    (ctx.dir / "images" / "scene_01.png").write_bytes(b"old-fallback")
    with pytest.raises(ManualGateRequired) as caught:
        stage_media(ctx, {})
    assert "requires a clip" in caught.value.instructions


def test_require_clips_overrides_default_still_fallback(tmp_path, settings):
    ctx = project(tmp_path, settings)
    ctx.project.options.update(require_video_clips=True, allow_still_fallback=True)
    (ctx.dir / "images" / "scene_01.png").write_bytes(b"keyframe")
    with pytest.raises(ManualGateRequired) as caught:
        stage_media(ctx, {})
    assert "Still fallback is disabled" in caught.value.instructions
    assert ctx.project.scenes[0].visual.type == "clip"


@pytest.mark.parametrize("info,reason", [
    (clip_info(has_video=False), "no timed video"),
    (clip_info(raw={"streams": [{"codec_type": "video", "duration": "2"}]}), "no freeze fallback"),
    (clip_info(width=320, height=180), "aspect ratio"),
    (clip_info(width=90, height=160), "native video"),
    (clip_info(vcodec="png"), "not an imported video"),
    (clip_info(raw={"streams": [{"codec_type": "video"}]}), "duration is unavailable"),
])
def test_invalid_clips_stop_gate(tmp_path, settings, monkeypatch, info, reason):
    ctx = project(tmp_path, settings)
    (ctx.dir / "clips" / "scene_01.mp4").write_bytes(b"probe-is-mocked")
    monkeypatch.setattr("studio.workflows.flow_media.probe", lambda *a, **kw: info)
    with pytest.raises(ManualGateRequired) as caught:
        stage_media(ctx, {})
    assert reason in caught.value.instructions
    assert ctx.project.scenes[0].visual.type == "clip"


def test_video_duration_not_longer_container_audio(tmp_path, settings, monkeypatch):
    ctx = project(tmp_path, settings)
    info = clip_info(duration=20, has_audio=True,
                     raw={"streams": [{"codec_type": "video", "duration_ts": 60,
                                       "time_base": "1/30"},
                                      {"codec_type": "audio", "duration": "20"}]})
    monkeypatch.setattr("studio.workflows.flow_media.probe", lambda *a, **kw: info)
    assert "video is 2.000s" in check_imported_clip(ctx, ctx.project.scenes[0])


def test_valid_clip_resumes_without_mutation(tmp_path, settings, monkeypatch):
    ctx = project(tmp_path, settings)
    scene = ctx.project.scenes[0]
    (ctx.dir / scene.visual.path).write_bytes(b"probe-is-mocked")
    monkeypatch.setattr("studio.workflows.flow_media.probe", lambda *a, **kw: clip_info())
    assert "all media present" in stage_media(ctx, {})
    assert scene.visual.type == "clip"


def test_corrupt_clip_returns_repair_gate(tmp_path, settings, monkeypatch):
    ctx = project(tmp_path, settings)

    def broken(*a, **kw):
        raise StudioError("cannot decode clip", code="unreadable_media")

    monkeypatch.setattr("studio.workflows.flow_media.probe", broken)
    assert "cannot decode" in check_imported_clip(ctx, ctx.project.scenes[0])


@needs_ffmpeg
@pytest.mark.ffmpeg
def test_actual_mp4_does_not_hide_short_video_with_long_audio(tmp_path, settings):
    from studio.core.ffmpeg import run_ffmpeg

    ctx = project(tmp_path, settings)
    scene = ctx.project.scenes[0]
    target = ctx.resolve(scene.visual.path)
    for seconds in (1, 4):
        run_ffmpeg(["-f", "lavfi", "-i", f"testsrc2=s=180x320:r=30:d={seconds}",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(target)], stage="fixture")
        problem = check_imported_clip(ctx, scene)
        if seconds == 1:
            assert "video is 1.000s" in problem
        else:
            assert problem is None
