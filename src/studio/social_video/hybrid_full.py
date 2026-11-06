"""Requested full-story visual revisions using Flow clips and cached stable illustrations."""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from ..core.media_probe import probe
from ..core.user_review import digest, payload, require
from .camera_motion import encode_scene
from .illustrated_full import audio_hash, captions, frame_shots, scene_signature
from .quality import inspect, sha256
from .util import ffmpeg, read_json, run, write_json

VERSION = "flow-illustration-hybrid-1"
FPS = 30


def parts_for_shot(shot: dict, replacement: dict | None) -> list[dict]:
    if replacement is None:
        return [{"type": "cached", "first_frame": shot["first_frame"], "frames": shot["frames"]}]
    prefix = replacement.get("still_prefix_frames", 0)
    if not isinstance(prefix, int) or isinstance(prefix, bool) or not 0 <= prefix < shot["frames"]:
        raise ValueError("Still prefix must leave a positive Flow window inside its scene")
    if prefix and not replacement.get("still_path"):
        raise ValueError("An authored illustration prefix needs its own still image")
    result = ([{"type": "still", "first_frame": shot["first_frame"], "frames": prefix}] if prefix else [])
    result.append({"type": "flow", "first_frame": shot["first_frame"] + prefix,
                   "frames": shot["frames"] - prefix})
    return result


def video_retime(source_seconds: float, target_frames: int, *, allow: bool) -> float:
    """Retiming is visual only, bounded to a small explicitly authored adjustment."""
    if not math.isfinite(source_seconds) or source_seconds <= 0 or target_frames < 1:
        raise ValueError("Clip duration and frame count must be positive")
    target = target_frames / FPS
    if target <= source_seconds + 2 / FPS:
        return 1.0
    ratio = target / source_seconds
    if not allow or ratio > 1.06:
        raise ValueError("Flow clip cannot cover its window without unapproved slowing or a freeze")
    return ratio


def _encode_flow(clip: Path, output: Path, part: dict, *, work: Path, allow_retime: bool) -> dict:
    info = probe(clip)
    duration = float(next(s["duration"] for s in info.raw["streams"] if s.get("codec_type") == "video"))
    factor = video_retime(duration, part["frames"], allow=allow_retime)
    # The two-frame guard only covers frame-rate endpoint rounding. No scene-long padding.
    vf = (f"setpts=(PTS-STARTPTS)*{factor:.12f},fps=30,"
          "tpad=stop_mode=clone:stop_duration=0.066666667,"
          "scale=1920:1080:flags=lanczos,setsar=1,"
          f"trim=end_frame={part['frames']},setpts=PTS+{part['first_frame']/FPS:.10f}/TB,"
          "ass=filename='captions.ass',setpts=PTS-STARTPTS")
    run([ffmpeg(), "-y", "-v", "error", "-i", str(clip), "-vf", vf,
         "-frames:v", str(part["frames"]), "-an", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-threads", "4", "-pix_fmt", "yuv420p", str(output.resolve())], cwd=work)
    result = probe(output)
    actual_frames = int(next(s["nb_frames"] for s in result.raw["streams"] if s.get("codec_type") == "video"))
    if actual_frames != part["frames"]:
        raise ValueError("Flow output has missing video frames")
    return {"native_width": info.width, "native_height": info.height, "native_fps": info.fps,
            "native_seconds": duration, "visual_retime": factor, "narration_retime": 1.0}


def render_hybrid(folder: Path, plan_path: Path) -> Path:
    plan = read_json(plan_path)
    work = plan_path.parent
    accepted = require(folder, "final")
    require(folder, "voice")
    ledger_sha = sha256(folder / "user_reviews.json")
    if accepted["fingerprint"] != plan["accepted_final_fingerprint"]:
        raise ValueError("The accepted source review changed")
    if not plan.get("user_request") or not plan.get("hybrid_selection_message"):
        raise ValueError("The current requested visual revision and hybrid choice must be recorded")
    if sha256(folder / "vi.json") != plan["script_sha256"]:
        raise ValueError("Approved script changed")
    if digest(payload(folder, "voice")) != plan["voice_fingerprint"]:
        raise ValueError("Approved voice packet changed")
    source = Path(plan["source_video"])
    if sha256(source) != plan["source_video_sha256"]:
        raise ValueError("Accepted source video changed")
    accepted_videos = payload(folder, "final")["videos"]
    if not any(x["sha256"] == plan["source_video_sha256"] for x in accepted_videos):
        raise ValueError("Audio source is not an accepted final video")
    output = Path(plan["output"])
    if output.resolve() in {Path(x["path"]).resolve() for x in accepted_videos}:
        raise ValueError("The new visual version must preserve the accepted original")
    baseline = Path(plan["baseline_plan"])
    if sha256(baseline) != plan["baseline_plan_sha256"]:
        raise ValueError("Baseline scene timing changed")
    base = read_json(baseline)
    shots = frame_shots(base["shots"], base["duration_seconds"])
    audit = captions(folder, work, base["duration_seconds"])
    if audit["ass_sha256"] != sha256(baseline.parent / "captions.ass"):
        raise ValueError("This revision cannot change accepted subtitle text or timing")
    images = {x["asset_key"]: x for x in read_json(baseline.parent / "image_manifest.json")["images"]}
    replacements = {int(x["shot"]): x for x in plan["replacements"]}
    if not set(replacements).issubset({s["shot"] for s in shots}):
        raise ValueError("Replacement references an unknown scene")
    audio_aac = audio_hash(source)
    audio_pcm = audio_hash(source, decoded=True)
    fingerprint = digest({"version": VERSION, "plan": plan, "captions": audit["ass_sha256"]})
    budget_path = work / "render_budget.json"
    budget = read_json(budget_path, {"attempts": []})
    previous = next((x for x in budget["attempts"] if x["fingerprint"] == fingerprint), None)
    if previous and previous.get("status") == "COMPLETE" and output.is_file():
        if sha256(output) == previous["sha256"]:
            return output
    if previous is None:
        previous = {"fingerprint": fingerprint, "status": "STARTED", "request": plan["user_request"],
                    "scope": "requested_visual_revision_only", "tts_calls": 0, "generation_calls": 0}
        budget["attempts"].append(previous)
        write_json(budget_path, budget)
    segment_dir = work / "segments"
    segment_dir.mkdir(exist_ok=True)
    records = []
    paths = []
    for index, shot in enumerate(shots):
        replacement = replacements.get(shot["shot"])
        image = images[shot["asset_key"]]
        if sha256(Path(image["path"])) != image["sha256"]:
            raise ValueError("Baseline artwork changed")
        for j, part in enumerate(parts_for_shot(shot, replacement)):
            if part["type"] == "cached":
                clip = baseline.parent / "segments" / f"shot_{index+1:02d}.mp4"
                state = read_json(clip.with_suffix(".json"))
                expected = scene_signature(shot, image["sha256"], audit["ass_sha256"])
                if state["key"] != expected or sha256(clip) != state["sha256"]:
                    raise ValueError("Cached illustration scene is stale")
                details = {"cache_reused": True}
            else:
                media_type = part["type"]
                source_path = Path(replacement["still_path" if media_type == "still" else "clip_path"])
                expected_sha = replacement["still_sha256" if media_type == "still" else "clip_sha256"]
                if sha256(source_path) != expected_sha:
                    raise ValueError("Replacement media changed")
                clip = segment_dir / f"shot_{shot['shot']:02d}_{j}_{media_type}.mp4"
                key = digest({"version": VERSION, "source": expected_sha, "part": part,
                              "captions": audit["ass_sha256"], "replacement": replacement})
                state = read_json(clip.with_suffix(".json"), {})
                if clip.is_file() and state.get("key") == key and state.get("sha256") == sha256(clip):
                    details = state["details"]
                else:
                    if media_type == "still":
                        encode_scene(source_path, clip, frames=part["frames"], first_frame=part["first_frame"],
                                     zoom_in=False, crop=None, work=work)
                        details = {"motion": "subpixel zoom-out to match the fixed-camera clip"}
                    else:
                        details = _encode_flow(source_path, clip, part, work=work,
                                               allow_retime=replacement.get("allow_video_retime", False))
                    write_json(clip.with_suffix(".json"), {"key": key, "sha256": sha256(clip), "details": details})
            paths.append(clip)
            records.append({"shot": shot["shot"], "asset_key": shot["asset_key"], **part,
                            "path": str(clip), "sha256": sha256(clip), **details})
        print(f"Hybrid scene {index+1}/{len(shots)}: {shot['asset_key']}", flush=True)
    if sum(x["frames"] for x in records) != sum(x["frames"] for x in shots):
        raise ValueError("Hybrid revision changed total scene coverage")
    listing = work / "hybrid.ffconcat"
    listing.write_text("ffconcat version 1.0\n" + "\n".join(
        f"file '{p.resolve().as_posix()}'" for p in paths) + "\n", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    candidate = output.with_name(output.stem + ".candidate.mp4")
    run([ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-i", str(source), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
         "-movflags", "+faststart", str(candidate)])
    if audio_hash(candidate) != audio_aac or audio_hash(candidate, decoded=True) != audio_pcm:
        raise ValueError("Hybrid revision changed the accepted narration/music/SFX")
    report = inspect(candidate, base["duration_seconds"], width=1920, height=1080)
    if report["errors"]:
        raise ValueError(f"Hybrid QC failed: {report['errors']}")
    if sha256(folder / "user_reviews.json") != ledger_sha:
        raise ValueError("The original creator approval ledger must remain unchanged")
    if output.exists():
        history = output.parent / "_history" / output.stem / sha256(output)[:12]
        history.mkdir(parents=True, exist_ok=True)
        for old in (output, output.with_suffix(".qc.json"), output.with_suffix(".sheet.jpg")):
            if old.is_file():
                shutil.copy2(old, history / old.name)
    candidate.replace(output)
    candidate.with_suffix(".sheet.jpg").replace(output.with_suffix(".sheet.jpg"))
    report.update(sheet=output.with_suffix(".sheet.jpg").name, hybrid={
        "source_audio_sha256": audio_aac, "decoded_audio_sha256": audio_pcm,
        "audio_identical": True, "creator_ledger_unchanged": True, "new_human_approval_created": False,
        "tts_calls": 0, "new_generation_calls": 0, "parts": records})
    write_json(output.with_suffix(".qc.json"), report)
    candidate.with_suffix(".qc.json").unlink(missing_ok=True)
    shutil.copy2(work / "captions.ass", output.with_suffix(".captions.ass"))
    previous.update(status="COMPLETE", output=str(output), sha256=sha256(output))
    write_json(budget_path, budget)
    write_json(work / "render_manifest.json", {"fingerprint": fingerprint, "path": str(output),
        "sha256": sha256(output), "parts": records, "audio_aac": audio_aac, "audio_pcm": audio_pcm,
        "script_sha256": plan["script_sha256"], "original_ledger_sha256": ledger_sha,
        "new_human_approval_created": False})
    return output
