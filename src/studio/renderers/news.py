"""Newspaper-video frames drawn with Pillow, one layout per scene role: a still background (animated with Ken Burns
by the renderer) and a transparent text overlay (faded in by the renderer). No browser, no AI.

Layouts (assets/shared/layouts/news.yaml): headline, portrait_quote, editorial_photo, document (a real
document image, or the `text_card` fallback), stat_card, timeline, closing.

Every element stays above `limit_y` - the top of the caption band minus a gap, computed by the caller from the
caption style - and inside the platform safe zone, so captions never cover a headline, a name bar or a number.
Photos are cropped around a subject point (`focus`, fractions of the source image) instead of the centre.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .card import _wrap, _wrap_tagged
from .fonts import load_font

DARK = (12, 12, 16)
LAYOUTS = ("headline", "portrait_quote", "editorial_photo", "document", "text_card", "stat_card", "timeline",
           "closing")


def _hex(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha


def _open(src: Path | None) -> Image.Image | None:
    if src is None:
        return None
    with Image.open(src) as im:
        return im.convert("RGB")


def crop_focus(im: Image.Image, w: int, h: int, focus: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    """Cover-crop to w x h keeping the subject point `focus` (x, y in 0..1 of the source) as central as the
    image allows - a face left of centre stays in frame instead of being cut by a centre crop."""
    r = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * r)), max(h, round(im.height * r))), Image.LANCZOS)
    fx, fy = focus
    left = min(max(0, round(fx * im.width - w / 2)), im.width - w)
    top = min(max(0, round(fy * im.height - h / 2)), im.height - h)
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
            d.line([(0, y), (w, y)], fill=(int(30 - 18 * k), int(28 - 16 * k), int(46 - 30 * k)))
        return bg
    bg = crop_focus(im, w // 4, h // 4).filter(ImageFilter.GaussianBlur(10)).resize((w, h), Image.LANCZOS)
    return Image.blend(bg, Image.new("RGB", (w, h), DARK), darken)


def _shadow(base: Image.Image, box: tuple[int, int, int, int], radius: int, blur: int = 30) -> None:
    sh = Image.new("L", base.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle(box, radius=radius, fill=170)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.paste(Image.new("RGB", base.size, (0, 0, 0)), (0, 0), sh)


def _band(bg: Image.Image, photo: Image.Image, band_h: int, focus: tuple[float, float]) -> Image.Image:
    """The photo across the top `band_h` px, its lower third fading into the dark backdrop below."""
    w = bg.width
    top = crop_focus(photo, w, band_h, focus)
    mask = Image.new("L", (w, band_h), 255)
    d = ImageDraw.Draw(mask)
    fade0 = int(band_h * 0.72)
    for y in range(fade0, band_h):
        d.line([(0, y), (w, y)], fill=int(255 * (1 - (y - fade0) / max(1, band_h - fade0)) ** 1.4))
    bg.paste(top, (0, 0), mask)
    return bg


def _gradient(img: Image.Image, y0: int, y1: int, max_alpha: int, *, until: int | None = None) -> None:
    """Darken from y0 (transparent) to y1 (max_alpha), and keep max_alpha down to `until` (default: bottom)."""
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for y in range(max(0, y0), min(h, until if until is not None else h)):
        a = max_alpha if y >= y1 else int(max_alpha * (y - y0) / max(1, y1 - y0))
        d.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    img.alpha_composite(layer)


def _chip(d: ImageDraw.ImageDraw, x: int, y: int, text: str, font: ImageFont.FreeTypeFont, *, fill, color,
          pad: int, max_w: int, right: bool = False) -> int:
    """A rounded label (x is its right edge when right=True); returns its bottom y."""
    if d.textlength(text, font=font) > max_w:
        while len(text) > 8 and d.textlength(text + "…", font=font) > max_w:
            text = text[:-1]
        text = text.rstrip() + "…"
    tw = d.textlength(text, font=font)
    bh = int(font.size * 1.55)
    if right:
        x = int(x - tw - 2 * pad)
    d.rounded_rectangle([x, y, x + tw + 2 * pad, y + bh], radius=bh // 4, fill=fill)
    d.text((x + pad, y + bh / 2), text, font=font, fill=color, anchor="lm")
    return y + bh


def _fit_lines(d: ImageDraw.ImageDraw, text: str, fonts_dir: Path, size: int, max_w: int, max_lines: int, *,
               weight: str = "bold", min_size: int = 40) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """The largest font (down to min_size) at which `text` wraps into at most max_lines lines, evened out."""
    font = load_font(fonts_dir, size, weight)
    while True:
        lines = _wrap(d, text, font, max_w)
        if len(lines) <= max_lines or font.size <= min_size:
            break
        font = load_font(fonts_dir, font.size - 4, weight)
    width = max_w
    while len(lines) > 1 and width > max_w * 0.55:  # same line count, balanced (no lone word on the last line)
        trial = _wrap(d, text, font, int(width * 0.95))
        if len(trial) > len(lines):
            break
        width, lines = int(width * 0.95), trial
    return font, lines


def _rich_lines(d: ImageDraw.ImageDraw, text: str, highlight: str, font: ImageFont.FreeTypeFont,
                max_w: int) -> list[list[tuple[str, int]]]:
    """Wrapped words tagged 1 when they belong to the highlighted phrase (case-insensitive), else 0."""
    start = text.lower().find(highlight.lower()) if highlight else -1
    end = start + len(highlight) if start >= 0 else -1
    words, pos = [], 0
    for word in text.split():
        i = text.find(word, pos)
        pos = i + len(word)
        words.append((word, 1 if start >= 0 and i < end and pos > start else 0))
    lines = _wrap_tagged(d, words, font, max_w)
    width = max_w
    while len(lines) > 1 and width > max_w * 0.55:
        trial = _wrap_tagged(d, words, font, int(width * 0.95))
        if len(trial) > len(lines):
            break
        width, lines = int(width * 0.95), trial
    return lines


def _draw_rich(d: ImageDraw.ImageDraw, x: int, y: int, lines: list[list[tuple[str, int]]],
               font: ImageFont.FreeTypeFont, *, colors: tuple, line_h: int, stroke: int = 0) -> int:
    space = d.textlength(" ", font=font)
    for ln in lines:
        cx = x
        for word, tag in ln:
            d.text((cx, y), word, font=font, fill=colors[tag], stroke_width=stroke, stroke_fill=(0, 0, 0))
            cx += d.textlength(word, font=font) + space
        y += line_h
    return y


def _text_block(d: ImageDraw.ImageDraw, x: int, y: int, lines: list[str], font: ImageFont.FreeTypeFont, *,
                fill, line_h: int, stroke: int = 0) -> int:
    for ln in lines:
        d.text((x, y), ln, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += line_h
    return y


# ------------------------------------------------------------------ layouts


@dataclass
class Frame:
    """What a layout needs to know about the output frame and the shared look."""

    width: int
    height: int
    fonts_dir: Path
    safe: dict
    limit_y: int  # nothing below this (caption band)
    theme: dict
    params: dict = field(default_factory=dict)  # this layout's block of the layout config

    @property
    def u(self) -> float:
        return min(self.width, self.height) / 1080

    @property
    def vertical(self) -> bool:
        return self.height > self.width

    @property
    def left(self) -> int:
        return max(int(self.safe.get("left", 60)), int(56 * self.u))

    @property
    def right(self) -> int:
        return max(int(self.safe.get("right", 60)), int(56 * self.u))

    @property
    def top(self) -> int:
        return max(int(self.safe.get("top", 60)) // 2, int(44 * self.u))

    @property
    def col_w(self) -> int:
        return self.width - self.left - self.right if self.vertical else int(self.width * 0.6)

    def color(self, key: str, alpha: int = 255) -> tuple[int, int, int, int]:
        return _hex(self.theme.get(key, "#FFFFFF"), alpha)

    def font(self, size: float, weight: str = "bold") -> ImageFont.FreeTypeFont:
        return load_font(self.fonts_dir, int(size * self.u), weight)

    def p(self, key: str, default):
        return self.params.get(key, default)


def _header(fr: Frame, d: ImageDraw.ImageDraw, chip: str, brand: str) -> int:
    """Source chip top left, channel name top right; returns the y below them."""
    y = fr.top
    f = fr.font(26)
    bottom = y
    if chip:
        bottom = _chip(d, fr.left, y, chip, f, fill=(0, 0, 0, 160), color=(238, 238, 238), pad=int(14 * fr.u),
                       max_w=int(fr.col_w * (0.7 if brand else 0.95)))
    if brand:
        bottom = max(bottom, _chip(d, fr.width - fr.right, y, brand, fr.font(28), fill=(0, 0, 0, 130),
                                   color=(255, 255, 255), pad=int(16 * fr.u), max_w=int(fr.col_w * 0.4),
                                   right=True))
    return bottom


def _headline_text(fr: Frame, d: ImageDraw.ImageDraw, text: str, highlight: str, *, size: float, max_lines: int,
                   upper: bool) -> tuple[ImageFont.FreeTypeFont, list[list[tuple[str, int]]], int]:
    text = text.upper() if upper else text
    font, _ = _fit_lines(d, text, fr.fonts_dir, int(size * fr.u), fr.col_w, max_lines, min_size=int(44 * fr.u))
    lines = _rich_lines(d, text, highlight.upper() if upper else highlight, font, fr.col_w)
    while len(lines) > max_lines and font.size > max(6, int(20 * fr.u)):
        font = load_font(fr.fonts_dir, max(6, font.size - 2))
        lines = _rich_lines(d, text, highlight.upper() if upper else highlight, font, fr.col_w)
    return font, lines, int(font.size * 1.2)


def layout_headline(fr: Frame, photo: Image.Image | None, focus, *, text: str, highlight: str = "",
                    category: str = "", chip: str = "", brand: str = "") -> tuple[Image.Image, Image.Image]:
    w, h = fr.width, fr.height
    still = _blurred(photo, w, h, 0.62)
    if photo is not None:
        _band(still, photo, int(h * fr.p("band", 0.62)) if fr.vertical else h, focus)
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    font, lines, lh = _headline_text(fr, d, text, highlight, size=fr.p("font_size", 92),
                                     max_lines=int(fr.p("max_lines", 2)), upper=bool(fr.p("uppercase", True)))
    bar = int(10 * fr.u)
    y_text = fr.limit_y - bar - int(22 * fr.u) - lh * len(lines)
    f_c = fr.font(30)
    chip_h = int(f_c.size * 1.55) + int(18 * fr.u) if category else 0
    _gradient(ov, y_text - chip_h - int(260 * fr.u), y_text - chip_h, 200, until=fr.limit_y + int(40 * fr.u))
    d = ImageDraw.Draw(ov)
    _header(fr, d, chip, brand)
    if category:
        _chip(d, fr.left, y_text - chip_h, category.upper(), f_c, fill=fr.color("accent"), color=(255, 255, 255),
              pad=int(14 * fr.u), max_w=fr.col_w)
    y = _draw_rich(d, fr.left, y_text, lines, font, colors=(fr.color("text"), fr.color("accent")), line_h=lh,
                   stroke=max(1, int(2 * fr.u)))
    d.rectangle([fr.left, y + int(12 * fr.u), fr.left + int(96 * fr.u), y + int(12 * fr.u) + bar],
                fill=fr.color("accent"))
    return still, ov


def layout_portrait_quote(fr: Frame, photo: Image.Image | None, focus, *, name: str, title: str = "",
                          chip: str = "", brand: str = "") -> tuple[Image.Image, Image.Image]:
    """A press portrait (thin light border, no tilt) and the name bar: name bold, title on a second line."""
    w, h = fr.width, fr.height
    still = _blurred(photo, w, h, 0.5)
    pw = int(w * fr.p("width", 0.70)) if fr.vertical else int(w * 0.34)
    ph = int(pw / fr.p("aspect", 0.8))
    py = int(h * fr.p("top", 0.11)) if fr.vertical else int(h * 0.12)
    ph = min(ph, fr.limit_y - py - int(40 * fr.u))
    px = (w - pw) // 2 if fr.vertical else int(w * 0.1)
    if photo is not None:
        border = max(3, int(fr.p("border", 6) * fr.u))
        _shadow(still, (px, py + 12, px + pw, py + ph + 12), radius=6, blur=26)
        framed = Image.new("RGB", (pw, ph), fr.color("border")[:3])
        framed.paste(crop_focus(photo, pw - 2 * border, ph - 2 * border, focus), (border, border))
        still.paste(framed, (px, py))
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    _header(fr, d, chip, brand)
    f_n = fr.font(fr.p("name_size", 52))
    f_t = fr.font(fr.p("title_size", 32), "regular")
    pad = int(26 * fr.u)
    x0 = fr.left - int(8 * fr.u) if fr.vertical else int(w * 0.5)
    x1 = w - fr.right + int(8 * fr.u)
    names = _wrap(d, name, f_n, x1 - x0 - 2 * pad - int(10 * fr.u))[:2]
    titles = _wrap(d, title, f_t, x1 - x0 - 2 * pad - int(10 * fr.u))[:2] if title else []
    box_h = int(f_n.size * 1.2) * len(names) + int(f_t.size * 1.3) * len(titles) + 2 * pad
    y0 = fr.limit_y - box_h if fr.vertical else int(h * 0.62)
    d.rectangle([x0, y0, x1, y0 + box_h], fill=fr.color("panel", int(fr.theme.get("panel_alpha", 225))))
    d.rectangle([x0, y0, x0 + int(10 * fr.u), y0 + box_h], fill=fr.color("accent"))
    y = _text_block(d, x0 + pad + int(10 * fr.u), y0 + pad - int(4 * fr.u), names, f_n, fill=fr.color("text"),
                    line_h=int(f_n.size * 1.2))
    _text_block(d, x0 + pad + int(10 * fr.u), y + int(2 * fr.u), titles, f_t, fill=fr.color("muted"),
                line_h=int(f_t.size * 1.3))
    return still, ov


def layout_editorial_photo(fr: Frame, photo: Image.Image | None, focus, *, kicker: str = "", chip: str = "",
                           brand: str = "") -> tuple[Image.Image, Image.Image]:
    """The documentary photo across the top of the frame, captions below it on the dark backdrop."""
    w, h = fr.width, fr.height
    still = _blurred(photo, w, h, 0.62)
    if photo is not None:
        if fr.vertical:
            _band(still, photo, int(h * fr.p("band", 0.64)), focus)
        else:
            still = crop_focus(photo, w, h, focus)
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if not fr.vertical:
        _gradient(ov, int(h * 0.6), int(h * 0.85), 150)
    d = ImageDraw.Draw(ov)
    _header(fr, d, chip, brand)
    if kicker:
        f_k = fr.font(34)
        y = fr.limit_y - int(f_k.size * 1.55)
        _chip(d, fr.left, y, kicker.upper(), f_k, fill=fr.color("accent"), color=(255, 255, 255),
              pad=int(16 * fr.u), max_w=fr.col_w)
    return still, ov


def layout_document(fr: Frame, photo: Image.Image, *, kicker: str = "", chip: str = "",
                    brand: str = "") -> tuple[Image.Image, Image.Image]:
    """A real document / cover / poster, whole (never cropped), over a blurred copy of itself."""
    w, h = fr.width, fr.height
    still = _blurred(photo, w, h, 0.4)
    top = fr.top + int(90 * fr.u)
    fg = _contain(photo, int(w * fr.p("width", 0.8)) if fr.vertical else int(w * 0.5),
                  fr.limit_y - top - int(30 * fr.u))
    x, y = (w - fg.width) // 2, top + (fr.limit_y - top - fg.height) // 2
    border = max(3, int(fr.p("border", 6) * fr.u))
    _shadow(still, (x - border, y + 14, x + fg.width + border, y + fg.height + 14 + border), radius=8)
    still.paste(Image.new("RGB", (fg.width + 2 * border, fg.height + 2 * border), fr.color("border")[:3]),
                (x - border, y - border))
    still.paste(fg, (x, y))
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    yb = _header(fr, d, chip, brand)
    if kicker:
        _chip(d, fr.left, yb + int(14 * fr.u), kicker.upper(), fr.font(30), fill=fr.color("accent"),
              color=(255, 255, 255), pad=int(14 * fr.u), max_w=fr.col_w)
    return still, ov


def layout_text_card(fr: Frame, backdrop: Image.Image | None, *, kicker: str, title: str, points: list[str],
                     source: str, chip: str = "", brand: str = "") -> tuple[Image.Image, Image.Image]:
    """Document fallback: a paper card with the sourced key points (no verified document image)."""
    w, h = fr.width, fr.height
    still = _blurred(backdrop, w, h, 0.6)
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    _header(fr, d, chip, brand)
    pad = int(44 * fr.u)
    x0 = fr.left - int(8 * fr.u)
    x1 = w - fr.right + int(8 * fr.u) if fr.vertical else int(w * 0.62)
    inner = x1 - x0 - 2 * pad
    y_top = fr.top + int(110 * fr.u)
    scale = 1.0
    while True:  # shrink everything until the card fits above the caption band
        f_k = fr.font(30 * scale)
        f_t = fr.font(fr.p("title_size", 56) * scale)
        f_p = fr.font(fr.p("point_size", 40) * scale, "regular")
        f_s = fr.font(26 * scale, "regular")
        t_lines = _wrap(d, title, f_t, inner)[:3] if title else []
        bullet = int(f_p.size * 0.9)
        p_lines = [_wrap(d, pt, f_p, inner - bullet)[:2] for pt in points]
        lh_t, lh_p = int(f_t.size * 1.2), int(f_p.size * 1.3)
        gap = int(f_p.size * 0.55)
        body = sum(len(pl) * lh_p for pl in p_lines) + gap * max(0, len(p_lines) - 1)
        card_h = (2 * pad + int(f_k.size * 1.6) + (lh_t * len(t_lines) + int(24 * fr.u) if t_lines else 0) + body
                  + int(30 * fr.u) + int(f_s.size * 1.4))
        if y_top + card_h <= fr.limit_y or scale <= 0.7:
            break
        scale -= 0.05
    y0 = max(y_top, y_top + (fr.limit_y - y_top - card_h) // 3)
    d.rounded_rectangle([x0, y0, x1, y0 + card_h], radius=int(18 * fr.u), fill=fr.color("paper"))
    d.rounded_rectangle([x0, y0, x1, y0 + int(12 * fr.u)], radius=int(6 * fr.u), fill=fr.color("accent"))
    y = y0 + pad
    d.text((x0 + pad, y), kicker.upper(), font=f_k, fill=fr.color("accent"))
    y += int(f_k.size * 1.6)
    if t_lines:
        y = _text_block(d, x0 + pad, y, t_lines, f_t, fill=fr.color("ink"), line_h=lh_t) + int(24 * fr.u)
    for pl in p_lines:
        r = int(f_p.size * 0.17)
        cy = y + int(f_p.size * 0.62)
        d.ellipse([x0 + pad, cy - r, x0 + pad + 2 * r, cy + r], fill=fr.color("accent"))
        y = _text_block(d, x0 + pad + bullet, y, pl, f_p, fill=fr.color("ink"), line_h=lh_p) + gap
    d.text((x0 + pad, y0 + card_h - pad - int(f_s.size * 1.1)), source, font=f_s, fill=(110, 110, 118))
    return still, ov


def layout_stat_card(fr: Frame, backdrop: Image.Image | None, *, value: str, unit: str, explain: str,
                     kicker: str = "", chip: str = "", brand: str = "") -> tuple[Image.Image, Image.Image]:
    """One verified number: big value, its unit, one line saying what it counts - on a dark panel."""
    w, h = fr.width, fr.height
    still = _blurred(backdrop, w, h, 0.62)
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    _header(fr, d, chip, brand)
    pad = int(48 * fr.u)
    x0 = fr.left - int(8 * fr.u)
    x1 = w - fr.right + int(8 * fr.u) if fr.vertical else int(w * 0.62)
    inner = x1 - x0 - 2 * pad
    f_v = fr.font(fr.p("value_size", 250))
    while d.textlength(value, font=f_v) > inner and f_v.size > 60:
        f_v = load_font(fr.fonts_dir, f_v.size - 10, "bold")
    f_u = fr.font(fr.p("unit_size", 64))
    f_e = fr.font(fr.p("explain_size", 40), "regular")
    f_k = fr.font(30)
    u_lines = _wrap(d, unit.upper(), f_u, inner)[:2] if unit else []
    e_lines = _wrap(d, explain, f_e, inner)[:3] if explain else []
    asc, desc = f_v.getmetrics()
    v_h = int(asc * 0.98)  # digits have no descenders
    card_h = (2 * pad + (int(f_k.size * 1.7) if kicker else 0) + v_h + int(f_u.size * 1.2) * len(u_lines)
              + (int(22 * fr.u) + int(f_e.size * 1.32) * len(e_lines) if e_lines else 0))
    y0 = max(fr.top + int(100 * fr.u), min(int(h * 0.40) - card_h // 2, fr.limit_y - card_h))
    d.rounded_rectangle([x0, y0, x1, y0 + card_h], radius=int(22 * fr.u),
                        fill=fr.color("panel", int(fr.theme.get("panel_alpha", 225))))
    y = y0 + pad
    if kicker:
        d.text((x0 + pad, y), kicker.upper(), font=f_k, fill=fr.color("muted"))
        y += int(f_k.size * 1.7)
    d.text((x0 + pad, y + v_h), value, font=f_v, fill=fr.color("text"), anchor="ls")
    y += v_h + int(8 * fr.u)
    y = _text_block(d, x0 + pad, y, u_lines, f_u, fill=fr.color("accent"), line_h=int(f_u.size * 1.2))
    if e_lines:
        d.rectangle([x0 + pad, y + int(4 * fr.u), x0 + pad + int(70 * fr.u), y + int(9 * fr.u)],
                    fill=fr.color("accent"))
        _text_block(d, x0 + pad, y + int(22 * fr.u), e_lines, f_e, fill=fr.color("muted"),
                    line_h=int(f_e.size * 1.32))
    return still, ov


def layout_timeline(fr: Frame, backdrop: Image.Image | None, *, title: str, items: list[dict], chip: str = "",
                    brand: str = "") -> tuple[Image.Image, Image.Image]:
    """Dated milestones on a vertical line: date in the accent colour, what happens on the line below."""
    w, h = fr.width, fr.height
    still = _blurred(backdrop, w, h, 0.66)
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    _header(fr, d, chip, brand)
    pad = int(44 * fr.u)
    x0 = fr.left - int(8 * fr.u)
    x1 = w - fr.right + int(8 * fr.u) if fr.vertical else int(w * 0.62)
    scale = 1.0
    while True:
        f_t = fr.font(fr.p("title_size", 50) * scale)
        f_d = fr.font(fr.p("date_size", 46) * scale)
        f_x = fr.font(fr.p("text_size", 36) * scale, "regular")
        dot = int(34 * fr.u)
        inner = x1 - x0 - 2 * pad - dot
        t_lines = _wrap(d, title, f_t, x1 - x0 - 2 * pad)[:2] if title else []
        rows = [(it["date"], _wrap(d, it["text"], f_x, inner)[:2]) for it in items]
        row_h = [int(f_d.size * 1.25) + len(tx) * int(f_x.size * 1.3) for _, tx in rows]
        gap = int(30 * fr.u * scale)
        card_h = (2 * pad + len(t_lines) * int(f_t.size * 1.2) + (int(30 * fr.u) if t_lines else 0) + sum(row_h)
                  + gap * max(0, len(rows) - 1))
        y_top = fr.top + int(100 * fr.u)
        if y_top + card_h <= fr.limit_y or scale <= 0.7:
            break
        scale -= 0.05
    y0 = max(y_top, min(int(h * 0.40) - card_h // 2, fr.limit_y - card_h))
    d.rounded_rectangle([x0, y0, x1, y0 + card_h], radius=int(22 * fr.u),
                        fill=fr.color("panel", int(fr.theme.get("panel_alpha", 225))))
    y = _text_block(d, x0 + pad, y0 + pad, t_lines, f_t, fill=fr.color("text"), line_h=int(f_t.size * 1.2))
    y += int(30 * fr.u) if t_lines else 0
    lx = x0 + pad + int(9 * fr.u)
    first_y, last_y = y + int(f_d.size * 0.6), y + sum(row_h[:-1]) + gap * (len(rows) - 1) + int(f_d.size * 0.6)
    if len(rows) > 1:
        d.line([(lx, first_y), (lx, last_y)], fill=fr.color("muted", 160), width=max(2, int(4 * fr.u)))
    for (date, tx), rh in zip(rows, row_h, strict=True):
        cy = y + int(f_d.size * 0.6)
        r = int(10 * fr.u)
        d.ellipse([lx - r, cy - r, lx + r, cy + r], fill=fr.color("accent"))
        d.text((x0 + pad + dot, y), date, font=f_d, fill=fr.color("accent"))
        _text_block(d, x0 + pad + dot, y + int(f_d.size * 1.25), tx, f_x, fill=fr.color("text"),
                    line_h=int(f_x.size * 1.3))
        y += rh + gap
    return still, ov


def layout_closing(fr: Frame, backdrop: Image.Image | None, *, text: str, highlight: str = "", source: str = "",
                   chip: str = "", brand: str = "") -> tuple[Image.Image, Image.Image]:
    """A short last line, the source and the channel name."""
    w, h = fr.width, fr.height
    still = _blurred(backdrop, w, h, 0.55)
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    _header(fr, d, chip, "")
    y = int(h * 0.30) if fr.vertical else int(h * 0.3)
    if text:
        font, lines, lh = _headline_text(fr, d, text, highlight, size=fr.p("font_size", 74),
                                         max_lines=int(fr.p("max_lines", 3)), upper=False)
        y = min(y, fr.limit_y - lh * len(lines) - int(200 * fr.u))
        y = _draw_rich(d, fr.left, y, lines, font, colors=(fr.color("text"), fr.color("accent")), line_h=lh,
                       stroke=max(1, int(2 * fr.u)))
        d.rectangle([fr.left, y + int(16 * fr.u), fr.left + int(96 * fr.u), y + int(26 * fr.u)],
                    fill=fr.color("accent"))
        y += int(60 * fr.u)
    if source:
        y = _chip(d, fr.left, y, source, fr.font(28, "regular"), fill=(0, 0, 0, 170), color=(235, 235, 235),
                  pad=int(14 * fr.u), max_w=fr.col_w) + int(16 * fr.u)
    if brand:
        _chip(d, fr.left, y, brand, fr.font(36), fill=fr.color("accent"), color=(255, 255, 255),
              pad=int(18 * fr.u), max_w=fr.col_w)
    return still, ov


def render_layout(plan: dict, still_out: Path, overlay_out: Path, fr: Frame, src: Path | None, *,
                  chip: str = "", brand: str = "") -> tuple[Path, Path]:
    """Draw one planned scene: the still (background) and its overlay (text), saved as JPEG / PNG."""
    layout = plan["layout"]
    t = plan.get("text") or {}
    photo = _open(src)
    focus = tuple(plan.get("focus") or (0.5, 0.45))
    if layout == "headline":
        still, ov = layout_headline(fr, photo, focus, text=t.get("headline", ""), highlight=t.get("highlight", ""),
                                    category=t.get("category", ""), chip=chip, brand=brand)
    elif layout == "portrait_quote":
        still, ov = layout_portrait_quote(fr, photo, focus, name=t.get("name", ""), title=t.get("title", ""),
                                          chip=chip, brand=brand)
    elif layout == "document" and photo is not None:
        still, ov = layout_document(fr, photo, kicker=t.get("kicker", ""), chip=chip, brand=brand)
    elif layout in ("document", "text_card"):
        still, ov = layout_text_card(fr, photo, kicker=t.get("kicker", ""), title=t.get("title", ""),
                                     points=t.get("points") or [], source=t.get("source", ""), chip=chip,
                                     brand=brand)
    elif layout == "stat_card":
        still, ov = layout_stat_card(fr, photo, value=t.get("value", ""), unit=t.get("unit", ""),
                                     explain=t.get("explain", ""), kicker=t.get("kicker", ""), chip=chip,
                                     brand=brand)
    elif layout == "timeline":
        still, ov = layout_timeline(fr, photo, title=t.get("title", ""), items=t.get("items") or [], chip=chip,
                                    brand=brand)
    elif layout == "closing":
        still, ov = layout_closing(fr, photo, text=t.get("headline", ""), highlight=t.get("highlight", ""),
                                   source=t.get("source", ""), chip=chip, brand=brand)
    else:  # editorial_photo
        still, ov = layout_editorial_photo(fr, photo, focus, kicker=t.get("kicker", ""), chip=chip, brand=brand)
    still_out.parent.mkdir(parents=True, exist_ok=True)
    still.save(still_out, quality=94)
    ov.save(overlay_out)
    return still_out, overlay_out
