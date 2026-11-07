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
from .funny_edit import load_edit, make_cover, make_layouts, reaction_geometry
from .quality import publish

FPS = 30
VERSION = "funny-threads-multicast-1"
ROOT = Path(__file__).resolve().parents[3]
VOICE_IDS = {
    "Ngọc Huyền": "vieneu-gallery-ngoc-huyen",
    "Mỹ Duyên": "vieneu-gallery-my-duyen",
    "Quang Sơn": "vieneu-gallery-quang-son",
    "Minh Đức": "vieneu-gallery-minh-duc",
    "Ngọc Trân": "vieneu-gallery-ngoc-tran",
    "Hải Đăng": "vieneu-gallery-hai-dang",
}


def cover_window(total_frames: int, duration_frames: int = 3) -> tuple[int, int]:
    if type(total_frames) is not int or type(duration_frames) is not int or total_frames < 9 or duration_frames != 3:
        raise ValueError("The requested one-tenth-second cover must occupy exactly three frames at 30 fps")
    start = total_frames // 2
    return start, start + duration_frames  # half-open: never four frames


def cover_in_pause(slots, total):
    candidates = []
    for left, right in zip(slots[:-1], slots[1:], strict=True):
        end = right["first_frame"]
        if not 0.35 * total <= end <= 0.65 * total or not (left["audio"] and right["audio"]):
            continue
        speech_end = left["first_frame"] + math.ceil(probe(Path(left["audio"])).duration * FPS)
        if speech_end <= end - 3:
            candidates.append(end - 3)
    if not candidates:
        return cover_window(total)
    start = min(candidates, key=lambda frame: abs(frame - total // 2))
    return start, start + 3


def compose_cover(visual: Path, cover: Path, audio: Path, draft: Path, timeline: dict) -> None:
    """Encode explicit frame ranges, then join without framesync or timestamp drift."""
    start, end = timeline["cover_frames"]
    if end - start != 3:
        raise ValueError("The cover replacement must span exactly three frames")
    work = draft.parent / "cover_parts"
    work.mkdir(parents=True, exist_ok=True)
    parts = []
    ranges = [("pre", 0, start), ("cover", 0, 3), ("post", end, timeline["total_frames"])]
    for name, first, last in ranges:
        part = work / f"{name}.mp4"
        source = cover if name == "cover" else visual
        key = digest([sha(source), first, last, "explicit-cover-parts-2-bt709"])
        old = read(part.with_suffix(".json"), {})
        if not part.is_file() or old.get("key") != key or old.get("sha256") != sha(part):
            inputs = ["-loop", "1", "-framerate", "30", "-i", str(source)] if name == "cover" else ["-i", str(source)]
            vf = f"trim=start_frame={first}:end_frame={last},setpts=PTS-STARTPTS,setsar=1"
            if name == "cover":
                vf += ",scale=out_color_matrix=bt709:out_range=tv"
            run_ffmpeg(
                [
                    *inputs,
                    "-vf",
                    vf,
                    "-frames:v",
                    str(last - first),
                    "-r",
                    "30",
                    "-fps_mode",
                    "cfr",
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
                    "-colorspace",
                    "bt709",
                    "-color_trc",
                    "bt709",
                    "-color_primaries",
                    "bt709",
                    "-color_range",
                    "tv",
                    str(part),
                ],
                stage="funny_cover_part",
            )
            count = int(next(s["nb_frames"] for s in probe(part).raw["streams"] if s.get("codec_type") == "video"))
            if count != last - first:
                raise ValueError("An explicit cover range lost video frames")
            write(part.with_suffix(".json"), {"key": key, "sha256": sha(part)})
        parts.append(part)
    listing = work / "concat.txt"
    listing.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in parts), encoding="utf-8")
    run_ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            str(timeline["duration"]),
            str(draft),
        ],
        stage="funny_cover_join",
    )


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


def revised_cast(plan, edit):
    overrides = (edit or {}).get("voice_overrides", {})
    if not overrides:
        return plan, set()
    names = {beat["voice"] for beat in plan["beats"] if beat.get("narration")}
    if set(overrides) - names:
        raise ValueError("Replace an existing speaking voice")
    for replacement in overrides.values():
        if set(replacement) != {"voice", "region", "gender"} or replacement["voice"] not in VOICE_IDS:
            raise ValueError("A replacement must name a registered voice, region and gender")
    replaced = {beat["id"] for beat in plan["beats"] if beat.get("voice") in overrides}
    return {**plan, "beats": [{**beat, **overrides.get(beat.get("voice"), {})} for beat in plan["beats"]]}, replaced


def validate_files(files: list[dict]) -> None:
    for entry in files:
        if sha(Path(entry["path"])) != entry["sha256"]:
            raise ValidationError(f"Changed funny Threads input: {entry['path']}", code="review_voice_stale")


def snapshot(folder: Path, plan: dict, edit: dict | None = None) -> list[dict]:
    root = ROOT / "assets"
    if not edit and any(b["kind"] == "reaction" for b in plan["beats"]):
        raise ValueError(
            "Chọn ảnh/clip thật trong kho funny_threads bằng funny_edit.json trước khi dựng."
        )
    music = next(x for x in read(root / "shared/music/library.json")["tracks"] if x["id"] == plan["music_id"])
    if not music.get("production_eligible"):
        raise ValueError("Music is a reference/preview, not an eligible production asset")
    paths = [Path(plan["background"]["path"]), folder / "cover_preview.png"]
    validate_files(list(plan["source"]["crops"].values()))
    paths += [Path(x["path"]) for x in plan["source"]["crops"].values()]
    music_path = root / music["path"]
    if sha(music_path) != music["sha256"]:
        raise ValueError("Changed comedy music asset")
    paths.append(music_path)
    if edit:
        paths += [folder / "funny_edit.json", *(Path(x["path"]) for x in edit["assets"].values())]
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


def repair_source(beat: dict, profile, repair: dict) -> Path:
    """A checked take must survive resume, bound to the exact script and voice."""
    if (
        repair.get("text_sha256") != hashlib.sha256(beat["narration"].encode()).hexdigest()
        or repair.get("voice_signature") != signature(profile)
        or repair.get("speed") != beat["speed"]
    ):
        raise ValidationError("Speech repair no longer matches the script/voice", code="review_voice_stale")

    def lexical(text):
        return re.findall(r"\w+", text.casefold())

    if lexical(repair.get("tts_input", "")) != lexical(beat["narration"]):
        raise ValidationError("A technical take may change punctuation, not approved words", code="review_voice_stale")
    source = Path(repair["path"])
    validate_files([{"path": str(source), "sha256": repair["sha256"]}])
    return source


def prepare_voice(folder: Path, *, reuse_checked: bool = False) -> dict:
    """Quarantined project audition only, after the creator's script acceptance."""
    folder = folder.resolve()
    require(folder, "script")
    plan = read(folder / "merged_plan.json")
    edit = load_edit(folder, plan)
    plan, replaced = revised_cast(plan, edit)
    registry = load_registry(get_settings())
    choices = cast_signature(plan, registry)
    if reuse_checked and not edit:
        raise ValueError("Prepare funny_edit.json before reusing the checked speech")
    if edit:
        validate_files(list(plan["source"]["crops"].values()))
    else:
        inputs = snapshot(folder, plan)
    work = folder / "work/funny_voice"
    work.mkdir(parents=True, exist_ok=True)
    previous = read(folder / "voice_manifest.json", {})
    if reuse_checked:
        _checked_speech(plan, previous, choices)
    repairs = read(folder / "voice_repairs.json", {}).get("selected", {})
    assets, files, slots = {}, [], []
    cursor = 0
    for i, beat in enumerate(plan["beats"]):
        narration = beat.get("narration", "").strip()
        audio = None
        if narration and reuse_checked:
            take = previous["beats"][str(i)]
            audio, native = Path(take["audio"]), Path(take["source"])
            profile = registry.get(VOICE_IDS[beat["voice"]])
        elif narration:
            profile = with_speed(registry.get(VOICE_IDS[beat["voice"]]), beat["speed"])
            key = digest([narration, signature(profile), profile.params, VERSION])
            native = work / f"{beat['id']}_{key[:12]}.wav"
            cached = read(native.with_suffix(".cache.json"), {})
            repair = repairs.get(beat["id"], {})
            if repair and (beat["id"] not in replaced or repair.get("voice_signature") == signature(profile)):
                native = repair_source(beat, registry.get(VOICE_IDS[beat["voice"]]), repair)
                write(
                    native.with_suffix(".cache.json"),
                    {"sha256": sha(native), "key": key, "selected_repair": True, "human_listening": "PENDING"},
                )
            elif not native.is_file() or cached.get("sha256") != sha(native):
                # An audition does not admit a voice globally or consume a production fallback.
                get_provider(profile.provider, registry).audition(narration, profile, native)
                write(
                    native.with_suffix(".cache.json"), {"sha256": sha(native), "key": key, "human_listening": "PENDING"}
                )
            audio = work / f"{beat['id']}_pcm.wav"
            run_ffmpeg(
                ["-i", str(native), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(audio)], stage="funny_pcm"
            )
        if narration:
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
    cover_frames = cover_in_pause(slots, cursor) if edit and edit.get("transition_frames") else cover_window(cursor)
    timeline = {
        "fps": FPS,
        "total_frames": cursor,
        "duration": cursor / FPS,
        "slots": slots,
        "cover_frames": cover_frames,
        "cast_choices": choices,
    }
    if edit:
        make_cover(folder, plan, edit, timeline)
        inputs = snapshot(folder, plan, edit)
    timeline["inputs"] = inputs
    write(folder / "funny_timeline.json", timeline)
    mixed = mix(folder, plan, timeline, edit)
    files += [mixed, folder / "funny_timeline.json"]
    if (folder / "voice_repairs.json").is_file():
        files.append(folder / "voice_repairs.json")
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


def mix(folder: Path, plan: dict, timeline: dict, edit: dict | None = None) -> Path:
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
    if edit:
        for slot in timeline["slots"]:
            cue = edit["reactions"].get(slot["beat"], {})
            if not cue.get("sound_id"):
                continue
            asset = edit["assets"][cue["sound_id"]]
            pcm = work / f"sfx_{slot['beat']}.wav"
            run_ffmpeg(
                ["-i", asset["path"], "-t", str(slot["frames"] / FPS), "-ar", "48000", "-ac", "2", str(pcm)],
                stage="funny_sfx",
            )
            samples = _pcm(pcm)[: slot["frames"] * 1600]
            samples *= min(0.038 / _rms(samples), 0.25 / max(np.max(np.abs(samples)), 1e-6))
            tail = min(len(samples), 3840)
            samples[-tail:] *= np.linspace(1, 0, tail)[:, None]
            start = slot["first_frame"] * 1600
            result[start : start + len(samples)] += samples
    out = work / "full_mix.wav"
    _write_pcm(out, result)
    source = plan["source"]
    source_credit = f"Source screenshots: @{source['author']} and visible commenters"
    reference = source.get("url") or source.get("reference_creator_credit")
    if reference:
        source_credit += f" — {reference}"
    (folder / "CREDITS.txt").write_text(
        f"{track['attribution']}\n{source_credit}\n",
        encoding="utf-8",
    )
    if edit:
        with (folder / "CREDITS.txt").open("a", encoding="utf-8") as credits:
            for item in edit["assets"].values():
                credits.write(f"{item['name']} — {item['source_url']}\n")
    return out


def layouts(folder: Path) -> list[Path]:
    plan = read(folder / "merged_plan.json")
    out = folder / "work/previews"
    out.mkdir(parents=True, exist_ok=True)
    edit = load_edit(folder, plan)
    if edit:
        return make_layouts(plan, edit, out)
    if any(b["kind"] == "reaction" for b in plan["beats"]):
        raise ValueError("Chọn phản ứng thật trong funny_edit.json để xem bố cục.")
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


def _checked_speech(plan: dict, manifest: dict, expected: dict) -> None:
    if manifest.get("cast_choices") != expected:
        raise ValidationError("Cast/script changed: rebuild the funny Threads audition", code="review_voice_stale")
    expected_beats = {str(i) for i, b in enumerate(plan["beats"]) if b.get("narration", "").strip()}
    if set(manifest["beats"]) != expected_beats:
        raise ValidationError("Missing comment speech", code="review_missing_voice")
    for key, asset in manifest["beats"].items():
        if sha(Path(asset["audio"])) != asset["sha256"] or sha(Path(asset["source"])) != asset["source_sha256"]:
            raise ValidationError("Speech cache changed", code="review_voice_stale")
        check = manifest.get("speech_checks", {}).get(key, {})
        if check.get("audio_sha256") != asset["sha256"] or check.get("status") != "ASR_CHECKED":
            raise ValidationError("Raw speech checks are missing or need repair", code="review_voice_stale")
        if check.get("context_source"):
            validate_files([{"path": check["context_source"], "sha256": check["context_sha256"]}])
        if any(x.get("evidence") == "MISSING_MARKER" for x in check.get("number_audit", {}).get("checks", [])):
            raise ValidationError("A critical spoken number marker is missing", code="review_number_check")


def voice_review_payload(folder: Path) -> dict:
    plan = read(folder / "merged_plan.json")
    plan, _ = revised_cast(plan, read(folder / "funny_edit.json", {}))
    manifest = read(folder / "voice_manifest.json")
    expected = cast_signature(plan, load_registry(get_settings()))
    validate_files(manifest["input_files"])
    _checked_speech(plan, manifest, expected)
    files = [Path(x) for x in manifest["files"]] + [folder / "voice_manifest.json", folder / "CREDITS.txt"]
    files += sorted((folder / "work/previews").glob("*"))
    return {
        "script": digest(payload(folder, "script")),
        "voice_choices": expected,
        "files": [{"path": str(p.resolve()), "sha256": sha(p)} for p in files],
    }


def check_speech(folder: Path, *, model: str = "large-v3-turbo", beats: set[str] | None = None) -> dict:
    from ..core.speech_checks import audit_numbers
    from ..providers.align import faster_whisper_words

    repositories = {
        "large-v3-turbo": "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
        "large-v3": "models--Systran--faster-whisper-large-v3",
    }
    if model not in repositories:
        raise ValueError("Use a supported Vietnamese ASR model")
    # Reuse the installed worker cache, including model-only snapshots. The current
    # HF client can reject an otherwise usable snapshot because its README is absent.
    import os

    hf_home = Path(os.environ.get("HF_HOME") or get_settings().get("tts.vieneu.hf_home") or "D:/studio-node/hf")
    cached = sorted((hf_home / "hub" / repositories[model] / "snapshots").glob("*/model.bin"))
    model_path = str(cached[-1].parent) if cached else model
    manifest = read(folder / "voice_manifest.json")
    plan = read(folder / "merged_plan.json")
    plan, replaced = revised_cast(plan, read(folder / "funny_edit.json", {}))
    repairs = read(folder / "voice_repairs.json", {}).get("selected", {})
    checks = dict(manifest.get("speech_checks", {})) if beats is not None else {}

    def norm(s):
        return re.sub(r"[^\w]", "", s.lower())

    for key, asset in manifest["beats"].items():
        beat_id = plan["beats"][int(key)]["id"]
        if beats is not None and beat_id not in beats:
            continue
        previous = manifest.get("speech_checks", {}).get(key, {})
        if (
            replaced and (beat_id not in replaced or previous.get("model") == model)
            and previous.get("status") == "ASR_CHECKED"
            and previous.get("audio_sha256") == sha(Path(asset["audio"])) == asset["sha256"]
        ):
            checks[key] = previous
            continue
        repair = repairs.get(beat_id, {})
        if beat_id in replaced and repair.get("sha256") != asset.get("source_sha256"):
            repair = {}
        recognition_audio = Path(asset["audio"])
        scope = {}
        if repair.get("full_context_audio"):
            context = Path(repair["full_context_audio"])
            validate_files([{"path": str(context), "sha256": repair["full_context_sha256"]}])
            with wave.open(str(context), "rb") as wav:
                params = wav.getparams()
                raw_context = wav.readframes(params.nframes)
            with wave.open(asset["source"], "rb") as wav:
                if wav.getparams()[:3] != params[:3]:
                    raise ValueError("Context crop changed PCM encoding")
                raw_target = wav.readframes(wav.getnframes())
            offset = repair["crop_start_sample"] * params.sampwidth * params.nchannels
            if raw_target != raw_context[offset:]:
                raise ValueError("Context speech evidence does not reconstruct the selected PCM")
            recognition_audio = context
            scope = {
                "recognition_scope": "Exact target window of full-context source PCM",
                "context_source": str(context),
                "context_sha256": sha(context),
                "crop_start_seconds": repair["crop_start_sample"] / params.framerate,
                "lossless_crop_verified": True,
            }
        words = faster_whisper_words(recognition_audio, "vi", model=model_path, device="cpu", compute_type="int8")
        if scope:
            from ..core.subtitles import Word

            scope["raw_context_transcript"] = " ".join(w.text for w in words)
            cut_ms = round(scope["crop_start_seconds"] * 1000)
            words = [
                Word(w.text, max(0, w.start_ms - cut_ms), w.end_ms - cut_ms) for w in words if w.end_ms > cut_ms
            ]
            previous = manifest.get("speech_checks", {}).get(key, {})
            if previous.get("audio_sha256") == asset["sha256"]:
                scope["alternate_raw_transcript"] = previous.get("raw_transcript", "")
            scope["human_listening_note"] = (
                "A very short Central utterance has inconsistent ASR spelling of its final address term. "
                "Preserve raw hypotheses; the creator waived separate listening and reviews the actual final mix."
            )
        raw = " ".join(w.text for w in words)
        similarity = difflib.SequenceMatcher(None, norm(asset["text"]), norm(raw)).ratio()
        check = {
            "audio_sha256": asset["sha256"],
            "expected": asset["text"],
            "raw_transcript": raw,
            "model": model,
            "model_snapshot": model_path,
            "similarity": similarity,
            "status": "ASR_CHECKED" if similarity >= 0.87 else "NEEDS_REPAIR_OR_LISTENING",
            "human_listening": "PENDING",
            "number_audit": audit_numbers(asset["text"], words),
            "words": [{"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms} for w in words],
            **scope,
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
    edit = load_edit(folder, plan)
    plan, _ = revised_cast(plan, edit)
    timeline = read(folder / "funny_timeline.json")
    validate_files(timeline["inputs"])
    from ..core.creative_brief import reserve_render

    overlays = [folder / f"work/previews/layout_{b['id']}.png" for b in plan["beats"]]
    overlay_hashes = [sha(p) for p in overlays]
    fingerprint = digest([timeline, sha(folder / "work/funny_voice/full_mix.wav"), overlay_hashes, VERSION])
    completed = read(output.with_suffix(".metadata.json"), {})
    if output.is_file() and completed.get("render_signature") == fingerprint and completed.get("sha256") == sha(output):
        return output
    budget = read(folder / "generation_budget.json", {"attempts": []})
    if not any(x.get("signature") == fingerprint for x in budget["attempts"]):
        reserve_render(folder, fingerprint)
    work = folder / "work/funny_render"
    work.mkdir(parents=True, exist_ok=True)
    clips = []
    for index, (slot, beat, overlay) in enumerate(zip(timeline["slots"], plan["beats"], overlays, strict=True)):
        clip = work / f"{beat['id']}.mp4"
        fade = min((edit or {}).get("transition_frames", 0), (slot["frames"] - 1) // 2)
        fades = []
        if fade and index and overlay_hashes[index - 1] != overlay_hashes[index]:
            fades.append(f"fade=t=in:s=0:n={fade}:alpha=1")
        if fade and index + 1 < len(overlays) and overlay_hashes[index + 1] != overlay_hashes[index]:
            fades.append(f"fade=t=out:s={slot['frames'] - fade - 1}:n={fade}:alpha=1")
        key = digest([slot, overlay_hashes[index], timeline["inputs"], fades, VERSION])
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
            card = "[1:v]format=rgba," + ",".join(fades) + "[card];" if fades else ""
            card_input = "[card]" if fades else "[1:v]"
            vf = (
                "[0:v]scale=1080:1920:flags=lanczos,setsar=1,fps=30,eq=saturation=0.85,"
                f"colorchannelmixer=rr={brightness}:gg={brightness}:bb={brightness}[bg];"
                f"{card}[bg]{card_input}overlay=0:0:shortest=1[v]"
            )
            cue = edit["reactions"].get(beat["id"], {}) if edit else {}
            if cue.get("video_id"):
                asset = edit["assets"][cue["video_id"]]
                x, y, width, height = reaction_geometry(asset, plan, cue["source_crop"])
                inputs += ["-ss", str(cue.get("start_seconds", 0)), "-i", asset["path"]]
                ease = (
                    ",format=rgba,fade=t=in:s=0:n=3:alpha=1,"
                    f"fade=t=out:s={slot['frames'] - 4}:n=3:alpha=1" if fade and slot["frames"] >= 8 else ""
                )
                vf = (
                    vf.replace("[v]", "[base]")
                    + f";[2:v]crop=iw:min(ih\\,iw):0:0,scale={width}:{height}:flags=lanczos,setsar=1{ease}[reaction];"
                    + f"[base][reaction]overlay={x}:{y}[v]"
                )
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
                    "-colorspace",
                    "bt709",
                    "-color_trc",
                    "bt709",
                    "-color_primaries",
                    "bt709",
                    "-color_range",
                    "tv",
                    str(clip),
                ],
                stage="funny_scene",
            )
            write(clip.with_suffix(".json"), {"key": key, "sha256": sha(clip)})
        clips.append(clip)
    # Overlaying an untagged reaction can erase its matrix tag. Concatenating
    # these SPS variants makes FFmpeg reset frame-based filters at every change.
    for clip in clips:
        stream = next(s for s in probe(clip).raw["streams"] if s.get("codec_type") == "video")
        if stream.get("color_space") != "bt709":
            normalized = clip.with_name(clip.stem + ".color-normalized.mp4")
            run_ffmpeg(
                [
                    "-i",
                    str(clip),
                    "-map",
                    "0:v:0",
                    "-c:v",
                    "copy",
                    "-bsf:v",
                    "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0",
                    str(normalized),
                ],
                stage="funny_color_metadata",
            )
            normalized.replace(clip)
            cache = read(clip.with_suffix(".json"))
            cache.update(sha256=sha(clip), color_metadata="bt709")
            write(clip.with_suffix(".json"), cache)
    listing = work / "concat.txt"
    listing.write_text("\n".join(f"file '{x.as_posix()}'" for x in clips), encoding="utf-8")
    visual = work / "continuous.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(visual)], stage="funny_concat")
    a, b = timeline["cover_frames"]
    draft = work / "draft.mp4"
    compose_cover(visual, folder / "cover_preview.png", folder / "work/funny_voice/full_mix.wav", draft, timeline)
    verify_cover(draft, folder / "cover_preview.png", timeline)
    result = publish(draft, output, {"video": {"width": 1080, "height": 1920}})
    verify_cover(result, folder / "cover_preview.png", timeline)
    shutil.copy2(folder / "cover_preview.png", result.with_suffix(".cover.png"))
    shutil.copy2(folder / "CREDITS.txt", result.with_suffix(".credits.txt"))
    from ..core.creative_brief import finish_render

    finish_render(folder, True, [str(result)])
    write(folder / "native_render_cache.json", {"outputs": [{"path": str(result), "sha256": sha(result)}]})
    write(
        result.with_suffix(".metadata.json"),
        {
            "mode": "funny_threads",
            "title": plan["title"],
            "version": VERSION,
            "render_signature": fingerprint,
            "sha256": sha(result),
            "cover_frame_start": a,
            "cover_frame_end_exclusive": b,
            "cover_seconds": 0.1,
            "narration_speeds_applied_once": {b["id"]: b["speed"] for b in plan["beats"] if b.get("narration")},
            "source_provenance": plan["source"],
            "edit_revision": edit["revision"] if edit else None,
            "reaction_assets": list(edit["assets"].values()) if edit else [],
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
