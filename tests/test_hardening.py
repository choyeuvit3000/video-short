"""Re-runs skip unchanged work, old renders are kept, QC looks at the content (sound, picture, captions)."""

import json

import pytest

from studio.core.errors import EXIT_QC_FAIL, QCFailed
from studio.core.ffmpeg import run_ffmpeg
from studio.core.outputs import archive_previous
from studio.core.qc_analysis import caption_layout, parse_analysis
from studio.pipeline.runner import RunOptions, run_pipeline

from .conftest import make_project, needs_ffmpeg, three_scene_fixed

STAGES = ["validate", "voice", "render", "qc", "package"]


def _state(ctx):
    return json.loads(ctx.state_path.read_text(encoding="utf-8"))["stages"]


def _qc(ctx):
    return json.loads((ctx.output / "qc_report.json").read_text(encoding="utf-8"))


def _mtimes(paths):
    return {p.name: p.stat().st_mtime_ns for p in paths}


@needs_ffmpeg
@pytest.mark.ffmpeg
def test_rerun_skips_unchanged_stages_and_keeps_old_render(tmp_path, settings):
    ctx = three_scene_fixed(tmp_path / "p", settings)
    run_pipeline(ctx, RunOptions(only=STAGES))
    rep = _qc(ctx)
    assert rep["status"] == "PASS" and rep["warnings"] == [], rep
    assert -16 <= rep["checks"]["audio"]["integrated_lufs"] <= -12  # loudness-normalised
    final = ctx.output / "final.mp4"
    first = final.stat().st_mtime_ns
    audio = _mtimes((ctx.dir / "audio").glob("*.*"))
    segs = _mtimes(ctx.work.glob("seg_*.mp4"))
    assert len(segs) == 3

    # same input -> render / qc / package are not rebuilt
    run_pipeline(ctx, RunOptions(only=STAGES))
    st = _state(ctx)
    assert all(st[s].get("skipped") for s in ("render", "qc", "package")), st
    assert final.stat().st_mtime_ns == first
    assert not (ctx.output / "history").exists()

    # caption style changed -> render again, but no new TTS and every scene segment reused
    ctx.project.video.caption_style = "clean_box"
    ctx.save()
    run_pipeline(ctx, RunOptions(only=STAGES))
    st = _state(ctx)
    assert not st["render"].get("skipped") and not st["qc"].get("skipped")
    assert final.stat().st_mtime_ns != first
    assert _mtimes((ctx.dir / "audio").glob("*.*")) == audio
    assert _mtimes(ctx.work.glob("seg_*.mp4")) == segs
    kept = list((ctx.output / "history").iterdir())
    assert len(kept) == 1 and {f.name for f in kept[0].iterdir()} >= {"final.mp4", "captions.srt", "qc_report.json"}

    # an output edited or deleted by hand is rebuilt even though the inputs did not change
    (ctx.output / "metadata.md").unlink()
    run_pipeline(ctx, RunOptions(only=STAGES))
    assert not _state(ctx)["package"].get("skipped") and (ctx.output / "metadata.md").exists()

    # --force rebuilds everything
    second = final.stat().st_mtime_ns
    run_pipeline(ctx, RunOptions(only=STAGES, force=True))
    assert not _state(ctx)["render"].get("skipped") and final.stat().st_mtime_ns != second


@needs_ffmpeg
@pytest.mark.ffmpeg
def test_qc_catches_silent_audio_black_frozen_clip_and_runaway_caption(tmp_path, settings):
    ctx = make_project(tmp_path / "p", settings, audio={"source": "manual", "voice_profile": None},
                       scenes=[{"scene_id": "s1", "narration": "Supercalifragilisticexpialidocious quá",
                                "audio_path": "audio/take.wav", "visual": {"type": "clip", "path": "clips/x.mp4"}}])
    (ctx.dir / "clips").mkdir(exist_ok=True)
    run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=360x640:r=30:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(ctx.dir / "clips" / "x.mp4")], stage="fixture")
    run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "3", str(ctx.dir / "audio" / "take.wav")],
               stage="fixture")
    with pytest.raises(QCFailed) as e:
        run_pipeline(ctx, RunOptions(only=STAGES))
    assert e.value.exit_code == EXIT_QC_FAIL
    rep = _qc(ctx)
    text = " | ".join(rep["errors"] + rep["warnings"])
    assert rep["status"] == "FAIL"
    assert "essentially silent" in text
    assert "black" in text
    assert "frozen" in text
    assert "run off the frame" in text
    assert rep["checks"]["captions"]["measured"] in ("font", "estimate")


def _ass(tmp_path, text, font="NoSuchFont"):
    p = tmp_path / "c.ass"
    p.write_text("[V4+ Styles]\nStyle: Caption," + font + ",28,&H00FFFFFF,&H00FFFFFF,&H00000000,&H60000000,-1,0,0,0,"
                 "100,100,0,0,1,6,2,2,30,46,200,1\n[Events]\n"
                 f"Dialogue: 0,0:00:00.00,0:00:01.00,Caption,,0,0,0,,{text}\n", encoding="utf-8")
    return p


@pytest.mark.parametrize(("chars", "where"), [(10, None), (19, "outside_safe_zone"), (25, "outside_frame")])
def test_caption_layout_against_safe_zone(tmp_path, chars, where):
    # unknown font -> width estimate 0.6 * size per char; box 360-30-46 = 284 px, safe zone left 20 / right 46
    lay = caption_layout(_ass(tmp_path, "{\\c&H00FFFFFF}" + "M" * chars), width=360, height=640,
                         safe={"top": 70, "bottom": 160, "left": 20, "right": 46}, font_dirs=[])
    assert lay["measured"] == "estimate"
    for k in ("outside_safe_zone", "outside_frame"):
        assert bool(lay[k]) == (k == where), lay


def test_parse_analysis_log():
    log = """
[blackdetect @ 0] black_start:0 black_end:1.5 black_duration:1.5
[freezedetect @ 0] lavfi.freezedetect.freeze_start: 2.0
[freezedetect @ 0] lavfi.freezedetect.freeze_duration: 1.0
[freezedetect @ 0] lavfi.freezedetect.freeze_end: 3.0
[freezedetect @ 0] lavfi.freezedetect.freeze_start: 7.5
[silencedetect @ 0] silence_start: 4.2
[silencedetect @ 0] silence_end: 6.4 | silence_duration: 2.2
[Parsed_ebur128_0 @ 0] Summary:
  Integrated loudness:
    I:         -14.2 LUFS
  True peak:
    Peak:       -1.6 dBFS
"""
    a = parse_analysis(log, 9.0)
    assert a["black"] == [(0.0, 1.5)]
    assert a["freeze"] == [(2.0, 3.0), (7.5, 9.0)]  # still frozen at the end of the file
    assert a["silence"] == [(4.2, 6.4)]
    assert (a["integrated_lufs"], a["true_peak_db"]) == (-14.2, -1.6)
    silent = parse_analysis("Integrated loudness:\n    I:         -70.0 LUFS\n  True peak:\n    Peak: -inf dBFS", 1)
    assert silent["integrated_lufs"] == -70.0 and silent["true_peak_db"] == float("-inf")
    assert parse_analysis("", 1)["integrated_lufs"] is None


def test_history_keeps_only_newest(tmp_path):
    import os

    out = tmp_path / "output"
    out.mkdir()
    for i in range(4):
        (out / "final.mp4").write_bytes(b"v%d" % i)
        (out / "qc_report.json").write_text("{}", encoding="utf-8")
        t = 1_700_000_000 + i * 60
        os.utime(out / "final.mp4", (t, t))
        archive_previous(out, keep=2)
    kept = sorted((out / "history").iterdir())
    assert len(kept) == 2
    assert [(d / "final.mp4").read_bytes() for d in kept] == [b"v2", b"v3"]
    assert not (out / "final.mp4").exists()
    assert archive_previous(out, keep=0) is None
