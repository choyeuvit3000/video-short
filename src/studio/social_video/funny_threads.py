"""Source-faithful funny Threads: reviewed cast, separated turns and frame-exact covers."""

from __future__ import annotations

import difflib
import hashlib
import math
import re
import shutil
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..core.config import get_settings
from ..core.errors import ValidationError
from ..core.ffmpeg import run_ffmpeg
from ..core.media_probe import probe
from ..core.user_review import digest, payload, read, require, sha, write
from ..core.voice_policy import assert_not_blocked, signature
from ..providers.tts import get_provider
from ..voices import load_registry, with_speed
from .quality import publish

FPS = 30
VERSION = "funny-threads-multicast-1"
ROOT = Path(__file__).resolve().parents[3]
VOICE_IDS = {
    "Ngọc Huyền": "vieneu-gallery-ngoc-huyen",
    "Mỹ Duyên": "vieneu-gallery-my-duyen",
    "Quang Sơn": "vieneu-gallery-quang-son",
    "Minh Đức": "vieneu-gallery-minh-duc",
}


def cover_window(total_frames: int, duration_frames: int = 3) -> tuple[int, int]:
    if type(total_frames) is not int or type(duration_frames) is not int or total_frames < 9 or duration_frames != 3:
        raise ValueError("The requested one-tenth-second cover must occupy exactly three frames at 30 fps")
    start = total_frames // 2
    return start, start + duration_frames  # half-open: never four frames


def turn_frames(audio_seconds: float, pause_seconds: float, minimum: float = 0) -> int:
    if not all(math.isfinite(x) and x >= 0 for x in [audio_seconds, pause_seconds, minimum]):
        raise ValueError("Turn durations must be finite and non-negative")
    return max(1, math.ceil(max(audio_seconds + pause_seconds, minimum) * FPS - 1e-8))


def cast_signature(plan: dict, registry) -> dict:
    choices = []
    last_comment = None
    authors = {}
    for beat in plan["beats"]:
        if not beat.get("narration", "").strip():
            continue
        profile = registry.get(VOICE_IDS[beat["voice"]])
        assert_not_blocked(profile.provider, profile.id, profile.params)
        speed = float(beat["speed"])
        if not 0.9 <= speed <= 1.3:
            raise ValueError("Review a natural reading speed before preparing this cast")
        if beat["kind"] == "comment":
            if profile.id == last_comment:
                raise ValueError("Adjacent comments must have distinct voices")
            last_comment = profile.id
        author = beat.get("author")
        if author and authors.setdefault(author, profile.id) != profile.id:
            raise ValueError("The same author must retain the same performed voice")
        choices.append(
            {
                "beat": beat["id"],
                "profile": profile.id,
                "voice_signature": signature(profile),
                "speed": speed,
                "region": beat["region"],
                "gender": beat["gender"],
            }
        )
    return {"version": VERSION, "cast": choices, "plan_sha256": digest(plan)}


def validate_files(files: list[dict]) -> None:
    for entry in files:
        if sha(Path(entry["path"])) != entry["sha256"]:
            raise ValidationError(f"Changed funny Threads input: {entry['path']}", code="review_voice_stale")


def snapshot(folder: Path, plan: dict) -> list[dict]:
    root = ROOT / "assets"
    library = read(root / "shared/overlays/funny_originals/library.json")
    music = next(x for x in read(root / "shared/music/library.json")["tracks"] if x["id"] == plan["music_id"])
    if not music.get("production_eligible"):
        raise ValueError("Music is a reference/preview, not an eligible production asset")
    paths = [Path(plan["background"]["path"]), folder / "cover_preview.png"]
    validate_files(list(plan["source"]["crops"].values()))
    paths += [Path(x["path"]) for x in plan["source"]["crops"].values()]
    for asset in [music, *library["items"]]:
        path = root / asset["path"]
        if not asset.get("production_eligible") or sha(path) != asset["sha256"]:
            raise ValueError("Missing, changed or ineligible comedy asset")
        paths.append(path)
    return [{"path": str(p.resolve()), "sha256": sha(p)} for p in dict.fromkeys(paths)]


def _pcm(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as f:
        if (f.getsampwidth(), f.getframerate(), f.getnchannels()) != (2, 48000, 2):
            raise ValueError("Funny mix requires protected stereo 48 kHz PCM")
        return np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").reshape(-1, 2).astype(np.float64) / 32768


def _write_pcm(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        f.writeframes((np.clip(samples, -0.98, 0.98) * 32767).astype("<i2").tobytes())


def _rms(samples: np.ndarray) -> float:
    active = samples[np.max(np.abs(samples), axis=1) > 0.008]
    return float(np.sqrt(np.mean(active**2))) if len(active) else 0.01


def prepare_voice(folder: Path) -> dict:
    """Quarantined project audition only, after the creator's script acceptance."""
    folder = folder.resolve()
    require(folder, "script")
    plan = read(folder / "merged_plan.json")
    registry = load_registry(get_settings())
    choices = cast_signature(plan, registry)
    inputs = snapshot(folder, plan)
    work = folder / "work/funny_voice"
    work.mkdir(parents=True, exist_ok=True)
    previous = read(folder / "voice_manifest.json", {})
    assets, files, slots = {}, [], []
    cursor = 0
    for i, beat in enumerate(plan["beats"]):
        narration = beat.get("narration", "").strip()
        audio = None
        if narration:
            profile = with_speed(registry.get(VOICE_IDS[beat["voice"]]), beat["speed"])
            key = digest([narration, signature(profile), profile.params, VERSION])
            native = work / f"{beat['id']}_{key[:12]}.wav"
            cached = read(native.with_suffix(".cache.json"), {})
            if not native.is_file() or cached.get("sha256") != sha(native):
                # An audition does not admit a voice globally or consume a production fallback.
                get_provider(profile.provider, registry).audition(narration, profile, native)
                write(
                    native.with_suffix(".cache.json"), {"sha256": sha(native), "key": key, "human_listening": "PENDING"}
                )
            audio = work / f"{beat['id']}_pcm.wav"
            run_ffmpeg(
                ["-i", str(native), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(audio)], stage="funny_pcm"
            )
            frames = turn_frames(
                probe(audio).duration, beat.get("post_pause_seconds", 0.6), beat.get("min_duration", 0)
            )
            assets[str(i)] = {
                "audio": str(audio),
                "sha256": sha(audio),
                "profile": profile.id,
                "text": narration,
                "text_sha256": hashlib.sha256(narration.encode()).hexdigest(),
                "speed": beat["speed"],
                "source": str(native),
                "source_sha256": sha(native),
            }
            files += [audio, native, native.with_suffix(".cache.json")]
        else:
            frames = turn_frames(float(beat["duration"]), 0)
        slots.append(
            {
                "beat": beat["id"],
                "index": i,
                "first_frame": cursor,
                "frames": frames,
                "audio": str(audio) if audio else None,
            }
        )
        cursor += frames
    timeline = {
        "fps": FPS,
        "total_frames": cursor,
        "duration": cursor / FPS,
        "slots": slots,
        "cover_frames": cover_window(cursor),
        "cast_choices": choices,
        "inputs": inputs,
    }
    write(folder / "funny_timeline.json", timeline)
    mixed = mix(folder, plan, timeline)
    files += [mixed, folder / "funny_timeline.json"]
    manifest = {
        "mode": "funny_threads",
        "version": VERSION,
        "cast_choices": choices,
        "beats": assets,
        "files": [str(p) for p in files],
        "input_files": inputs,
        "speech_checks": previous.get("speech_checks", {}),
        "status": "QUARANTINED_PROJECT_AUDITION",
        "human_listening": "PENDING",
        "mixed_audio": str(mixed),
    }
    write(folder / "voice_manifest.json", manifest)
    layouts(folder)
    return manifest


def mix(folder: Path, plan: dict, timeline: dict) -> Path:
    work = folder / "work/funny_voice"
    count = timeline["total_frames"] * 1600  # 48 kHz / 30 fps
    voice = np.zeros((count, 2), dtype=np.float64)
    for slot in timeline["slots"]:
        if not slot["audio"]:
            continue
        samples = _pcm(Path(slot["audio"]))
        gain = min(0.1 / _rms(samples), 0.82 / max(np.max(np.abs(samples)), 1e-6))
        at = slot["first_frame"] * 1600
        voice[at : at + len(samples)] += samples * gain
    library = read(ROOT / "assets/shared/music/library.json")
    track = next(x for x in library["tracks"] if x["id"] == plan["music_id"])
    bed_path = work / "music_pcm.wav"
    run_ffmpeg(
        [
            "-ss",
            "0",
            "-i",
            str(ROOT / "assets" / track["path"]),
            "-t",
            str(timeline["duration"]),
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(bed_path),
        ],
        stage="funny_music",
    )
    bed = _pcm(bed_path)
    if len(bed) < count:
        raise ValueError("Music source cannot cover the requested preview")
    relative_db = float(plan["audio_policy"]["music_relative_to_voice_db"])
    bed = bed[:count] * (_rms(voice) * 10 ** (relative_db / 20) / _rms(bed))
    # Slow envelope: no harsh pumping or sentence-edge cuts.
    gate = (np.max(np.abs(voice), axis=1) > 0.008).astype(float)
    smooth = np.convolve(gate[::480], np.ones(21) / 21, mode="same")
    duck = np.interp(np.arange(count) / 480, np.arange(len(smooth)), smooth)
    bed *= (1 - 0.25 * duck)[:, None]
    for slot, beat in zip(timeline["slots"], plan["beats"], strict=True):
        if beat["kind"] != "reaction":
            continue
        start = slot["first_frame"] * 1600
        end = min(count, start + round(0.35 * 48000))
        before = max(0, start - 2400)
        after = min(count, end + 5760)
        bed[before:start] *= np.linspace(1, 0.18, start - before)[:, None]
        bed[start:end] *= 0.18
        bed[end:after] *= np.linspace(0.18, 1, after - end)[:, None]
    fades = np.minimum(1, np.minimum(np.arange(count) / 14400, (count - np.arange(count)) / 24000))
    result = voice + bed * np.maximum(fades, 0)[:, None]
    effects = read(ROOT / "assets/shared/overlays/funny_originals/library.json")["items"]
    effect_ids = [
        "soft-pop",
        "reveal-dings",
        "comic-boing",
        "short-whoosh",
        "question-chirp",
        "mini-ta-da",
        "soft-bonk",
    ]
    for slot, slug in zip(timeline["slots"], effect_ids, strict=False):
        asset = next(x for x in effects if x["id"] == f"s:studio-original/{slug}")
        pcm = work / f"sfx_{slug}.wav"
        run_ffmpeg(
            ["-i", str(ROOT / "assets" / asset["path"]), "-ar", "48000", "-ac", "2", str(pcm)], stage="funny_sfx"
        )
        samples = _pcm(pcm) * 0.16
        start = slot["first_frame"] * 1600
        result[start : start + len(samples)] += samples[: count - start]
    out = work / "full_mix.wav"
    _write_pcm(out, result)
    (folder / "CREDITS.txt").write_text(
        track["attribution"]
        + (
            "\nSource screenshots: @nhinguyen_207 and visible commenters, "
            "from creator-supplied NẮNG AUDIO reference. New gameplay, mix and local original reactions.\n"
        ),
        encoding="utf-8",
    )
    return out


def layouts(folder: Path) -> list[Path]:
    plan = read(folder / "merged_plan.json")
    out = folder / "work/previews"
    out.mkdir(parents=True, exist_ok=True)
    ink, paper, yellow = "#152b24", "#fff8e8", "#ffdc5d"

    def font(n):
        return ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", n)

    results = []
    for beat in plan["beats"]:
        im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((58, 202, 365, 260), radius=10, fill=yellow)
        d.text((78, 214), "THREADS VUI", font=font(32), fill=ink)
        d.text((60, 303), "HỎI GU MẶC ÁO", font=font(68), fill=paper, stroke_width=2, stroke_fill=ink)
        d.text((60, 389), "Bình luận thành album", font=font(54), fill=yellow, stroke_width=2, stroke_fill=ink)
        d.rounded_rectangle((60, 490, 960, 546), radius=8, fill=paper)
        d.text((80, 502), beat.get("label", "BÌNH LUẬN VÀO VIỆC LIỀN"), font=font(27), fill=ink)
        if beat.get("source_crop"):
            card = Image.open(plan["source"]["crops"][beat["source_crop"]]["path"]).convert("RGBA")
            box = (920, 350) if beat.get("media_crop") else (920, 980)
            card = ImageOps.contain(card, box, Image.Resampling.LANCZOS)
            y = 590 if beat.get("media_crop") else 590 + (980 - card.height) // 2
            im.alpha_composite(card, ((1080 - card.width) // 2, y))
            if beat.get("media_crop"):
                picture = Image.open(plan["source"]["crops"][beat["media_crop"]]["path"]).convert("RGBA")
                picture = ImageOps.contain(picture, (850, 750), Image.Resampling.LANCZOS)
                im.alpha_composite(picture, ((1080 - picture.width) // 2, y + card.height + 24))
        elif beat["kind"] == "reaction":
            asset = ROOT / f"assets/shared/overlays/funny_originals/{beat['reaction']}/{beat['reaction']}.png"
            card = Image.open(asset).convert("RGBA").resize((840, 840), Image.Resampling.LANCZOS)
            im.alpha_composite(card, (120, 635))
        else:
            d.rounded_rectangle((60, 725, 960, 1310), radius=28, fill=paper)
            for n, line in enumerate(["Hỏi gu mặc áo.", "Bình luận thành album.", "Ai hiểu đề nhất?"]):
                d.text((98, 850 + n * 116), line, font=font(54), fill=ink)
        d.rounded_rectangle((60, 1620, 960, 1735), radius=13, fill=ink)
        d.text((80, 1640), "Nguồn bài: @nhinguyen_207", font=font(28), fill=paper)
        d.text((80, 1689), "Fluffing a Duck · Kevin MacLeod · CC BY 4.0", font=font(23), fill=paper)
        path = out / f"layout_{beat['id']}.png"
        im.save(path)
        results.append(path)
    return results


def voice_review_payload(folder: Path) -> dict:
    plan = read(folder / "merged_plan.json")
    manifest = read(folder / "voice_manifest.json")
    expected = cast_signature(plan, load_registry(get_settings()))
    if manifest["cast_choices"] != expected:
        raise ValidationError("Cast/script changed: rebuild the funny Threads audition", code="review_voice_stale")
    validate_files(manifest["input_files"])
    expected_beats = {str(i) for i, b in enumerate(plan["beats"]) if b.get("narration", "").strip()}
    if set(manifest["beats"]) != expected_beats:
        raise ValidationError("Missing comment speech", code="review_missing_voice")
    for key, asset in manifest["beats"].items():
        if sha(Path(asset["audio"])) != asset["sha256"] or sha(Path(asset["source"])) != asset["source_sha256"]:
            raise ValidationError("Speech cache changed", code="review_voice_stale")
        check = manifest.get("speech_checks", {}).get(key, {})
        if check.get("audio_sha256") != asset["sha256"] or check.get("status") != "ASR_CHECKED":
            raise ValidationError("Raw speech checks are missing or need repair", code="review_voice_stale")
        if any(x.get("evidence") == "MISSING_MARKER" for x in check.get("number_audit", {}).get("checks", [])):
            raise ValidationError("A critical spoken number marker is missing", code="review_number_check")
    files = [Path(x) for x in manifest["files"]] + [folder / "voice_manifest.json", folder / "CREDITS.txt"]
    files += sorted((folder / "work/previews").glob("*"))
    return {
        "script": digest(payload(folder, "script")),
        "voice_choices": expected,
        "files": [{"path": str(p.resolve()), "sha256": sha(p)} for p in files],
    }


def check_speech(folder: Path) -> dict:
    from ..core.speech_checks import audit_numbers
    from ..providers.align import faster_whisper_words

    manifest = read(folder / "voice_manifest.json")
    checks = {}

    def norm(s):
        return re.sub(r"[^\w]", "", s.lower())

    for key, asset in manifest["beats"].items():
        words = faster_whisper_words(
            Path(asset["audio"]), "vi", model="large-v3-turbo", device="cpu", compute_type="int8"
        )
        raw = " ".join(w.text for w in words)
        similarity = difflib.SequenceMatcher(None, norm(asset["text"]), norm(raw)).ratio()
        check = {
            "audio_sha256": asset["sha256"],
            "expected": asset["text"],
            "raw_transcript": raw,
            "model": "large-v3-turbo",
            "similarity": similarity,
            "status": "ASR_CHECKED" if similarity >= 0.87 else "NEEDS_REPAIR_OR_LISTENING",
            "human_listening": "PENDING",
            "number_audit": audit_numbers(asset["text"], words),
            "words": [{"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms} for w in words],
        }
        write(folder / f"work/speech_checks/funny_{key}.json", check)
        checks[key] = check
    manifest["speech_checks"] = checks
    write(folder / "voice_manifest.json", manifest)
    return checks


def render(folder: Path, output: Path) -> Path:
    folder = folder.resolve()
    require(folder, "voice")
    plan = read(folder / "merged_plan.json")
    timeline = read(folder / "funny_timeline.json")
    validate_files(timeline["inputs"])
    from ..core.creative_brief import reserve_render

    fingerprint = digest([timeline, sha(folder / "work/funny_voice/full_mix.wav"), VERSION])
    completed = read(output.with_suffix(".metadata.json"), {})
    if output.is_file() and completed.get("render_signature") == fingerprint and completed.get("sha256") == sha(output):
        return output
    budget = read(folder / "generation_budget.json", {"attempts": []})
    if not any(x.get("signature") == fingerprint for x in budget["attempts"]):
        reserve_render(folder, fingerprint)
    work = folder / "work/funny_render"
    work.mkdir(parents=True, exist_ok=True)
    clips = []
    for slot, beat in zip(timeline["slots"], plan["beats"], strict=True):
        overlay = folder / f"work/previews/layout_{beat['id']}.png"
        clip = work / f"{beat['id']}.mp4"
        key = digest([slot, sha(overlay), timeline["inputs"], VERSION])
        cache = read(clip.with_suffix(".json"), {})
        if not clip.is_file() or cache.get("key") != key or cache.get("sha256") != sha(clip):
            start = plan["background"]["start_seconds"] + slot["first_frame"] / FPS
            duration = slot["frames"] / FPS
            inputs = [
                "-ss",
                str(start),
                "-i",
                plan["background"]["path"],
                "-loop",
                "1",
                "-framerate",
                "30",
                "-i",
                str(overlay),
            ]
            brightness = 1 - float(plan["background"].get("darken", 0.2))
            vf = (
                "[0:v]scale=1080:1920:flags=lanczos,setsar=1,fps=30,eq=saturation=0.85,"
                f"colorchannelmixer=rr={brightness}:gg={brightness}:bb={brightness}[bg];"
                "[bg][1:v]overlay=0:0:shortest=1[v]"
            )
            # Animated reactions replace their still area; source screenshots never shake/zoom.
            if beat["kind"] == "reaction":
                asset = ROOT / f"assets/shared/overlays/funny_originals/{beat['reaction']}/{beat['reaction']}.mp4"
                inputs += ["-i", str(asset)]
                vf = vf.replace("[v]", "[base]") + ";[2:v]scale=840:840[cat];[base][cat]overlay=120:635:shortest=1[v]"
            run_ffmpeg(
                [
                    *inputs,
                    "-filter_complex",
                    vf,
                    "-map",
                    "[v]",
                    "-t",
                    str(duration),
                    "-frames:v",
                    str(slot["frames"]),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-threads",
                    "4",
                    "-crf",
                    "19",
                    "-pix_fmt",
                    "yuv420p",
                    str(clip),
                ],
                stage="funny_scene",
            )
            write(clip.with_suffix(".json"), {"key": key, "sha256": sha(clip)})
        clips.append(clip)
    listing = work / "concat.txt"
    listing.write_text("\n".join(f"file '{x.as_posix()}'" for x in clips), encoding="utf-8")
    visual = work / "continuous.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(visual)], stage="funny_concat")
    a, b = timeline["cover_frames"]
    draft = work / "draft.mp4"
    run_ffmpeg(
        [
            "-i",
            str(visual),
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(folder / "cover_preview.png"),
            "-i",
            str(folder / "work/funny_voice/full_mix.wav"),
            "-filter_complex",
            f"[0:v][1:v]overlay=0:0:enable='between(n,{a},{b - 1})':shortest=1[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-frames:v",
            str(timeline["total_frames"]),
            "-t",
            str(timeline["duration"]),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-threads",
            "4",
            "-crf",
            "19",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(draft),
        ],
        stage="funny_cover",
    )
    verify_cover(draft, folder / "cover_preview.png", timeline)
    result = publish(draft, output, {"video": {"width": 1080, "height": 1920}})
    verify_cover(result, folder / "cover_preview.png", timeline)
    shutil.copy2(folder / "cover_preview.png", result.with_suffix(".cover.png"))
    shutil.copy2(folder / "CREDITS.txt", result.with_suffix(".credits.txt"))
    from ..core.creative_brief import finish_render

    finish_render(folder, True)
    write(folder / "native_render_cache.json", {"outputs": [{"path": str(result), "sha256": sha(result)}]})
    write(
        result.with_suffix(".metadata.json"),
        {
            "mode": "funny_threads",
            "version": VERSION,
            "render_signature": fingerprint,
            "sha256": sha(result),
            "cover_frame_start": a,
            "cover_frame_end_exclusive": b,
            "cover_seconds": 0.1,
            "narration_speeds_applied_once": {b["id"]: b["speed"] for b in plan["beats"] if b.get("narration")},
            "source_provenance": plan["source"],
            "editorial": "PENDING_USER_REVIEW",
        },
    )
    return result


def verify_cover(video: Path, cover: Path, timeline: dict) -> dict:
    """Decode both neighboring frames as well as the exact three-frame insert."""
    start, end = timeline["cover_frames"]
    work = video.parent / "_cover_check" / video.stem
    work.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(video),
            "-vf",
            f"select='between(n,{start - 1},{end})'",
            "-fps_mode",
            "vfr",
            "-frames:v",
            "5",
            str(work / "%02d.png"),
        ],
        stage="funny_cover_check",
    )
    images = sorted(work.glob("*.png"))
    if len(images) != 5:
        raise ValueError("Cover check needs the three insert frames and both adjacent frames")
    # Header coordinates distinguish the standalone cover from the normal layout.
    region = (30, 280, 1010, 620)
    target = np.asarray(Image.open(cover).convert("RGB").crop(region), dtype=float)
    distances = [
        float(np.mean(np.abs(np.asarray(Image.open(p).convert("RGB").crop(region), dtype=float) - target)))
        for p in images
    ]
    matched = [d < 8 for d in distances]
    if matched != [False, True, True, True, False]:
        raise ValueError(f"Cover occupies the wrong decoded frames: {matched}")
    actual_frames = int(next(s["nb_frames"] for s in probe(video).raw["streams"] if s.get("codec_type") == "video"))
    if actual_frames != timeline["total_frames"]:
        raise ValueError("Cover insertion changed the video duration")
    report = {
        "status": "PASS",
        "first_frame": start,
        "end_frame_exclusive": end,
        "seconds": 0.1,
        "decoded_matches": matched,
        "mean_absolute_errors": distances,
        "total_frames": actual_frames,
    }
    write(video.with_suffix(".cover_check.json"), report)
    return report
