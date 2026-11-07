"""Prepare attributed comedy music and original, reusable Vietnamese reactions."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import wave
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

from studio.core.ffmpeg import run_ffmpeg
from studio.core.media_probe import probe

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets/shared"
WORK = ROOT / "projects/social_video/work/funny_threads/pilot_20261107"
VERSION = "funny-originals-1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def music() -> None:
    library_path = ASSETS / "music/library.json"
    library = json.loads(library_path.read_text(encoding="utf-8"))
    for title, slug in [("Fluffing a Duck", "fluffing-a-duck"), ("Sneaky Snitch", "sneaky-snitch")]:
        folder = ASSETS / "music/comedy" / slug
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{slug}.mp3"
        url = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/" + requests.utils.quote(title) + ".mp3"
        if not dest.exists():
            cached = WORK / "downloads" / f"{title}.mp3"
            if cached.is_file():
                shutil.copy2(cached, dest)
            else:
                result = requests.get(url, timeout=40)
                result.raise_for_status()
                dest.write_bytes(result.content)
        record = {
            "id": f"music:kevin-macleod/{slug}",
            "title": title,
            "creator": "Kevin MacLeod",
            "path": dest.relative_to(ROOT / "assets").as_posix(),
            "kind": "music",
            "tags": ["comedy", "playful", "instrumental", "hai_huoc", "funny_threads"],
            "mood": "comedy",
            "duration": probe(dest).duration,
            "sha256": sha(dest),
            "source_url": url,
            "license": "CC-BY-4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "license_evidence_url": "https://incompetech.com/music/royalty-free/faq.html",
            "status": "READY_WITH_ATTRIBUTION",
            "production_eligible": True,
            "automatic_selection": False,
            "attribution": (
                f"{title} — Kevin MacLeod (incompetech.com). Licensed under CC BY 4.0: "
                "https://creativecommons.org/licenses/by/4.0/; excerpt with fades and effects."
            ),
        }
        save(folder / "source.json", record)
        library["tracks"] = [x for x in library["tracks"] if x["id"] != record["id"]] + [record]
    save(library_path, library)


def sound(slug: str, seconds: float, mode: int) -> dict:
    rate = 48000
    t = np.arange(round(seconds * rate)) / rate
    rng = np.random.default_rng(mode + 100)
    if mode == 0:  # Rounded UI pop, no borrowed notification recording.
        x = np.sin(2 * math.pi * (800 * t - 1300 * t * t)) * np.exp(-t * 28)
    elif mode == 1:  # Soft descending cartoon spring.
        x = np.sin(2 * math.pi * (250 * t + 90 * np.sin(2 * math.pi * 6 * t) / (2 * math.pi * 6))) * np.exp(-t * 5)
    elif mode == 2:
        x = np.zeros_like(t)
        for offset, freq in [(0, 660), (0.12, 880), (0.25, 1100)]:
            q = np.maximum(t - offset, 0)
            x += (t >= offset) * np.sin(2 * math.pi * freq * q) * np.exp(-q * 12) * 0.45
    elif mode == 3:  # Short question chirp.
        x = np.sin(2 * math.pi * (400 * t + 900 * t * t)) * np.exp(-t * 6)
    elif mode == 4:  # Dry, quiet comic hit.
        x = 0.7 * np.sin(2 * math.pi * 170 * t) * np.exp(-t * 30) + rng.normal(0, 0.18, len(t)) * np.exp(-t * 65)
    elif mode == 5:
        x = rng.normal(0, 0.3, len(t)) * np.sin(math.pi * t / seconds) ** 3
        x = np.convolve(x, np.ones(5) / 5, mode="same")
    elif mode == 6:
        x = sum(np.sin(2 * math.pi * f * t) * np.exp(-t * 5) for f in [523.25, 659.25, 783.99]) / 3
    else:
        x = np.sin(2 * math.pi * (700 * t - 550 * t * t)) * np.exp(-t * 5)
    edge = np.minimum(1, np.minimum(t / 0.007, (seconds - t) / 0.025))
    x *= np.maximum(edge, 0)
    x = x / max(np.max(np.abs(x)), 1e-6) * 0.55
    path = ASSETS / "sfx/funny_originals" / f"{slug}.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes((x * 32767).astype("<i2").tobytes())
    return {
        "id": f"s:studio-original/{slug}",
        "kind": "sound",
        "path": path.relative_to(ROOT / "assets").as_posix(),
        "duration": seconds,
        "sha256": sha(path),
        "source": "procedural_original",
        "rights": "Created locally for this project; no sampled recording; no external license granted",
        "production_eligible": True,
        "role": "functional_effect",
        "is_meme": False,
        "funny_threads_allowed": False,
        "tags": ["funny_threads", "vn_editorial"],
        "version": VERSION,
    }


def cat_frame(phase: float, title: str, subtitle: str) -> Image.Image:
    """Simple original vector mascot; no existing character or meme template."""
    im = Image.new("RGB", (720, 720), "#faf1d9")
    d = ImageDraw.Draw(im)
    ink, paper, yellow = "#17221c", "#fffefa", "#f7cd4c"
    d.rounded_rectangle((14, 14, 706, 706), radius=40, outline=ink, width=5)
    bob = round(7 * math.sin(phase * 2 * math.pi))
    d.ellipse((194, 155 + bob, 530, 480 + bob), fill=paper, outline=ink, width=7)
    d.polygon([(202, 260 + bob), (205, 113 + bob), (301, 190 + bob)], fill=paper, outline=ink, width=7)
    d.polygon([(433, 190 + bob), (520, 113 + bob), (526, 260 + bob)], fill=paper, outline=ink, width=7)
    d.ellipse((212, 338 + bob, 275, 372 + bob), fill="#f7bdb0")
    d.ellipse((450, 338 + bob, 512, 372 + bob), fill="#f7bdb0")
    shift = round(12 * math.sin(phase * math.pi))
    for x in [280, 439]:
        d.ellipse((x - 38, 267 + bob, x + 38, 345 + bob), fill=ink)
        d.ellipse((x - 8 + shift, 280 + bob, x + 8 + shift, 314 + bob), fill=paper)
    d.polygon([(347, 350 + bob), (373, 350 + bob), (360, 366 + bob)], fill=ink)
    d.arc((326, 360 + bob, 360, 393 + bob), 0, 90, fill=ink, width=5)
    d.arc((360, 360 + bob, 394, 393 + bob), 90, 180, fill=ink, width=5)
    d.line((225, 370 + bob, 164, 358 + bob), fill=ink, width=4)
    d.line((492, 370 + bob, 553, 358 + bob), fill=ink, width=4)
    d.rounded_rectangle((230, 426 + bob, 490, 486 + bob), radius=17, fill=yellow, outline=ink, width=5)
    f = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 49)
    small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 32)
    d.text((360, 548), title, font=f, fill=ink, anchor="mm")
    d.text((360, 613), subtitle, font=small, fill=ink, anchor="mm")
    return im


def reactions() -> list[dict]:
    items = []
    for slug, title, subtitle in [
        ("xin-anh-minh-hoa", "CÓ ẢNH MINH HỌA", "Bình luận vào việc liền."),
        ("binh-luan-thanh-album", "ĐANG ĐỌC BÀI...", "Lát sau thành xem album."),
    ]:
        folder = ASSETS / "overlays/funny_originals" / slug
        folder.mkdir(parents=True, exist_ok=True)
        still = folder / f"{slug}.png"
        cat_frame(0, title, subtitle).save(still)
        frames = WORK / "reaction_frames" / slug
        frames.mkdir(parents=True, exist_ok=True)
        for i in range(48):
            cat_frame(i / 48, title, subtitle).save(frames / f"{i:03d}.png")
        video = folder / f"{slug}.mp4"
        run_ffmpeg(
            [
                "-framerate",
                "30",
                "-i",
                str(frames / "%03d.png"),
                "-frames:v",
                "48",
                "-an",
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(video),
            ],
            stage="original_reaction",
        )
        for p, kind in [(still, "image"), (video, "video")]:
            items.append(
                {
                    "id": f"{'i' if kind == 'image' else 'v'}:studio-original/{slug}",
                    "kind": kind,
                    "path": p.relative_to(ROOT / "assets").as_posix(),
                    "sha256": sha(p),
                    "source": "code_drawn_original",
                    "rights": "Created locally for this project; no external license granted",
                    "production_eligible": False,
                    "role": "editorial_overlay",
                    "is_meme": False,
                    "funny_threads_allowed": False,
                    "status": "CREATOR_REJECTED_NOT_MEME",
                    "panels": 1,
                    "duration": 1.6 if kind == "video" else None,
                    "tags": ["funny_threads", "vn_editorial"],
                    "version": VERSION,
                }
            )
    return items


def main() -> None:
    music()
    sounds = [
        sound(slug, sec, i)
        for i, (slug, sec) in enumerate(
            [
                ("soft-pop", 0.22),
                ("comic-boing", 0.7),
                ("reveal-dings", 0.8),
                ("question-chirp", 0.5),
                ("soft-bonk", 0.2),
                ("short-whoosh", 0.4),
                ("mini-ta-da", 1.0),
                ("comic-down", 0.65),
            ]
        )
    ]
    save(
        ASSETS / "overlays/funny_originals/library.json",
        {
            "version": VERSION,
            "items": sounds + reactions(),
            "selection_policy": (
                "Source-related, restrained cues; no repetitions inside one pilot; no sensitive topics."
            ),
            "unavailable_packs": [
                {
                    "title": "Kenney Interface Sounds",
                    "source": "https://kenney.nl/assets/interface-sounds",
                    "license": "CC0",
                    "status": "DOWNLOAD_HTTP_403_NOT_INSTALLED",
                }
            ],
            "music_reference": {
                "title": "Plants vs. Zombies OST",
                "status": "RIGHTS_NOT_VERIFIED_REFERENCE_ONLY",
                "production_eligible": False,
                "note": "Use a cheerful game-like mood, not an unlicensed OST copy.",
            },
        },
    )
    print("Prepared two new music tracks, eight original SFX and two image/video reactions.")


if __name__ == "__main__":
    main()
