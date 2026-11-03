"""Post card PNG (Reddit/Threads style) drawn with Pillow - no browser, no AI."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .fonts import load_font

THEMES = {
    "light": {"bg": (255, 255, 255, 255), "text": (26, 26, 27), "muted": (120, 124, 126), "accent": (255, 69, 0)},
    "dark": {"bg": (26, 26, 27, 255), "text": (215, 218, 220), "muted": (129, 131, 132), "accent": (255, 69, 0)},
}


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _short_num(n: int | None) -> str:
    if n is None:
        return ""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def render_post_card(
    out: Path,
    *,
    video_width: int,
    title: str,
    community: str | None,
    author: str | None,
    score: int | None,
    platform: str = "reddit",
    theme: str = "light",
    fonts_dir: Path,
    width_ratio: float = 0.86,
    max_title_lines: int = 7,
) -> Path:
    t = THEMES.get(theme, THEMES["light"])
    w = int(video_width * width_ratio)
    pad = int(w * 0.06)
    u = w / 900  # unit scale
    f_title = load_font(fonts_dir, int(46 * u), "bold")
    f_meta = load_font(fonts_dir, int(28 * u), "regular")
    f_meta_b = load_font(fonts_dir, int(30 * u), "bold")

    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    lines = _wrap(probe, title, f_title, w - 2 * pad)
    if len(lines) > max_title_lines:
        lines = lines[:max_title_lines]
        lines[-1] = lines[-1].rstrip(".,;:") + "…"
    line_h = int(f_title.size * 1.25)
    header_h = int(80 * u)
    footer_h = int(64 * u)
    h = pad + header_h + int(18 * u) + line_h * len(lines) + int(24 * u) + footer_h + pad // 2

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(36 * u), fill=t["bg"])

    # header: avatar + community + author
    av = int(64 * u)
    d.ellipse([pad, pad, pad + av, pad + av], fill=t["accent"])
    name = community or platform or "?"
    name = name[2:] if name.startswith("r/") else name.lstrip("@")
    initial = (name[:1] or "?").upper()
    d.text((pad + av / 2, pad + av / 2), initial, font=f_meta_b, fill=(255, 255, 255), anchor="mm")
    x = pad + av + int(18 * u)
    head = community or platform.capitalize()
    if platform == "reddit" and community and not community.startswith("r/"):
        head = f"r/{community}"
    d.text((x, pad + int(4 * u)), head, font=f_meta_b, fill=t["text"])
    if author:
        sub = f"u/{author}" if platform == "reddit" else f"@{author}"
        d.text((x, pad + int(38 * u)), sub, font=f_meta, fill=t["muted"])

    y = pad + header_h + int(18 * u)
    for ln in lines:
        d.text((pad, y), ln, font=f_title, fill=t["text"])
        y += line_h
    y += int(24 * u)
    # footer: score + comments glyphs (drawn shapes, no icon font needed)
    s = int(26 * u)
    d.polygon([(pad, y + s), (pad + s / 2, y), (pad + s, y + s)], fill=t["accent"])
    d.text((pad + s + int(12 * u), y - int(4 * u)), _short_num(score) or "•", font=f_meta_b, fill=t["muted"])
    cx = pad + int(170 * u)
    d.rounded_rectangle([cx, y, cx + s, y + s * 0.8], radius=int(6 * u), outline=t["muted"], width=max(2, int(3 * u)))
    d.text((cx + s + int(12 * u), y - int(4 * u)), "Share", font=f_meta, fill=t["muted"])

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
