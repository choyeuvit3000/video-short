"""Post / passage / hook / end card PNGs (Reddit/Threads style) drawn with Pillow - no browser, no AI."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .fonts import load_font

THEMES = {
    "light": {"bg": (255, 255, 255, 255), "text": (26, 26, 27), "muted": (120, 124, 126), "dim": (178, 181, 184),
              "accent": (255, 69, 0)},
    "dark": {"bg": (26, 26, 27, 255), "text": (215, 218, 220), "muted": (129, 131, 132), "dim": (100, 102, 104),
             "accent": (255, 69, 0)},
}
HOOK_RED = (255, 52, 40)


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


def _wrap_tagged(draw: ImageDraw.ImageDraw, words: list[tuple[str, int]], font: ImageFont.FreeTypeFont,
                 max_w: int) -> list[list[tuple[str, int]]]:
    """Like _wrap, but each word keeps a tag (e.g. the index of its sentence) for per-word colour."""
    lines: list[list[tuple[str, int]]] = []
    cur: list[tuple[str, int]] = []
    for w in words:
        trial = " ".join(x for x, _ in [*cur, w])
        if cur and draw.textlength(trial, font=font) > max_w:
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def _short_num(n: int | None) -> str:
    if n is None:
        return ""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _header(d: ImageDraw.ImageDraw, t: dict, *, pad: int, u: float, fonts_dir: Path, community: str | None,
            author: str | None, platform: str) -> int:
    """Avatar + community + author at the top of a card; returns its height."""
    f_meta = load_font(fonts_dir, int(28 * u), "regular")
    f_meta_b = load_font(fonts_dir, int(30 * u), "bold")
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
    return int(80 * u)


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
    badge: str | None = None,
) -> Path:
    """The post header + title; `badge` (e.g. "Phần 2/3") is drawn as an accent pill in the footer."""
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
    _header(d, t, pad=pad, u=u, fonts_dir=fonts_dir, community=community, author=author, platform=platform)

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
    if badge:
        bw = d.textlength(badge, font=f_meta_b) + int(40 * u)
        bh = int(48 * u)
        bx, by = w - pad - bw, y + s / 2 - bh / 2
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2, fill=t["accent"])
        d.text((bx + bw / 2, by + bh / 2), badge, font=f_meta_b, fill=(255, 255, 255), anchor="mm")

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def render_passage_card(
    out: Path,
    *,
    video_width: int,
    video_height: int,
    sentences: list[str],
    current: int,
    community: str | None,
    author: str | None,
    platform: str = "reddit",
    theme: str = "light",
    fonts_dir: Path,
    width_ratio: float = 0.86,
) -> Path:
    """A passage of 1-3 sentences on the post card; sentence `current` (being read) is bright, the rest dim."""
    t = THEMES.get(theme, THEMES["light"])
    w = int(video_width * width_ratio)
    pad = int(w * 0.06)
    u = w / 900
    words = [(word, k) for k, s in enumerate(sentences) for word in s.split()]
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    header_h = int(80 * u)
    size = int(42 * u)
    while True:  # shrink the type until the card fits in 85% of the frame
        f_body = load_font(fonts_dir, size, "bold")
        lines = _wrap_tagged(probe, words, f_body, w - 2 * pad)
        line_h = int(size * 1.35)
        h = pad + header_h + int(16 * u) + line_h * len(lines) + pad
        if h <= video_height * 0.85 or size <= 18:
            break
        size -= 2

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(36 * u), fill=t["bg"])
    _header(d, t, pad=pad, u=u, fonts_dir=fonts_dir, community=community, author=author, platform=platform)
    space = d.textlength(" ", font=f_body)
    y = pad + header_h + int(16 * u)
    for line in lines:
        x = pad
        for word, k in line:
            d.text((x, y), word, font=f_body, fill=t["text"] if k == current else t["dim"])
            x += d.textlength(word, font=f_body) + space
        y += line_h

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def render_hook_card(out: Path, *, video_width: int, video_height: int, sentences: list[str],
                     fonts_dir: Path) -> Path:
    """Full-frame opener: the hook in big type over a darkened background, its last sentence in red."""
    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 150))
    d = ImageDraw.Draw(img)
    u = min(video_width, video_height) / 1080
    font = load_font(fonts_dir, int(78 * u), "bold")
    last = len(sentences) - 1
    words = [(word, int(k == last and last > 0)) for k, s in enumerate(sentences) for word in s.split()]
    lines = _wrap_tagged(d, words, font, int(video_width * 0.85))
    line_h = int(font.size * 1.25)
    y = video_height * 0.42 - len(lines) * line_h / 2
    stroke = max(2, int(5 * u))
    for line in lines:
        x = (video_width - d.textlength(" ".join(word for word, _ in line), font=font)) / 2
        for word, red in line:
            d.text((x, y), word, font=font, fill=HOOK_RED if red else (255, 255, 255),
                   stroke_width=stroke, stroke_fill=(0, 0, 0))
            x += d.textlength(word + " ", font=font)
        y += line_h

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def render_end_card(out: Path, *, video_width: int, text: str, theme: str = "light", fonts_dir: Path,
                    width_ratio: float = 0.86) -> Path:
    """Closing card: one short line ("Còn tiếp ở phần 2.", the CTA...) centred on the card."""
    t = THEMES.get(theme, THEMES["light"])
    w = int(video_width * width_ratio)
    pad = int(w * 0.06)
    u = w / 900
    font = load_font(fonts_dir, int(46 * u), "bold")
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    lines = _wrap(probe, text, font, w - 2 * pad)
    line_h = int(font.size * 1.3)
    h = 2 * pad + line_h * len(lines)

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(36 * u), fill=t["bg"])
    y = pad
    for ln in lines:
        d.text(((w - d.textlength(ln, font=font)) / 2, y), ln, font=font, fill=t["text"])
        y += line_h

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
