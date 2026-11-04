"""Jumpscare and hook assets for the Reddit videos.

  faces    pale, hollow-eyed faces drawn procedurally (numpy), no stock images
  screams  loud scare sounds from the local sound-effect folder, cut to start on the hit
  stings   low suspense sounds played under the opening hook
  moment   the sentence of a part where a jumpscare lands best (at most one per part)
"""
from __future__ import annotations

import math
import random
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .util import ASSETS, ffmpeg, log, run

DIR = ASSETS / "jumpscare"
SFX = ASSETS / "sfx" / "tiengdong"   # from tiengdong.com/am-thanh-meme
SCREAMS = ["tieng-dien-no-va-tieng-het-meme.mp3", "aaaa-aaaaa-aaaaaa-sound-effect.mp3"]
STINGS = ["long-suspense-sound-effect.mp3", "nhac-nen-to-mo-bi-an.mp3",
          "dramatic-vine-instagram-boom-sound-effect.mp3", "thunder-sound-effect-edit-video.mp3",
          "tieng-uynh.mp3"]
SCARE_SEC = 1.6
W, H = 1080, 1920


# ---------------------------------------------------------------- faces

def _face(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    r = random.Random(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = W / 2 + r.uniform(-30, 30), H * r.uniform(0.47, 0.53)
    fw, fh = W * r.uniform(0.5, 0.6), H * r.uniform(0.45, 0.52)
    # a gaunt head filling the frame: ellipse narrowed towards the chin, hollow cheeks
    ny = (yy - cy) / fh
    nx = (xx - cx) / (fw * (1 - 0.3 * np.clip(ny, 0, 1)))
    d = np.sqrt(nx ** 2 + ny ** 2)
    skin = np.clip(1.12 - d, 0, 1) ** 0.5
    cheeks = np.exp(-(((np.abs(xx - cx) - fw * 0.55) / (fw * 0.14)) ** 2
                      + ((yy - cy - fh * 0.12) / (fh * 0.2)) ** 2))
    shade = (0.5 + 0.5 * np.exp(-((xx - cx) / (fw * 0.85)) ** 2)) * (1 - 0.45 * cheeks)
    tex = rng.normal(0, 0.1, (H // 6, W // 6)).astype(np.float32)
    tex = np.array(Image.fromarray(tex).resize((W, H), Image.BICUBIC))
    lum = skin * shade * (0.85 + tex) + rng.normal(0, 0.035, (H, W))

    holes = Image.new("L", (W, H), 0)
    hd = ImageDraw.Draw(holes)
    ey = cy - fh * r.uniform(0.2, 0.28)
    ex = fw * r.uniform(0.34, 0.42)
    tilt = r.uniform(0.02, 0.07) * fh
    eyes = []
    for side in (-1, 1):
        x0, y0 = cx + side * ex, ey + side * tilt
        rx, ry = fw * r.uniform(0.16, 0.22), fh * r.uniform(0.1, 0.15)
        hd.ellipse([x0 - rx, y0 - ry, x0 + rx, y0 + ry], fill=255)
        for _ in range(r.randint(2, 5)):   # black streaks running down from the sockets
            sx = x0 + r.uniform(-rx * 0.7, rx * 0.7)
            ln, wd = r.uniform(120, 520), r.uniform(5, 15)
            hd.line([(sx, y0), (sx + r.uniform(-25, 25), y0 + ln)], fill=230, width=int(wd))
            hd.ellipse([sx - wd, y0 + ln - wd, sx + wd, y0 + ln + wd], fill=230)
        eyes.append((x0, y0))
    my = cy + fh * r.uniform(0.33, 0.42)
    mrx, mry = fw * r.uniform(0.15, 0.21), fh * r.uniform(0.24, 0.33)
    hd.ellipse([cx - mrx, my - mry, cx + mrx, my + mry], fill=255)
    hd.polygon([(cx - fw * 0.05, cy + fh * 0.02), (cx + fw * 0.05, cy + fh * 0.02),
                (cx, cy - fh * 0.08)], fill=200)   # nose cavity
    for _ in range(r.randint(10, 18)):   # cracks
        x, y = cx + r.uniform(-fw * 0.7, fw * 0.7), cy + r.uniform(-fh * 0.8, fh * 0.6)
        pts = [(x, y)]
        for _ in range(r.randint(4, 9)):
            x += r.uniform(-40, 40); y += r.uniform(-45, 45)
            pts.append((x, y))
        hd.line(pts, fill=150, width=r.randint(2, 4))
    holes = holes.filter(ImageFilter.GaussianBlur(5))
    hole = np.asarray(holes).astype(np.float32) / 255
    lum = np.clip(lum * (1 - hole), 0, 1)

    rgb = np.stack([lum * 0.9, lum * 0.93, lum * 0.86], -1)
    im = Image.fromarray((rgb * 255).astype(np.uint8))
    draw = ImageDraw.Draw(im)
    for x0, y0 in eyes:   # pin-prick pupils staring at the viewer
        pr = r.uniform(6, 10)
        draw.ellipse([x0 - pr, y0 - pr, x0 + pr, y0 + pr],
                     fill=(255, 30, 20) if r.random() < 0.6 else (250, 250, 240))
    n = r.randint(12, 20)   # needle teeth around the gaping mouth
    for k in range(n):
        a = math.pi * (0.08 + 0.84 * k / (n - 1))
        for top in (True, False):
            sy = -1 if top else 1
            bx = cx - mrx * 0.97 * math.cos(a)
            by = my + sy * mry * 0.97 * math.sin(a)
            tw, tl = r.uniform(4, 9), r.uniform(40, 120) * math.sin(a) + 15
            tip = (bx + r.uniform(-10, 10) - (bx - cx) * 0.15, by - sy * tl)
            c = int(r.uniform(170, 225))
            draw.polygon([(bx - tw, by), (bx + tw, by), tip], fill=(c, c - 5, c - 30))
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    a = np.asarray(im).astype(np.float32) / 255
    # warp: slow sideways ripple so the face is subtly wrong
    amp, lam, ph = r.uniform(10, 28), r.uniform(180, 360), r.uniform(0, 6.3)
    sx = np.clip((xx + amp * np.sin(yy / lam + ph)).astype(int), 0, W - 1)
    sy2 = np.clip((yy + amp * 0.6 * np.sin(xx / lam + ph * 2)).astype(int), 0, H - 1)
    a = a[sy2, sx]
    shift = r.randint(8, 16)   # chromatic split
    a[..., 0] = np.roll(a[..., 0], shift, axis=1)
    a[..., 2] = np.roll(a[..., 2], -shift, axis=1)
    a = np.clip((a - 0.1) * 1.5, 0, 1)
    vig = np.clip(1.3 - np.sqrt(((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.6)) ** 2),
                  0, 1)
    a = a * vig[..., None] + rng.normal(0, 0.06, a.shape)
    tint = r.choice([(0.82, 1.0, 0.8), (1.0, 0.72, 0.7), (0.9, 0.92, 1.0), (1.0, 1.0, 1.0)])
    return Image.fromarray((np.clip(a * np.array(tint), 0, 1) * 255).astype(np.uint8))


def faces(n: int = 8) -> list[Path]:
    DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for k in range(n):
        p = DIR / f"face_{k}.png"
        if not p.exists():
            _face(1000 + k * 37).save(p)
        out.append(p)
    return out


FRAME_SEC = 1 / 30
# (zoom, x shake, y shake, frames): a white flash, the face slams in large and settles,
# shaking; 24 frames = 0.8 s
MOTION = [(None, 0, 0, 2)] + [(1.32 - 0.32 * min(1, k / 5), (-1) ** k * (30 - k), (-1) ** (k // 2)
                               * (24 - k), 1) for k in range(22)]


def frames(face: Path) -> list[tuple[Path, float]]:
    """The jumpscare as (opaque png, seconds) frames, cached next to the face."""
    out = []
    with Image.open(face) as im:
        im = im.convert("RGB")
        for k, (zoom, dx, dy, n) in enumerate(MOTION):
            p = face.with_name(f"{face.stem}_f{k:02d}.png")
            if not p.exists():
                if zoom is None:
                    frame = Image.new("RGB", (W, H), (255, 255, 255))
                else:
                    big = im.resize((round(W * zoom), round(H * zoom)))
                    x = (big.width - W) // 2 - dx
                    y = (big.height - H) // 2 - dy
                    frame = big.crop((x, y, x + W, y + H))
                frame.save(p)
            out.append((p, n * FRAME_SEC))
    return out


# ---------------------------------------------------------------- sounds

def _cut(src: Path, out: Path, seconds: float, volume_db: float) -> None:
    """Start on the first loud moment, keep `seconds`, peak-normalise to `volume_db`."""
    run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af",
         "silenceremove=start_periods=1:start_threshold=-22dB,"
         f"atrim=0:{seconds},afade=out:st={max(0.0, seconds - 0.35):.2f}:d=0.35,"
         f"loudnorm=I=-12:TP={volume_db}:LRA=7",
         "-ar", "48000", "-ac", "2", str(out)])


def screams() -> list[Path]:
    return _sounds("scream", SCREAMS, SCARE_SEC, -0.5)


def stings() -> list[Path]:
    return _sounds("sting", STINGS, 7.0, -3.0)


def _sounds(kind: str, names: list[str], seconds: float, peak: float) -> list[Path]:
    DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for k, name in enumerate(names):
        p = DIR / f"{kind}_{k}.wav"
        if not p.exists():
            if not (SFX / name).exists():
                log(f"  thiếu âm thanh {name}")
                continue
            _cut(SFX / name, p, seconds, peak)
        out.append(p)
    return out


# ---------------------------------------------------------------- where

CUES = [
    (3, r"hét lên|thét lên|gào lên|rú lên|la hét|thét|gào thét"),
    (3, r"khuôn mặt|gương mặt|mặt nó|mặt hắn|mặt của nó"),
    (3, r"ngay sau lưng|sau lưng tôi|ngay trước mặt tôi|sát mặt tôi|ngay bên cạnh tôi"),
    (2, r"lao (tới|vào|về phía|ra)|nhảy bổ|chồm|vồ|chộp|túm lấy|tóm lấy|bám lấy|kéo tôi"),
    (2, r"nhìn chằm chằm|đang nhìn tôi|nhìn thẳng vào tôi|mở mắt|trợn|đôi mắt|hốc mắt|không có mắt"),
    (2, r"nhe răng|hàm răng|nụ cười|cười toe|cười rộng|miệng nó|há miệng|há hốc"),
    (2, r"bóng đen|cái bóng|hình bóng|bóng người|thứ đó|sinh vật|con quái"),
    (1, r"đập cửa|đập mạnh|cửa bật|bật mở|tiếng thét|tiếng hét|đột nhiên|bất thình lình|bỗng"),
    (1, r"xác|thi thể|máu|móng vuốt|móng tay|bàn tay lạnh|da trắng bệch|trắng bệch"),
]


def moment(sentences: list[str]) -> int | None:
    """Index of the scariest sentence, skipping the opening and the last two lines;
    None when nothing in the part is scary enough for a jumpscare."""
    best, best_score = None, 0
    lo, hi = max(2, len(sentences) // 6), len(sentences) - 2
    for i in range(lo, hi):
        s = sentences[i].lower()
        score = sum(w for w, pat in CUES if re.search(pat, s))
        score += 1 if s.rstrip().endswith(("!", "…")) else 0
        if score > best_score or (score == best_score and score and i > (best or 0)
                                  and i < hi - 1 and random.random() < 0.3):
            best, best_score = i, score
    return best if best_score >= 2 else None
