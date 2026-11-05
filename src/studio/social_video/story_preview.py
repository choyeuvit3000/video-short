"""Checkpoint two: full mixed audio and a short preview from the exact frozen assets."""

import random
from pathlib import Path

from PIL import Image, ImageOps

from ..core.ffmpeg import run_ffmpeg
from ..core.subtitles import load_words
from . import bgclips
from .reddit import _join
from .story_cards import timed_cards
from .story_sound import mix
from .util import media_duration, read_json


def prepare_previews(folder, cfg):
    manifest = read_json(folder / "voice_manifest.json")
    plan = read_json(folder / "part_plan.json")["parts"]
    story = read_json(folder / "source.json", {})
    vi = read_json(folder / "vi.json", {})
    from .reddit import SEAM, chunks
    from .story_scenes import photo

    paragraph_of = [
        pi for pi, text in enumerate(vi.get("paragraphs", [])) for group in chunks([text]) for sentence in group
    ]
    work = folder / "work/previews"
    work.mkdir(parents=True, exist_ok=True)
    outputs = []
    for part in plan:
        key = part["part"]
        hook = manifest["hooks"][key - 1]
        ending = manifest.get("endings", [None] * len(plan))[key - 1]
        body = [manifest["body"][i] for i in part["sentences"]]
        clips = ([hook] if hook else []) + body + ([ending] if ending else [])
        narration = work / f"part{key}_narration.wav"
        _join([Path(item["path"]) for item in clips], narration, 0.35)
        seconds = media_duration(narration)
        mixed = work / f"part{key}_full_mix.wav"
        mix(folder, key, narration, mixed, seconds)
        # Visual preview starts at the first body sentence, with the matching audio offset.
        offset = hook["seconds"] if hook else 0
        lines, elapsed, last = [], 0, None
        for index in part["sentences"]:
            words, origin = load_words(Path(manifest["timing_files"][index]))
            if origin not in ("faster_whisper", "manual"):
                raise ValueError("Preview requires actual speech anchors")
            duration = manifest["body"][index]["seconds"]
            for frame, share in timed_cards(story, words, duration, work / "cards", f"p{key}s{index}"):
                picture = photo(folder, paragraph_of[index]) if vi.get("scenes") else None
                if picture:
                    backdrop = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
                    backdrop.paste(ImageOps.fit(Image.open(picture).convert("RGB"), (1080, SEAM)), (0, 0))
                    Image.alpha_composite(backdrop, Image.open(frame).convert("RGBA")).save(frame)
                last = frame
                lines += [f"file '{frame.resolve().as_posix()}'", f"duration {duration * share:.6f}"]
            elapsed += duration
            if elapsed >= 12:
                break
        if last is None:
            raise ValueError("No story body in preview")
        lines.append(f"file '{last.resolve().as_posix()}'")
        concat = work / f"part{key}_cards.txt"
        concat.write_text("ffconcat version 1.0\n" + "\n".join(lines) + "\n", encoding="utf-8")
        source, start, crop = bgclips.planned(
            folder,
            key,
            seconds,
            random.Random(folder.name + str(key)),
            aspect=1080 / (1920 - SEAM) if vi.get("scenes") else 9 / 16,
            family=cfg["reddit"].get("background_family", "horror"),
        )
        output = work / f"part{key}_layout.mp4"
        width = int(cfg["reddit"].get("preview_width", 540))
        height = width * 16 // 9
        shade = float(cfg["reddit"].get("vignette_opacity", 0.18))
        if vi.get("scenes"):
            bg_chain = (
                f"[1:v]{crop}scale=1080:960,setsar=1,split[g1][g2];"
                "[g2]boxblur=24:2,eq=brightness=-.3[gb];[gb][g1]vstack[raw];"
            )
        else:
            bg_chain = f"[1:v]{crop}scale=1080:1920,setsar=1[raw];"
        run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-stream_loop",
                "-1",
                "-ss",
                str(start + offset),
                "-i",
                str(source),
                "-ss",
                str(offset),
                "-i",
                str(mixed),
                "-filter_complex",
                bg_chain + f"[raw]eq=brightness=-{shade / 4:.3f}:saturation=.82,vignette=PI/6[bg];"
                f"[bg][0:v]overlay=0:0:format=auto,scale={width}:{height},fps=30,format=yuv420p[v]",
                "-map",
                "[v]",
                "-map",
                "2:a",
                "-t",
                str(min(12, elapsed)),
                "-c:v",
                "libx264",
                "-crf",
                "21",
                "-preset",
                "veryfast",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output),
            ],
            stage="story-preview",
        )
        outputs.append(output)
    return outputs
