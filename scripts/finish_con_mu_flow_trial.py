"""Import real Flow downloads and assemble a silent visual test, never a production replacement."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from studio.core.ffmpeg import run_ffmpeg
from studio.core.media_probe import probe
from studio.core.outputs import organized_output
from studio.core.project import ProjectContext
from studio.pipeline.runner import RunOptions, run_pipeline

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "flow_trials" / "con_mu_20261106"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(imports: list[str]) -> None:
    ctx = ProjectContext(PROJECT)
    records_path = ctx.work / "flow_imports.json"
    records = json.loads(records_path.read_text(encoding="utf-8")) if records_path.exists() else {}
    for item in imports:
        sid, source_string = item.split("=", 1)
        scene = ctx.project.scene(sid)  # validated IDs; no filenames constructed from unchecked input
        source = Path(source_string).resolve(strict=True)
        target = ctx.resolve(scene.visual.path)
        if target.exists() and sha(target) != sha(source):
            history = ctx.work / "flow_import_history"
            history.mkdir(exist_ok=True)
            shutil.copy2(target, history / f"{sid}_{sha(target)[:12]}.mp4")
        # Decode the WHOLE source before accepting a file that merely has valid metadata.
        run_ffmpeg(["-v", "error", "-xerror", "-i", str(source), "-map", "0:v:0", "-an", "-f", "null", "-"],
                   stage="flow_decode")
        if source != target:
            shutil.copy2(source, target)
        info = probe(target)
        video = next(s for s in info.raw["streams"] if s.get("codec_type") == "video")
        duration = float(video["duration"])
        # Preserve native duration; do not turn an eight-second request into a padded freeze.
        scene.duration_sec = duration
        records[sid] = {"source_file": str(source), "local_clip": str(target), "sha256": sha(target),
                        "native_width": info.width, "native_height": info.height, "native_fps": info.fps,
                        "video_duration_sec": duration, "whole_video_decode": "PASS",
                        "provider": "Google Flow web", "source_audio_kept_in_import": info.has_audio,
                        "trial_audio": "omitted; no replacement of accepted narration",
                        "creator_approved": False}
    ctx.save()
    records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    run_pipeline(ctx, RunOptions(only=["media"]))  # no TTS, approval bypass or production rendering
    native = [probe(ctx.resolve(s.visual.path)) for s in ctx.project.scenes]
    shapes = {(p.width, p.height, p.fps) for p in native}
    if len(shapes) != 1:
        raise RuntimeError(f"Different native formats; review before converting: {shapes}")
    width, height, fps = shapes.pop()
    work = ctx.work / "flow_assembly"
    work.mkdir(exist_ok=True)
    concat = work / "clips.ffconcat"
    concat.write_text("ffconcat version 1.0\n" + "".join(
        f"file '{ctx.resolve(s.visual.path).as_posix()}'\n" for s in ctx.project.scenes), encoding="utf-8")
    output = organized_output(ROOT / "output", "flow_trials", ctx.work / "trial_output_location.json")
    final = output / "con_mu__character_motion_trial.mp4"
    temp = work / "character_motion.tmp.mp4"
    # Test clips retain native 720p/24 fps and the provider watermark; no fake 1080p upgrade.
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat), "-map", "0:v:0", "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(temp)], stage="flow_trial")
    run_ffmpeg(["-v", "error", "-xerror", "-i", str(temp), "-map", "0:v:0", "-f", "null", "-"],
               stage="flow_trial_decode")
    result = probe(temp)
    black_log = run_ffmpeg(["-i", str(temp), "-vf", "blackdetect=d=0.2:pix_th=0.05",
                            "-an", "-f", "null", "-"], stage="flow_black", loglevel="info")
    (work / "blackdetect.log").write_text(black_log, encoding="utf-8")
    black_events = [line for line in black_log.splitlines() if "black_start:" in line]
    if black_events:
        raise RuntimeError(f"Black intervals require inspection: {black_events}")
    expected = sum(s.duration_sec for s in ctx.project.scenes)
    if abs(result.duration - expected) > 2 / fps:
        raise RuntimeError("Assembled duration differs from imported video streams")
    if final.exists() and sha(final) != sha(temp):
        history = output / "_history" / "con_mu_character_motion_trial"
        history.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final, history / f"{sha(final)[:12]}.mp4")
    shutil.copy2(temp, final)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 19)
    sheet = Image.new("RGB", (960, 3 * 208), "#eee5d7")
    draw = ImageDraw.Draw(sheet)
    labels = ["Hạnh ngẩng đầu", "Thu chân dưới ghế", "Bà Bảy chỉ di ảnh"]
    for row, scene in enumerate(ctx.project.scenes):
        path = ctx.resolve(scene.visual.path)
        for col, fraction in enumerate((0.03, 0.5, 0.93)):
            frame = work / f"{scene.scene_id}_{col}.jpg"
            run_ffmpeg(["-ss", str(scene.duration_sec * fraction), "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=320:180", str(frame)], stage="flow_sheet")
            sheet.paste(Image.open(frame), (col * 320, row * 208 + 28))
        draw.text((10, row * 208 + 4), labels[row], fill="#292622", font=font)
    sheet_path = final.with_suffix(".sheet.jpg")
    sheet.save(sheet_path, quality=94)
    report = {"kind": "VISUAL_EXPERIMENT_ONLY", "video": str(final), "sha256": sha(final),
              "native_format": {"width": width, "height": height, "fps": fps},
              "duration_sec": result.duration, "whole_video_decode": "PASS", "has_audio": result.has_audio,
              "black_intervals": black_events,
              "imports": records, "human_approval_created": False, "production_replaced": False,
              "editorial_status": "PENDING_AGENT_INSPECTION", "sheet": str(sheet_path)}
    final.with_suffix(".qc.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(final)
    print(sheet_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clip", action="append", default=[], metavar="SCENE_ID=ABSOLUTE_FILE")
    main(parser.parse_args().clip)
