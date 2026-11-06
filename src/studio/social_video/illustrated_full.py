"""Landscape illustration revisions that preserve an accepted video's exact audio."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path

from ..core.errors import ManualGateRequired
from ..core.subtitles import Word, group_words, load_words
from ..core.user_review import digest, payload, require
from .quality import inspect, sha256
from .util import ffmpeg, read_json, run, write_json

VERSION = "illustrated-full-1"
FPS = 30


def frame_shots(shots: list[dict], seconds: float) -> list[dict]:
    """Snap shared cut boundaries once; reject gaps instead of padding the story."""
    result = []
    cursor = 0.0
    for shot in shots:
        start, end = float(shot["start_seconds"]), float(shot["end_seconds"])
        if not all(math.isfinite(x) for x in (start, end)) or abs(start - cursor) > .002 or end <= start:
            raise ValueError("Illustrated shots must cover the narration continuously")
        a, b = round(start * FPS), round(end * FPS)
        if b <= a:
            raise ValueError("Illustrated shot has no video frames")
        result.append({**shot, "first_frame": a, "frames": b - a})
        cursor = end
    if not result or abs(cursor - seconds) > .04:
        raise ValueError("Illustrated shots must end with the accepted narration")
    return result


def _time(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _text(text: str) -> str:
    return text.replace("\\", "／").replace("{", "(").replace("}", ")").replace("\n", " ")


def captions(folder: Path, work: Path, seconds: float) -> dict:
    """Stable two-line pages, with phrase emphasis at existing real speech anchors."""
    manifest = read_json(folder / "voice_manifest.json")
    all_words = []
    offset = 0.0
    for item, timing in zip(manifest["body"], manifest["timing_files"], strict=True):
        words, origin = load_words(Path(timing))
        if origin not in ("faster_whisper", "manual") or not words:
            raise ValueError("Illustrated subtitles require actual speech anchors")
        all_words.extend(Word(w.text, round(offset * 1000) + w.start_ms,
                              round(offset * 1000) + w.end_ms) for w in words)
        offset += item["seconds"]
    if abs(offset - seconds) > .04:
        raise ValueError("Narration and illustration duration differ")
    pages = group_words(all_words, max_words=14, max_chars=76, max_gap_ms=500)
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Story,Arial,49,&H00F4F8FF,&H009ADBF4,&H00100D0A,&H80100D0A,-1,0,0,0,100,100,0,0,1,2.8,1,2,160,160,68,1
Style: Label,Arial,24,&H00DFE7EB,&H00DFE7EB,&H40100D0A,&H80100D0A,0,0,0,0,100,100,0,0,1,1.5,0,7,44,44,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""  # noqa: E501
    title = _text(read_json(folder / "vi.json", {}).get("title", "Truyện kỳ dị"))[:90]
    events = [f"Dialogue: 0,0:00:00.00,{_time(seconds)},Label,,0,0,0,,Truyện hư cấu · {title}"]
    audit = []
    for i, page in enumerate(pages):
        start = page[0].start_ms / 1000
        next_start = pages[i + 1][0].start_ms / 1000 if i + 1 < len(pages) else seconds
        end = min(next_start, max(page[-1].end_ms / 1000 + .10, start + .10), seconds)
        # A fixed line break keeps geometry identical as the active phrase changes color.
        split = min(range(1, len(page)), key=lambda j: abs(
            len(" ".join(w.text for w in page[:j])) - len(" ".join(w.text for w in page[j:]))
        )) if len(page) > 7 else len(page)
        for first in range(0, len(page), 3):
            a = max(start, page[first].start_ms / 1000)
            b = min(end, page[first + 3].start_ms / 1000) if first + 3 < len(page) else end
            if b <= a:
                continue
            text = ""
            for k, word in enumerate(page):
                if k:
                    text += r"\N" if k == split else " "
                color = r"{\c&H9ADBF4&}" if first <= k < first + 3 else r"{\c&HF4F8FF&}"
                text += color + _text(word.text)
            events.append(f"Dialogue: 1,{_time(a)},{_time(b)},Story,,0,0,0,,{text}")
        audit.append({"start": start, "end": end, "text": " ".join(w.text for w in page),
                      "lines": 2 if split < len(page) else 1})
    out = work / "captions.ass"
    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    report = {"timing": "existing actual speech anchors", "pages": audit,
              "max_lines": 2, "emphasis_words": 3, "ass_sha256": sha256(out)}
    write_json(work / "caption_audit.json", report)
    return report


def audio_hash(video: Path, *, decoded: bool = False) -> str:
    codec = "pcm_s16le" if decoded else "copy"
    return run([ffmpeg(), "-v", "error", "-i", str(video), "-map", "0:a:0", "-c:a", codec,
                "-f", "hash", "-hash", "sha256", "-"]).stdout.strip()


def scene_signature(shot: dict, image_sha256: str, caption_sha256: str) -> str:
    """Unrelated illustration edits must not re-encode an unchanged scene."""
    values = {"version": VERSION, "image": image_sha256, "captions": caption_sha256,
              "first_frame": shot["first_frame"], "frames": shot["frames"], "crop": shot.get("crop")}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def render_revision(folder: Path, plan_path: Path, source: Path, output: Path) -> Path:
    """One user-requested visual revision; never synthesize or re-encode speech."""
    require(folder, "voice")
    ledger = read_json(folder / "user_reviews.json")
    if any(x["stage"] == "final" for x in ledger.get("approvals", [])):
        raise ManualGateRequired("visual_revision", "Bản cuối đã duyệt; cần chỉ dẫn sửa mới.")
    plan = read_json(plan_path)
    if not plan.get("selection_message") or plan.get("style_selected") not in ("A", "B"):
        raise ValueError("Creator's actual art-direction selection is required")
    if sha256(folder / "vi.json") != plan["script_sha256"]:
        raise ValueError("Accepted story changed during visual revision")
    if sha256(source) != plan["source_video_sha256"]:
        raise ValueError("The accepted source video changed")
    if digest(payload(folder, "voice")) != plan["source_voice_review_fingerprint"]:
        raise ValueError("The accepted voice packet changed during visual revision")
    work = plan_path.parent
    images = read_json(work / "image_manifest.json")["images"]
    by_key = {x["asset_key"]: x for x in images}
    seconds = float(plan["duration_seconds"])
    shots = frame_shots(plan["shots"], seconds)
    for shot in shots:
        asset = by_key[shot["asset_key"]]
        if sha256(Path(asset["path"])) != asset["sha256"]:
            raise ValueError("Illustration changed after inspection")
    caption_report = captions(folder, work, seconds)
    source_hash = sha256(source)
    source_audio = audio_hash(source)
    source_pcm = audio_hash(source, decoded=True)
    fingerprint = hashlib.sha256(json.dumps({"version": VERSION, "plan": plan,
        "images": images, "captions": caption_report["ass_sha256"], "source": source_hash},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    budget_path = work / "render_budget.json"
    budget = read_json(budget_path, {"attempts": []})
    records = [row for attempt in budget["attempts"] for row in [attempt, *attempt.get("repairs", [])]]
    prior = next((x for x in records if x["fingerprint"] == fingerprint), None)
    if prior and prior.get("status") == "COMPLETE" and output.exists() and prior.get("output_sha256") == sha256(output):
        return output
    if prior and prior.get("status") == "FAILED":
        raise ManualGateRequired("visual_render_budget", "Kiểm tra lỗi trước khi cấp lại lượt dựng ảnh.")
    if prior is None:
        prior = {"fingerprint": fingerprint, "status": "STARTED", "scope": "full_16x9_visual_revision",
                 "user_request": plan["user_request"], "selection_message": plan["selection_message"],
                 "audio_generation": False}
        request = next((x for x in budget["attempts"] if x.get("user_request") == plan["user_request"]
                        and x.get("selection_message") == plan["selection_message"]), None)
        if request is not None:
            if not plan.get("qc_repair_reason"):
                raise ManualGateRequired("visual_render_budget", "Cần ghi rõ lỗi QC và các cảnh phải sửa.")
            prior.update(scope="QC_REPAIR", reason=plan["qc_repair_reason"])
            request.setdefault("repairs", []).append(prior)
        else:
            budget["attempts"].append(prior)
        write_json(budget_path, budget)
    segments = work / "segments"
    segments.mkdir(exist_ok=True)
    paths = []
    for i, shot in enumerate(shots):
        asset = by_key[shot["asset_key"]]
        clip = segments / f"shot_{i + 1:02d}.mp4"
        key = scene_signature(shot, asset["sha256"], caption_report["ass_sha256"])
        state = read_json(clip.with_suffix(".json"), {})
        if not clip.exists() or state.get("key") != key or state.get("sha256") != sha256(clip):
            n = shot["frames"]
            start = shot["first_frame"] / FPS
            zoom = f"1+0.045*on/{max(1, n - 1)}" if i % 2 == 0 else f"1.045-0.045*on/{max(1, n - 1)}"
            crop = shot.get("crop")
            framing = f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}," if crop else ""
            vf = (framing + "scale=2304:1296:force_original_aspect_ratio=increase,crop=2304:1296,"
                  f"zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={n}:s=1920x1080:fps=30,"
                  f"setpts=PTS+{start:.8f}/TB,ass=filename='captions.ass',setpts=PTS-STARTPTS,setsar=1")
            run([ffmpeg(), "-y", "-v", "error", "-i", asset["path"], "-vf", vf,
                 "-frames:v", str(n), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-threads", "4", "-pix_fmt", "yuv420p", str(clip.resolve())], cwd=work)
            write_json(clip.with_suffix(".json"), {"key": key, "sha256": sha256(clip), "frames": n})
        paths.append(clip)
        print(f"Illustrated scene {i + 1}/{len(shots)}: {shot['asset_key']}", flush=True)
    listing = work / "scenes.ffconcat"
    listing.write_text("ffconcat version 1.0\n" + "\n".join(
        f"file '{p.resolve().as_posix()}'" for p in paths) + "\n", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    candidate = output.with_name(output.stem + ".illustrated-candidate.mp4")
    run([ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-i", str(source), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
         "-movflags", "+faststart", str(candidate)])
    if audio_hash(candidate) != source_audio or audio_hash(candidate, decoded=True) != source_pcm:
        raise ValueError("Visual-only revision changed the accepted audio")
    report = inspect(candidate, seconds, width=1920, height=1080)
    if report["errors"]:
        raise ValueError(f"Illustrated revision QC failed: {report['errors']}")
    if output.exists():
        history = output.parent / "_history" / output.stem
        history.mkdir(parents=True, exist_ok=True)
        previous = history / (sha256(output)[:12] + ".mp4")
        if not previous.exists():
            shutil.copy2(output, previous)
    candidate.replace(output)
    candidate.with_suffix(".sheet.jpg").replace(output.with_suffix(".sheet.jpg"))
    report["sheet"] = output.with_suffix(".sheet.jpg").name
    report["visual_revision"] = {"style": plan["style_selected"], "shots": len(shots),
                                 "source_audio_sha256": source_audio, "decoded_audio_sha256": source_pcm,
                                 "audio_identical": True, "plan_sha256": sha256(plan_path)}
    write_json(output.with_suffix(".qc.json"), report)
    candidate.with_suffix(".qc.json").unlink(missing_ok=True)
    prior.update(status="COMPLETE", output=str(output), output_sha256=sha256(output))
    write_json(budget_path, budget)
    write_json(work / "render_manifest.json", {"fingerprint": fingerprint, "output": str(output),
        "sha256": sha256(output), "source_video": str(source), "source_video_sha256": source_hash,
        "aac_sha256": source_audio, "decoded_audio_sha256": source_pcm, "audio_identical": True,
        "tts_calls": 0, "images": images, "caption_audit": caption_report, "creator_final_approved": False})
    return output
