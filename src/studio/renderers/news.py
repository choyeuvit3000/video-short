"""Newspaper-video frames drawn with Pillow: still backgrounds (animated with Ken Burns by the renderer) and
static text overlays (source chip, headline block, quote lower-third, big number). No browser, no AI.

Positions are fractions of the frame and stay clear of the caption band (format `caption.margin_v`) and the
platform UI (`safe_zone`).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .card import _wrap
from .fonts import load_font

DARK = (12, 12, 16)


def _hex(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    r = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * r)), max(h, round(im.height * r))), Image.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def _contain(im: Image.Image, w: int, h: int) -> Image.Image:
    r = min(w / im.width, h / im.height)
    return im.resize((max(1, round(im.width * r)), max(1, round(im.height * r))), Image.LANCZOS)


def _blurred(im: Image.Image | None, w: int, h: int, darken: float) -> Image.Image:
    if im is None:  # no photo: a dark vertical gradient
        bg = Image.new("RGB", (w, h), DARK)
        d = ImageDraw.Draw(bg)
        for y in range(h):
            k = y / h
            d.line([(0, y), (w, y)], fill=(int(28 - 16 * k), int(26 - 14 * k), int(44 - 28 * k)))
        return bg
    bg = _cover(im, w // 4, h // 4).filter(ImageFilter.GaussianBlur(10)).resize((w, h), Image.LANCZOS)
    return Image.blend(bg, Image.new("RGB", (w, h), DARK), darken)


def _shadow(base: Image.Image, box: tuple[int, int, int, int], radius: int, blur: int = 30) -> None:
    sh = Image.new("L", base.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle(box, radius=radius, fill=170)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.paste(Image.new("RGB", base.size, (0, 0, 0)), (0, 0), sh)


def _open(src: Path | None) -> Image.Image | None:
    if src is None:
        return None
    with Image.open(src) as im:
        return im.convert("RGB")


def still_photo(src: Path, out: Path, w: int, h: int) -> Path:
    """The article photo filling the frame (the renderer adds the slow zoom/pan)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    _cover(_open(src), w, h).save(out, quality=94)
    return out


def still_framed(src: Path, out: Path, w: int, h: int, *, tilt: float = -3.0) -> Path:
    """Quote scene: blurred backdrop + the photo in a slightly tilted white frame, upper half of the frame."""
    im = _open(src)
    bg = _blurred(im, w, h, 0.45)
    u = min(w, h) / 1080
    pw = int(w * (0.72 if h > w else 0.36))
    ph = int(pw * 1.25) if h > w else int(pw * 0.8)
    photo = _cover(im, pw, ph)
    border = max(8, int(16 * u))
    framed = Image.new("RGB", (pw + 2 * border, ph + 2 * border), (245, 245, 245))
    framed.paste(photo, (border, border))
    framed = framed.convert("RGBA").rotate(tilt, resample=Image.BICUBIC, expand=True)
    cx, cy = (w // 2, int(h * 0.34)) if h > w else (int(w * 0.3), h // 2)
    x, y = cx - framed.width // 2, cy - framed.height // 2
    _shadow(bg, (x + 10, y + 18, x + framed.width - 10, y + framed.height), radius=12)
    bg.paste(framed, (x, y), framed)
    out.parent.mkdir(parents=True, exist_ok=True)
    bg.save(out, quality=94)
    return out


def still_card(src: Path, out: Path, w: int, h: int) -> Path:
    """Document/poster scene: the whole image (never cropped) centred over a blurred copy of itself."""
    im = _open(src)
    bg = _blurred(im, w, h, 0.35)
    u = min(w, h) / 1080
    fg = _contain(im, int(w * (0.8 if h > w else 0.5)), int(h * (0.5 if h > w else 0.72)))
    x, y = (w - fg.width) // 2, int(h * (0.36 if h > w else 0.5)) - fg.height // 2
    radius = int(22 * u)
    _shadow(bg, (x, y + 14, x + fg.width, y + fg.height + 14), radius=radius)
    mask = Image.new("L", fg.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, fg.width - 1, fg.height - 1], radius=radius, fill=255)
    bg.paste(fg, (x, y), mask)
    out.parent.mkdir(parents=True, exist_ok=True)
    bg.save(out, quality=94)
    return out


def still_backdrop(src: Path | None, out: Path, w: int, h: int) -> Path:
    """Number scene: a heavily blurred, darkened photo (or a dark gradient)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    _blurred(_open(src), w, h, 0.6).save(out, quality=94)
    return out


# ------------------------------------------------------------------ overlays


def _chip(d: ImageDraw.ImageDraw, x: int, y: int, text: str, font: ImageFont.FreeTypeFont, *, fill, color,
          pad: int, max_w: int) -> int:
    """A rounded label; returns its bottom y."""
    if d.textlength(text, font=font) > max_w:
        while len(text) > 8 and d.textlength(text + "…", font=font) > max_w:
            text = text[:-1]
        text = text.rstrip() + "…"
    tw = d.textlength(text, font=font)
    bh = int(font.size * 1.5)
    d.rounded_rectangle([x, y, x + tw + 2 * pad, y + bh], radius=bh // 4, fill=fill)
    d.text((x + pad, y + bh / 2), text, font=font, fill=color, anchor="lm")
    return y + bh


def _gradient(img: Image.Image, top: float, bottom: float, max_alpha: int) -> None:
    """Darken from `top` (fraction of height, transparent) down to `bottom` (max_alpha) and below."""
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y0, y1 = int(h * top), int(h * bottom)
    for y in range(y0, h):
        a = max_alpha if y >= y1 else int(max_alpha * (y - y0) / max(1, y1 - y0))
        d.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    img.alpha_composite(layer)


def _balanced_wrap(d: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Same number of lines as a greedy wrap, but evened out (no lone "15.3" on the last line)."""
    lines = _wrap(d, text, font, max_w)
    width = max_w
    while len(lines) > 1 and width > max_w * 0.5:
        trial = _wrap(d, text, font, int(width * 0.96))
        if len(trial) > len(lines):
            break
        width, lines = int(width * 0.96), trial
    return lines


def _text_block(d: ImageDraw.ImageDraw, x: int, y: int, lines: list[str], font: ImageFont.FreeTypeFont, *,
                fill, line_h: int, stroke: int = 0) -> int:
    for ln in lines:
        d.text((x, y), ln, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += line_h
    return y


def news_overlay(
    out: Path,
    *,
    width: int,
    height: int,
    kind: str,  # headline | photo | quote | stat | card
    fonts_dir: Path,
    safe: dict,
    chip: str = "",
    brand: str = "",
    accent: str = "#FF5A1F",
    headline: str = "",
    category: str = "",
    name: str = "",
    role: str = "",
    value: str = "",
    label: str = "",
    note: str = "",
    title_chip: str = "",
) -> Path:
    w, h = width, height
    vertical = h > w
    u = min(w, h) / 1080
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if kind in ("headline", "photo"):
        _gradient(img, 0.42 if kind == "headline" else 0.55, 0.75, 215 if kind == "headline" else 150)
    d = ImageDraw.Draw(img)
    left = max(int(safe.get("left", 60)), int(48 * u))
    right = max(int(safe.get("right", 60)), int(48 * u))
    top = max(int(safe.get("top", 60)) // 2, int(40 * u))
    col_w = (w - left - right) if vertical else int(w * 0.58)
    acc = _hex(accent)
    f_small = load_font(fonts_dir, int(26 * u), "bold")

    y_chip = top
    if title_chip:
        f_t = load_font(fonts_dir, int(28 * u), "bold")
        lines = _wrap(d, title_chip.upper(), f_t, int(col_w * 0.9))[:2]
        lh = int(f_t.size * 1.25)
        box_h = lh * len(lines) + int(18 * u)
        box_w = max(d.textlength(ln, font=f_t) for ln in lines) + int(28 * u)
        d.rectangle([left, y_chip, left + box_w, y_chip + box_h], fill=(255, 255, 255, 235))
        _text_block(d, left + int(14 * u), y_chip + int(9 * u), lines, f_t, fill=(17, 17, 17), line_h=lh)
        y_chip += box_h + int(14 * u)
    if chip:
        _chip(d, left, y_chip, chip, f_small, fill=(0, 0, 0, 150), color=(235, 235, 235), pad=int(14 * u),
              max_w=int(col_w * 0.7))
    if brand:
        f_b = load_font(fonts_dir, int(28 * u), "bold")
        bw = d.textlength(brand, font=f_b) + int(32 * u)
        _chip(d, int(w - right - bw), top, brand, f_b, fill=(0, 0, 0, 120), color=(255, 255, 255),
              pad=int(16 * u), max_w=int(w * 0.4))

    if kind == "headline" and headline:
        f_h = load_font(fonts_dir, int((84 if vertical else 72) * u), "bold")
        lines = _balanced_wrap(d, headline.upper(), f_h, col_w)
        while len(lines) > 4 and f_h.size > 40:
            f_h = load_font(fonts_dir, f_h.size - 6, "bold")
            lines = _balanced_wrap(d, headline.upper(), f_h, col_w)
        lh = int(f_h.size * 1.15)
        bottom = int(h * (0.6 if vertical else 0.8))
        y = bottom - lh * len(lines)
        if category:
            f_c = load_font(fonts_dir, int(30 * u), "bold")
            _chip(d, left, y - int(f_c.size * 1.5) - int(18 * u), category.upper(), f_c, fill=acc,
                  color=(255, 255, 255), pad=int(14 * u), max_w=col_w)
        y = _text_block(d, left, y, lines, f_h, fill=(255, 255, 255), line_h=lh, stroke=max(1, int(2 * u)))
        d.rectangle([left, y + int(14 * u), left + int(90 * u), y + int(22 * u)], fill=acc)
    elif kind == "quote" and name:
        f_n = load_font(fonts_dir, int(50 * u), "bold")
        f_r = load_font(fonts_dir, int(28 * u), "regular")
        roles = _wrap(d, role, f_r, col_w - int(56 * u))[:2] if role else []
        names = _wrap(d, name, f_n, col_w - int(56 * u))[:2]
        box_h = int(f_n.size * 1.2) * len(names) + int(f_r.size * 1.3) * len(roles) + int(52 * u)
        y0 = int(h * 0.585) if vertical else int(h * 0.62)
        x0 = left - int(8 * u) if vertical else int(w * 0.52)
        x1 = w - right + int(8 * u) if vertical else w - right
        d.rectangle([x0, y0, x1, y0 + box_h], fill=(16, 16, 20, 215))
        d.rectangle([x0, y0, x1, y0 + max(4, int(7 * u))], fill=acc)
        y = _text_block(d, x0 + int(28 * u), y0 + int(26 * u), names, f_n, fill=(255, 255, 255),
                        line_h=int(f_n.size * 1.2))
        _text_block(d, x0 + int(28 * u), y + int(4 * u), roles, f_r, fill=(190, 190, 196),
                    line_h=int(f_r.size * 1.3))
    elif kind == "stat" and value:
        f_v = load_font(fonts_dir, int((230 if vertical else 200) * u), "bold")
        while d.textlength(value, font=f_v) > col_w and f_v.size > 60:
            f_v = load_font(fonts_dir, f_v.size - 10, "bold")
        f_l = load_font(fonts_dir, int(58 * u), "bold")
        f_s = load_font(fonts_dir, int(32 * u), "regular")
        y = int(h * (0.3 if vertical else 0.28))
        d.text((left, y), value, font=f_v, fill=(255, 255, 255))
        y += int(f_v.size * 1.08)
        y = _text_block(d, left, y, _wrap(d, label.upper(), f_l, col_w)[:3], f_l, fill=acc,
                        line_h=int(f_l.size * 1.15))
        if note:
            _text_block(d, left, y + int(10 * u), _wrap(d, note, f_s, col_w)[:2], f_s, fill=(200, 200, 205),
                        line_h=int(f_s.size * 1.3))

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
