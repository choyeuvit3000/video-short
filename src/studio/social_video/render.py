"""Shared narration, meme-image and media concatenation primitives."""
from __future__ import annotations

import os
import random
import shutil
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import subs, tts
from .util import ASSETS, MEMES, ffmpeg, log, media_duration, run

POST_W = 960          # screenshot width inside the 1080 frame
TOP = 300             # below the hook banner
BOTTOM_PAD = 330      # keep room for subtitles
SCROLL_PX_PER_SEC = 260
MEME_W = 560
AUDIO_LEAD = 0.4      # narration starts slightly after the cut


def _wrap_hook(hook: str, max_chars: int = 24) -> str:
    """Balanced 1-2 line wrap, so the hook never ends with an orphan word."""
    hook = " ".join(hook.split())
    if len(hook) <= max_chars:
        return hook
    words = hook.split()
    best = min(range(1, len(words)),
               key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
    return " ".join(words[:best]) + "\n" + " ".join(words[best:])


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def meme_image(src: Path, top: str, bottom: str, out: Path, font_path: str,
               width: int = MEME_W) -> Path:
    """Resize a meme and draw classic white-with-black-outline captions."""
    if src.suffix.lower() == ".gif":
        return src
    im = Image.open(src).convert("RGBA")
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    if top or bottom:
        draw = ImageDraw.Draw(im)
        for text, anchor_y in ((top, "top"), (bottom, "bottom")):
            if not text:
                continue
            text = text.upper()
            size = round(54 * width / MEME_W)
            while size > 26:
                font = _font(font_path, size)
                lines = textwrap.wrap(text, width=max(8, int(width / (size * 0.55))))
                if len(lines) <= 2:
                    break
                size -= 4
            block = "\n".join(lines)
            box = draw.multiline_textbbox((0, 0), block, font=font, align="center",
                                          stroke_width=4)
            bw, bh = box[2] - box[0], box[3] - box[1]
            x = (width - bw) / 2
            y = 12 if anchor_y == "top" else im.height - bh - 22
            draw.multiline_text((x, y), block, font=font, fill="white", align="center",
                                stroke_width=4, stroke_fill="black")
    # thin white border so memes read as "stickers" over the post
    framed = Image.new("RGBA", (im.width + 16, im.height + 16), (255, 255, 255, 255))
    framed.paste(im, (8, 8), im)
    framed.save(out)
    return out


class SegmentRenderer:
    def __init__(self, cfg: dict, workdir: Path, lib: dict):
        self.cfg = cfg
        self.dir = workdir
        self.items = {i["id"]: i for i in lib["items"]}
        self.W, self.H = cfg["video"]["width"], cfg["video"]["height"]
        self.fps = cfg["video"]["fps"]
        # Fonts are copied next to the filter scripts so ffmpeg paths need no escaping.
        shutil.copy(cfg["fonts"]["title"], workdir / "title.ttf")

    def narrate(self, text: str, name: str) -> tuple[Path | None, list[dict], float]:
        if not text.strip() or not self.cfg["tts"]["enabled"]:
            return None, [], 0.0
        mp3 = self.dir / f"{name}.mp3"
        try:
            words = tts.synth(text, mp3, self.cfg["tts"])
        except Exception as exc:
            if self.cfg['tts'].get('strict', False):
                raise
            log(f"  Bỏ giọng đọc đoạn này (TTS lỗi: {exc.__class__.__name__})")
            mp3.unlink(missing_ok=True)
            return None, [], 0.0
        return mp3, words, media_duration(mp3)

def _concat_raw(parts: list[Path], workdir: Path, out: Path, cfg: dict, name: str = "joined") -> Path:
    listing = workdir / f"{name}_concat.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    joined = workdir / f"{name}.mp4"
    run([ffmpeg(), "-y", "-hide_banner", "-f", "concat", "-safe", "0", "-i", listing.name,
         "-c", "copy", joined.name], cwd=workdir)

    bgm_files = [p for p in (ASSETS / "bgm").glob("*") if p.suffix.lower() in
                 {".mp3", ".m4a", ".wav", ".ogg"}]
    out.parent.mkdir(parents=True, exist_ok=True)
    if not (cfg["bgm"]["enabled"] and bgm_files):
        shutil.copy(joined, out)
        return out
    bgm = random.choice(bgm_files)
    log(f"Nhạc nền: {bgm.name}")
    vol = cfg["bgm"]["volume"]
    # Duck the music under narration/sfx with a sidechain compressor.
    graph = (f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol}[b];"
             "[0:a]asplit=2[main][key];"
             "[b][key]sidechaincompress=threshold=0.015:ratio=10:attack=15:release=400[duck];"
             "[main][duck]amix=inputs=2:normalize=0:duration=first[a]")
    run([ffmpeg(), "-y", "-hide_banner", "-i", str(joined), "-stream_loop", "-1", "-i", str(bgm),
         "-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)])
    return out


def concat(parts, workdir, out, cfg, name='joined'):
    from .quality import publish
    draft = workdir / f'{name}_unmastered.mp4'
    _concat_raw(parts, workdir, draft, cfg, name=name)
    return publish(draft, out, cfg)
