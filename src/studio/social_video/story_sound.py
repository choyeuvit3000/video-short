"""Pinned horror beds and restrained, speech-anchored SFX with measured levels."""

import json
import math
import random
import re
from pathlib import Path

from ..core.errors import ManualGateRequired
from ..core.ffmpeg import run_ffmpeg
from ..core.subtitles import load_words
from . import horrormusic
from .quality import sha256
from .util import ASSETS, ffmpeg, read_json, run, write_json

SFX = {
    "hook": "horror-stinger-54.mp3",
    "laugh": "distant_laugh.wav",
    "footsteps": "footsteps-concrete-64.mp3",
    "door": "door-creak-13.mp3",
    "whisper": "horror-wind-whisper-56.mp3",
}
RULES = [
    ("laugh", r"cười|khúc khích"),
    ("footsteps", r"tiếng chân|bước chân|kéo lê"),
    ("door", r"gõ cửa|cửa kêu|cửa mở"),
    ("whisper", r"thì thào|tiếng ru|tiếng gió"),
]


def _asset(path):
    if not path.is_file():
        raise ManualGateRequired("horror_assets", f"Thiếu asset kinh dị: {path.name}; bổ sung kho trước khi dựng.")
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def prepare_plan(folder, cfg):
    m = read_json(folder / "voice_manifest.json", {})
    body = m["body"]
    vi = read_json(folder / "vi.json")
    from .reddit import chunks

    texts = [s for g in chunks(vi["paragraphs"]) for s in g]
    parts = read_json(folder / "part_plan.json")["parts"]
    rng = random.Random(folder.name + "-horror-bed-v2")
    tracks = horrormusic.ensure(1)
    result = {"version": 2, "assets": [], "parts": {}, "speech_sha256": [sha256(Path(x["path"])) for x in body]}
    all_parts = parts + [{"part": "full", "sentences": list(range(len(body)))}]
    for part in all_parts:
        key = str(part["part"])
        music = _asset(rng.choice(tracks))
        result["assets"].append(music)
        events = []
        cursor = 0.0
        if key != "full":
            hook = m.get("hooks", [])[int(key) - 1]
            cursor = hook["seconds"] if hook else 0
        if cfg["reddit"].get("story_sfx_enabled", True) and not vi.get("sensitive"):
            events.append({"kind": "hook", "at": 0, "duration": 0.65, "relative_db": -22})
        for idx in part["sentences"]:
            if cfg["reddit"].get("story_sfx_enabled", True) and not vi.get("sensitive"):
                for kind, pattern in RULES:
                    match = re.search(pattern, texts[idx], re.I)
                    if not match or any(e["kind"] == kind for e in events):
                        continue
                    words, _source = load_words(Path(m["timing_files"][idx]))
                    word_index = len(texts[idx][: match.start()].split())
                    at = cursor + words[min(word_index, len(words) - 1)].start_ms / 1000
                    events.append({"kind": kind, "at": round(at, 3), "duration": 1.15, "relative_db": -26})
            cursor += body[idx]["seconds"]
        events = sorted(events, key=lambda e: (e["kind"] != "hook", e["kind"] != "laugh", e["at"]))[:4]
        for event in events:
            asset = _asset(ASSETS / "horror_sfx" / SFX[event["kind"]])
            event.update(asset)
            result["assets"].append(asset)
        result["parts"][key] = {
            "music": music,
            "music_start": rng.uniform(7, 20),
            "relative_music_db": float(cfg["reddit"].get("music_relative_db", -23)),
            "events": sorted(events, key=lambda e: e["at"]),
        }
    write_json(folder / "sound_plan.json", result)
    return result


def loudness(path):
    result = run([ffmpeg(), "-v", "info", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    reports = re.findall(r'\{\s*"input_i".*?\}', result.stderr, re.S)
    level = float(json.loads(reports[-1])["input_i"]) if reports else float("-inf")
    if not math.isfinite(level):
        raise ValueError(f"Silent or unmeasurable audio: {path}")
    return level


def mix(folder, part, narration, output, seconds):
    plan = read_json(folder / "sound_plan.json", {})
    selected = plan.get("parts", {}).get(str(part))
    if not selected:
        raise ManualGateRequired("story_sound", "Chuẩn bị nhạc và SFX cùng gói duyệt giọng trước khi dựng.")
    body = read_json(folder / "voice_manifest.json", {}).get("body", [])
    if plan.get("speech_sha256") != [sha256(Path(x["path"])) for x in body]:
        raise ManualGateRequired("story_sound", "Lời đọc đã đổi; chuẩn bị lại các mốc SFX trước khi dựng.")
    for asset in plan["assets"]:
        if sha256(Path(asset["path"])) != asset["sha256"]:
            raise ManualGateRequired("story_sound", "Asset nhạc/SFX đã đổi; chuẩn bị lại gói nghe.")
    voice_i = loudness(narration)
    music_i = loudness(Path(selected["music"]["path"]))
    gain = voice_i + selected["relative_music_db"] - music_i
    args = [
        "-i",
        str(narration),
        "-stream_loop",
        "-1",
        "-ss",
        str(selected["music_start"]),
        "-i",
        selected["music"]["path"],
    ]
    filters = [
        f"[1:a]volume={gain:.3f}dB,afade=t=in:d=0.8,afade=t=out:st={max(0, seconds - 1):.3f}:d=1[mus]",
        "[0:a]asplit=2[nar][key]",
        "[mus][key]sidechaincompress=threshold=0.03:ratio=2:attack=40:release=350[bed]",
    ]
    labels = ["[nar]", "[bed]"]
    cue_levels = []
    for i, event in enumerate(selected["events"], 2):
        args += ["-i", event["path"]]
        event_gain = voice_i + event["relative_db"] - loudness(Path(event["path"]))
        name = f"fx{i}"
        filters.append(
            f"[{i}:a]atrim=0:{event['duration']},asetpts=PTS-STARTPTS,highpass=f=120,lowpass=f=3500,"
            f"afade=t=in:d=0.04,afade=t=out:st={event['duration'] - 0.16}:d=0.16,"
            f"volume={event_gain:.3f}dB,adelay={round(event['at'] * 1000)}:all=1[{name}]"
        )
        labels.append(f"[{name}]")
        cue_levels.append({**event, "applied_gain_db": event_gain})
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0[a]")
    run_ffmpeg(
        [
            *args,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[a]",
            "-t",
            str(seconds),
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
        stage="horror-mix",
    )
    report = {
        "voice_i": voice_i,
        "music_source_i": music_i,
        "music_gain_db": gain,
        "music_relative_db_before_duck": selected["relative_music_db"],
        "events": cue_levels,
        "voice_preserved_at_unity": True,
        "dry_voice_only": False,
        "output_sha256": sha256(output),
    }
    write_json(folder / f"{part}_mix_report.json", report)
    return output
