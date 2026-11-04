"""Recompose a landscape full story from approved narration, without Shorts title/outro repetition."""

import copy
import random
import textwrap

from PIL import Image, ImageDraw, ImageFont

from ..core.outputs import organized_output
from . import bgclips
from .util import FINAL_OUTPUT, ffmpeg, media_duration, run


def export_full(story_id, story, vi, groups, voiced, cfg, folder):
    from .quality import publish
    from .reddit import _join
    from .story_source import labels, mode

    work = folder / "full"
    work.mkdir(exist_ok=True)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 42)
    heading = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 46)
    lines = []
    index = 0
    for g in groups:
        for current, _sentence in enumerate(g):
            image = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((55, 55, 1060, 1025), radius=28, fill=(15, 22, 32, 250))
            draw.text(
                (95, 100),
                " · ".join(labels(story)),
                font=font,
                fill="#B5BDC8",
            )
            title = textwrap.wrap(vi.get("shock_title") or vi["title"], 34)
            draw.multiline_text((95, 190), "\n".join(title[:3]), font=heading, fill="white", spacing=12)
            y = 430
            for n, s in enumerate(g):
                wrapped = textwrap.wrap(s, 40)
                draw.multiline_text(
                    (95, y), "\n".join(wrapped), font=font, fill="white" if n == current else "#7F8999", spacing=10
                )
                y += len(wrapped) * 56 + 16
            frame = work / f"card_{index:04d}.png"
            image.save(frame)
            lines += ["file '" + frame.name + "'", f"duration {voiced[index][1]:.6f}"]
            index += 1
    lines.append("file '" + frame.name + "'")
    (work / "cards.txt").write_text("ffconcat version 1.0\n" + "\n".join(lines) + "\n", encoding="utf-8")
    narration = work / "narration.wav"
    _join([p for p, t in voiced], narration, 0.0)
    seconds = media_duration(narration)
    bg = bgclips.pick(
        seconds, random.Random(story_id), 820 / 1080, family=cfg["reddit"].get("background_family", "any")
    )
    if not bg:
        raise RuntimeError("No background available for full landscape video")
    src, start, crop = bg
    draft = work / "full_unmastered.mp4"
    run(
        [
            ffmpeg(),
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            "cards.txt",
            "-stream_loop",
            "-1",
            "-ss",
            str(start),
            "-i",
            str(src.resolve()),
            "-i",
            str(narration.resolve()),
            "-filter_complex",
            f"[1:v]{crop}scale=820:1080,fps=30,setsar=1,pad=1920:1080:1100:0:color=0x101822[bg];[bg][0:v]overlay=0:0:format=auto,format=yuv420p[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(draft.resolve()),
        ],
        cwd=work,
    )
    full_mode = mode(story) + "_full"
    outdir = organized_output(FINAL_OUTPUT, full_mode, folder / "full_output_location.json")
    out = outdir / f"{full_mode}__{story_id}.mp4"
    wide = copy.deepcopy(cfg)
    wide["video"].update(width=1920, height=1080)
    publish(draft, out, wide)
    return out
