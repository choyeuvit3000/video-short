"""Manim CE scene templates, run by `python -m manim render templates.py T_<name>` (see manim_render.py).

Everything comes from the JSON spec in $STUDIO_MANIM_SPEC: size, fps, duration, palette, the content box
(inside the safe zone and above the captions), validated params and the reveal time of each list item.
This file imports nothing from studio and runs no code from the spec - params are data only.

Coordinates: the short side of the frame is 9 units (9x16 portrait, 16x9 landscape). Sizes passed to `txt`
are line heights in pixels of a 1080 px short side, so layouts look the same at every resolution.
Text uses Pango (no LaTeX); `formula.tex` is used only when the spec says LaTeX is installed.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
from manim import (
    BOLD,
    DOWN,
    ITALIC,
    LEFT,
    RIGHT,
    UP,
    Arrow,
    Axes,
    Circle,
    Create,
    CurvedArrow,
    Dot,
    FadeIn,
    Group,
    GrowArrow,
    GrowFromCenter,
    GrowFromEdge,
    ImageMobject,
    Indicate,
    Line,
    MathTex,
    Paragraph,
    Rectangle,
    RoundedRectangle,
    Scene,
    SurroundingRectangle,
    Text,
    ValueTracker,
    VGroup,
    Write,
    always_redraw,
    config,
    linear,
    smooth,
)

_SPEC_FILE = os.environ.get("STUDIO_MANIM_SPEC")
SPEC: dict = json.loads(Path(_SPEC_FILE).read_text(encoding="utf-8")) if _SPEC_FILE else {
    "width": 1080, "height": 1920, "fps": 30, "duration": 6, "voice": 5, "params": {}, "times": [],
    "box": {"x0": 60, "y0": 220, "x1": 940, "y1": 1150}, "font": "Arial", "language": "vi",
    "palette": {"background": "#101626", "text": "#F4F6FB", "muted": "#9AA4B8",
                "accent": ["#4CC9F0", "#FFD166", "#EF476F", "#06D6A0"]},
}

W, H, FPS = int(SPEC["width"]), int(SPEC["height"]), int(SPEC["fps"])
DUR, VOICE = float(SPEC["duration"]), float(SPEC.get("voice") or 0)
PORTRAIT = H > W
SHORT = min(W, H)
FW, FH = 9 * W / SHORT, 9 * H / SHORT
U = FW / W  # units per pixel
PAL = SPEC["palette"]
ACC = list(PAL["accent"]) or ["#4CC9F0"]
FONT = SPEC.get("font") or "Arial"
LANG = SPEC.get("language", "vi")

config.frame_width, config.frame_height = FW, FH
config.pixel_width, config.pixel_height, config.frame_rate = W, H, FPS
config.background_color = PAL["background"]


def _pt(x: float, y: float) -> np.ndarray:
    return np.array([(x / W - 0.5) * FW, (0.5 - y / H) * FH, 0.0])


_B = SPEC["box"]
BOX_C = _pt((_B["x0"] + _B["x1"]) / 2, (_B["y0"] + _B["y1"]) / 2)
BOX_W, BOX_H = (_B["x1"] - _B["x0"]) * U, (_B["y1"] - _B["y0"]) * U
BOX_TOP = BOX_C[1] + BOX_H / 2
BOX_BOTTOM = BOX_C[1] - BOX_H / 2
BOX_LEFT = BOX_C[0] - BOX_W / 2
_REF: list[float] = []


def acc(i: int) -> str:
    return ACC[i % len(ACC)]


def wrap(text: str, width: int) -> str:
    """Greedy word wrap, then the narrowest width with the same line count (no lone last word)."""
    n = _wrap(text, width).count("\n")
    for w in range(max(1, math.ceil(len(text) / (n + 1))), width):
        out = _wrap(text, w)
        if out.count("\n") == n:
            return out
    return _wrap(text, width)


def _wrap(text: str, width: int) -> str:
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    if cur:
        lines.append(cur)
    return "\n".join(lines)


_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋", "0123456789+-")  # most UI fonts lack them (CO₂ -> CO2)


def _math_font() -> str:
    """Arial lacks symbols such as ∝ ∈ ⇒; use a math font for formulas when the machine has one."""
    try:
        import manimpango
        have = set(manimpango.list_fonts())
    except Exception:  # noqa: BLE001 - any failure -> keep the UI font
        return FONT
    return next((f for f in ("Cambria Math", "Segoe UI Symbol", "DejaVu Sans") if f in have), FONT)


def txt(s: str, size: float, color: str | None = None, *, bold: bool = False, italic: bool = False,
        wrap_at: int | None = None, center: bool = False, font: str | None = None):
    """Text whose line height is `size` px (on a 1080 px short side); `center` centres wrapped lines."""
    if not _REF:
        _REF.append(Text("Ag", font=FONT, font_size=48).height)
    fs = 48 * (size * 9 / 1080) / _REF[0]
    s = s.translate(_SUBSCRIPTS)
    s = wrap(s, wrap_at) if wrap_at else s
    kw = dict(font=font or FONT, font_size=fs, color=color or PAL["text"], line_spacing=0.9,
              weight=BOLD if bold else "NORMAL", slant=ITALIC if italic else "NORMAL")
    if center and "\n" in s:
        return Paragraph(*s.split("\n"), alignment="center", **kw)
    return Text(s, **kw)


def fit(mob, max_w: float, max_h: float):
    if mob.width > max_w:
        mob.scale_to_fit_width(max_w)
    if mob.height > max_h:
        mob.scale_to_fit_height(max_h)
    return mob


def num(v: float, decimals: int = 0) -> str:
    s = f"{v:,.{decimals}f}"
    if LANG == "vi":  # 1.234.567,8
        s = s.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return s


def chars(portrait: int, landscape: int) -> int:
    return portrait if PORTRAIT else landscape


class Base(Scene):
    """Timing helpers: `at(t)` waits until scene time t, `finish()` pads to the exact duration."""

    def setup(self):
        self.p = SPEC.get("params") or {}
        self.times = list(SPEC.get("times") or [])
        footer = SPEC.get("footer")
        self.bottom = BOX_BOTTOM
        if footer:
            f = fit(txt(footer, 30, PAL["muted"], wrap_at=chars(40, 80), center=True), BOX_W, BOX_H * 0.12)
            f.move_to([BOX_C[0], BOX_BOTTOM + f.height / 2, 0])
            self.add(f)
            self.bottom = BOX_BOTTOM + f.height + 0.25

    def now(self) -> float:
        return float(self.time)

    def at(self, t: float) -> None:
        dt = t - self.now()
        if dt > 1 / FPS:
            self.wait(dt)

    def rt(self, want: float, until: float | None = None) -> float:
        if until is None:
            return want
        return max(0.2, min(want, until - self.now() - 0.05))

    def spread(self, n: int, start: float = 0.6, end: float | None = None) -> list[float]:
        end = max(VOICE * 0.85, start + 0.5 * n) if end is None else end
        return [start + (end - start) * i / max(n, 1) for i in range(n)]

    def next_time(self, i: int) -> float | None:
        return self.times[i + 1] if i + 1 < len(self.times) else None

    def budget(self, n: int, want: float = 3.0, reserve: float = 0.4) -> float:
        """Run time for each of n drawings so all of them end before ~85% of the narration."""
        left = VOICE * 0.85 - self.now() - reserve * n
        return max(0.8, min(want, left / max(n, 1)))

    def finish(self) -> None:
        rest = DUR - self.now()
        if rest > 1 / FPS:
            self.wait(rest)

    def header(self, title: str | None):
        """Title at the top of the box (shown by `settle`); returns (mobject or None, y of the free area's top)."""
        if not title:
            return None, BOX_TOP
        t = fit(txt(title, 76, bold=True, wrap_at=chars(20, 40), center=True), BOX_W, BOX_H * 0.22)
        t.move_to([BOX_C[0], BOX_TOP - t.height / 2, 0])
        bar = Line(t.get_corner(DOWN + LEFT), t.get_corner(DOWN + RIGHT), color=acc(0), stroke_width=6)
        bar.shift(DOWN * 0.18)
        return VGroup(t, bar), bar.get_y() - 0.35

    def settle(self, head, content, gap: float = 0.5) -> None:
        """Centre header + content as one block in the box (short content moves up under its header), then
        show the header. Call once the content is laid out in `area()` and before it is animated."""
        if head is None:
            return
        lift = head.get_bottom()[1] - gap - content.get_top()[1]
        if lift > 0:
            content.shift(UP * lift)
        top, bottom = head.get_top()[1], min(content.get_bottom()[1], head.get_bottom()[1])
        d = (BOX_TOP + self.bottom) / 2 - (top + bottom) / 2
        d = max(min(d, BOX_TOP - top), self.bottom - bottom)
        head.shift(UP * d)
        content.shift(UP * d)
        self.play(FadeIn(head[0], shift=DOWN * 0.2), Create(head[1]), run_time=0.7)

    def area(self, top: float) -> tuple[np.ndarray, float, float]:
        """Centre, width, height of the free area between `top` and the bottom of the box."""
        h = top - self.bottom
        return np.array([BOX_C[0], self.bottom + h / 2, 0.0]), BOX_W, h


# ------------------------------------------------------------------ templates


class T_title(Base):
    def construct(self):
        p = self.p
        parts = []
        if p.get("kicker"):
            parts.append(txt(p["kicker"].upper(), 40, acc(0), bold=True))
        title = txt(p["title"], 130, bold=True, wrap_at=chars(12, 24), center=True)
        parts.append(title)
        if p.get("subtitle"):
            parts.append(txt(p["subtitle"], 58, PAL["muted"], wrap_at=chars(24, 48), center=True))
        g = VGroup(*parts).arrange(DOWN, buff=0.45)
        fit(g, BOX_W * 0.94, (BOX_TOP - self.bottom) * 0.9)
        g.move_to(self.area(BOX_TOP)[0])
        line = Line(title.get_corner(DOWN + LEFT), title.get_corner(DOWN + RIGHT), color=acc(1), stroke_width=8)
        line.shift(DOWN * 0.15)
        anims = []
        if p.get("kicker"):
            self.play(FadeIn(parts[0], shift=DOWN * 0.2), run_time=0.5)
        self.play(Write(title), run_time=min(1.4, max(0.6, DUR * 0.25)))
        anims.append(Create(line))
        if p.get("subtitle"):
            anims.append(FadeIn(parts[-1], shift=UP * 0.2))
        self.play(*anims, run_time=0.7)
        self.finish()


class T_bullets(Base):
    def construct(self):
        p = self.p
        head, top = self.header(p.get("title"))
        c, w, h = self.area(top)
        rows = []
        for i, it in enumerate(p["items"]):
            dot = Circle(radius=0.13, color=acc(i), fill_opacity=1).set_stroke(width=0)
            t = txt(it["text"], 62, wrap_at=chars(22, 44))
            rows.append(VGroup(dot, t).arrange(RIGHT, buff=0.35, aligned_edge=UP))
            dot.shift(DOWN * 0.12)
        g = VGroup(*rows).arrange(DOWN, buff=0.55, aligned_edge=LEFT)
        fit(g, w * 0.95, h * 0.95).move_to(c)
        self.settle(head, g)
        times = self.times or self.spread(len(rows))
        for i, row in enumerate(rows):
            self.at(times[i])
            dims = [r.animate.set_opacity(0.45) for r in rows[:i]]
            self.play(FadeIn(row, shift=RIGHT * 0.3), *dims, run_time=self.rt(0.5, self.next_time(i)))
        if len(rows) > 1:
            self.play(*[r.animate.set_opacity(1) for r in rows], run_time=0.4)
        self.finish()


class T_counter(Base):
    def construct(self):
        p = self.p
        c, w, h = self.area(BOX_TOP)
        label = fit(txt(p["label"], 64, PAL["muted"], wrap_at=chars(22, 44), center=True), w, h * 0.3)
        tracker = ValueTracker(float(p.get("start", 0)))
        dec = int(p.get("decimals", 0))

        def make():
            m = txt(f"{p.get('prefix', '')}{num(tracker.get_value(), dec)}{p.get('suffix', '')}", 170, acc(1),
                    bold=True)
            return fit(m, w, h * 0.45).move_to(c + UP * h * 0.05)

        number = always_redraw(make)
        label.next_to(number, UP, buff=0.5)
        self.play(FadeIn(label, shift=DOWN * 0.2), FadeIn(number), run_time=0.6)
        self.play(tracker.animate.set_value(float(p["end"])), run_time=min(2.8, max(1.0, VOICE * 0.5)),
                  rate_func=smooth)
        number.clear_updaters()
        self.play(Indicate(number, color=acc(1), scale_factor=1.08), run_time=0.6)
        if p.get("note"):
            note = fit(txt(p["note"], 36, PAL["muted"], wrap_at=chars(34, 70), center=True), w, h * 0.15)
            note.next_to(number, DOWN, buff=0.6)
            self.play(FadeIn(note), run_time=0.4)
        self.finish()


class T_bar_chart(Base):
    def construct(self):
        p = self.p
        head, top = self.header(p.get("title"))
        c, w, h = self.area(top)
        bars = p["bars"]
        vmax = max(b["value"] for b in bars)
        unit = p.get("unit", "")
        hi = p.get("highlight")
        dec = 0 if all(float(b["value"]).is_integer() for b in bars) else 1
        groups = []
        if PORTRAIT:  # horizontal bars, labels on the left
            n = len(bars)
            row_h = min(h / n, 1.1)
            label_w = w * 0.32
            max_len = w - label_w - w * 0.2
            for i, b in enumerate(bars):
                y = c[1] + row_h * n / 2 - row_h * (i + 0.5)  # rows centred in the area
                color = acc(1) if hi == i else acc(0)
                length = max(0.02, max_len * b["value"] / vmax)
                bar = Rectangle(width=length, height=row_h * 0.62, color=color, fill_opacity=0.9).set_stroke(width=0)
                bar.move_to([BOX_LEFT + label_w + length / 2, y, 0])
                lab = fit(txt(b["label"], 48), label_w * 0.92, row_h * 0.8)
                lab.move_to([BOX_LEFT + label_w - 0.15 - lab.width / 2, y, 0])
                val = fit(txt(f"{num(b['value'], dec)}{(' ' + unit) if unit else ''}", 44, PAL["muted"]),
                          w * 0.2, row_h * 0.7)
                val.next_to(bar, RIGHT, buff=0.15)
                groups.append((bar, lab, val, LEFT))
        else:  # vertical bars, labels below
            n = len(bars)
            col_w = w / n
            base_y = c[1] - h / 2 + h * 0.14
            max_len = h * 0.72
            for i, b in enumerate(bars):
                x = BOX_LEFT + col_w * (i + 0.5)
                color = acc(1) if hi == i else acc(0)
                length = max(0.02, max_len * b["value"] / vmax)
                bar = Rectangle(width=col_w * 0.6, height=length, color=color, fill_opacity=0.9).set_stroke(width=0)
                bar.move_to([x, base_y + length / 2, 0])
                lab = fit(txt(b["label"], 44), col_w * 0.95, h * 0.12).move_to([x, base_y - 0.35, 0])
                val = fit(txt(f"{num(b['value'], dec)}{(' ' + unit) if unit else ''}", 40, PAL["muted"]),
                          col_w * 0.95, h * 0.1)
                val.next_to(bar, UP, buff=0.12)
                groups.append((bar, lab, val, DOWN))
        self.settle(head, VGroup(*[VGroup(*g[:3]) for g in groups]))
        times = self.times or self.spread(len(groups))
        for i, (bar, lab, val, edge) in enumerate(groups):
            self.at(times[i])
            rt = self.rt(0.7, self.next_time(i))
            self.play(GrowFromEdge(bar, edge), FadeIn(lab), run_time=rt)
            self.add(val)
        if hi is not None:
            self.play(Indicate(groups[hi][0], color=acc(1), scale_factor=1.05), run_time=0.6)
        self.finish()


def _axis_range(values: list[float]) -> tuple[float, float]:
    lo, hi = min(values), max(values)
    if hi == lo:
        hi = lo + 1
    if lo >= 0 and lo < 0.35 * hi:
        lo = 0.0
    else:
        lo -= 0.1 * (hi - lo)
    return lo, hi + 0.08 * (hi - lo)


def _axes(c, w, h, x0, x1, y0, y1):
    ax = Axes(x_range=[x0, x1, (x1 - x0) / 5], y_range=[y0, y1, (y1 - y0) / 4], x_length=w * 0.8,
              y_length=h * 0.78, tips=False,
              axis_config={"color": PAL["muted"], "stroke_width": 3, "include_ticks": True})
    ax.move_to(c + RIGHT * w * 0.06)
    labels = VGroup()
    for v in (y0, (y0 + y1) / 2, y1):
        d = 0 if abs(y1 - y0) >= 10 else 2
        t = fit(txt(num(v, d), 34, PAL["muted"]), w * 0.15, h * 0.08)
        t.next_to(ax.c2p(x0, v), LEFT, buff=0.15)
        if v == y0:
            t.shift(UP * t.height * 0.6)
        labels.add(t)
    return ax, labels


class T_line_chart(Base):
    def construct(self):
        p = self.p
        head, top = self.header(p.get("title"))
        c, w, h = self.area(top)
        xs = p["x_labels"]
        n = len(xs)
        allv = [v for s in p["series"] for v in s["values"]]
        y0, y1 = _axis_range(allv)
        ax, ylabels = _axes(c, w, h * 0.88, 0, n - 1, y0, y1)
        ax.shift(UP * h * 0.05)
        step = max(1, math.ceil(n / chars(4, 8)))
        xlabels = VGroup(*[fit(txt(xs[i], 34, PAL["muted"]), w / 5, h * 0.08).next_to(ax.c2p(i, y0), DOWN, buff=0.2)
                           for i in range(0, n, step)])
        xlabels[0].align_to(ax.c2p(0, y0), LEFT)  # clear of the lowest y label
        self.settle(head, VGroup(ax, ylabels, xlabels))
        self.play(Create(ax), FadeIn(ylabels), FadeIn(xlabels), run_time=0.8)
        unit = p.get("unit", "")
        draw = self.budget(len(p["series"]))
        for i, s in enumerate(p["series"]):
            g = ax.plot_line_graph(list(range(n)), s["values"], line_color=acc(i), add_vertex_dots=False,
                                   stroke_width=7)
            end = s["values"][-1]
            dec = 0 if abs(end) >= 100 else 1
            tag = fit(txt(f"{s['name']}: {num(end, dec)}{(' ' + unit) if unit else ''}", 38, acc(i), bold=True),
                      w * 0.45, h * 0.08)
            tag.next_to(ax.c2p(n - 1, end), UP + LEFT * 0.3, buff=0.15)
            self.play(Create(g), run_time=draw)
            self.play(FadeIn(tag), run_time=0.3)
        self.finish()


def _curve(kind: str, a: float, b: float, c: float):
    return {
        "linear": lambda x: a * x + b,
        "quadratic": lambda x: a * x * x + b * x + c,
        "exponential": lambda x: a * math.exp(b * x),
        "compound": lambda x: a * (1 + b) ** x,
        "logistic": lambda x: a / (1 + math.exp(-b * (x - c))),
        "sine": lambda x: a * math.sin(b * x + c),
        "normal": lambda x: math.exp(-((x - b) ** 2) / (2 * a * a)) / (a * math.sqrt(2 * math.pi)),
    }[kind]


class T_function_graph(Base):
    def construct(self):
        p = self.p
        head, top = self.header(p.get("title"))
        c, w, h = self.area(top)
        x0, x1 = p["x_range"]
        fns = [_curve(cv["kind"], cv["a"], cv["b"], cv["c"]) for cv in p["curves"]]
        samples = [f(x) for f in fns for x in np.linspace(x0, x1, 120)]
        samples = [v for v in samples if math.isfinite(v)]
        y0, y1 = _axis_range(samples)
        ax, ylabels = _axes(c, w, h * 0.9, x0, x1, y0, y1)
        xl = VGroup(fit(txt(num(x0), 34, PAL["muted"]), w / 5, h * 0.08).next_to(ax.c2p(x0, y0), DOWN, buff=0.2),
                    fit(txt(num(x1) + (f" {p['x_label']}" if p.get("x_label") else ""), 34, PAL["muted"]), w / 3,
                        h * 0.08).next_to(ax.c2p(x1, y0), DOWN, buff=0.2))
        extra = []
        if p.get("y_label"):
            extra.append(fit(txt(p["y_label"], 34, PAL["muted"]), w / 3, h * 0.08).next_to(ax.c2p(x0, y1), UP,
                                                                                         buff=0.2))
        self.settle(head, VGroup(ax, ylabels, xl, *extra))
        self.play(Create(ax), FadeIn(ylabels), FadeIn(xl), *[FadeIn(e) for e in extra], run_time=0.8)
        draw = self.budget(len(fns))
        tags: list = []
        for i, (f, cv) in enumerate(zip(fns, p["curves"], strict=True)):
            g = ax.plot(lambda x, f=f: min(max(f(x), y0), y1), x_range=[x0, x1], color=acc(i), stroke_width=7)
            self.play(Create(g), run_time=draw)
            if cv.get("label"):
                end = min(max(f(x1), y0), y1)
                t = fit(txt(f"{cv['label']}: {num(f(x1), 0 if abs(f(x1)) >= 100 else 2)}", 38, acc(i), bold=True),
                        w * 0.5, h * 0.08)
                pt, top = ax.c2p(x1, end), ax.c2p(x1, y1)[1]
                t.next_to(pt, UP, buff=0.15).align_to(pt, RIGHT)  # above the curve's end
                if t.get_top()[1] > top:  # no room above: left of the end, inside the axes
                    t.next_to(pt, LEFT, buff=0.2)
                    if t.get_top()[1] > top:
                        t.shift(DOWN * (t.get_top()[1] - top))
                for o in tags:  # don't stack labels of curves that end close together
                    if abs(t.get_y() - o.get_y()) < (t.height + o.height) / 2 + 0.05:
                        t.next_to(o, DOWN, buff=0.1, aligned_edge=RIGHT)
                tags.append(t)
                self.play(FadeIn(t), run_time=0.3)
        self.finish()


class T_timeline(Base):
    def construct(self):
        p = self.p
        head, top = self.header(p.get("title"))
        c, w, h = self.area(top)
        ev = p["events"]
        n = len(ev)
        items = []
        if PORTRAIT:
            x = c[0] - w * 0.38
            gap = min((h - 0.4) / n, 2.2)  # a few events stay together instead of spreading over the box
            y_top = c[1] + gap * n / 2
            line = Line([x, y_top, 0], [x, y_top - gap * n, 0], color=PAL["muted"], stroke_width=4)
            for i, e in enumerate(ev):
                y = y_top - gap * (i + 0.5)
                dot = Dot([x, y, 0], radius=0.14, color=acc(i))
                year = fit(txt(e["year"], 54, acc(i), bold=True), w * 0.7, gap * 0.45)
                lab = fit(txt(e["label"], 46, wrap_at=chars(24, 40)), w * 0.78, gap * 0.5)
                g = VGroup(year, lab).arrange(DOWN, buff=0.08, aligned_edge=LEFT)
                g.move_to([x + 0.35 + g.width / 2, y, 0])
                items.append((dot, g))
        else:
            y = c[1]
            line = Line([c[0] - w / 2 + 0.2, y, 0], [c[0] + w / 2 - 0.2, y, 0], color=PAL["muted"], stroke_width=4)
            gap = (w - 0.4) / n
            for i, e in enumerate(ev):
                x = c[0] - w / 2 + 0.2 + gap * (i + 0.5)
                dot = Dot([x, y, 0], radius=0.14, color=acc(i))
                year = fit(txt(e["year"], 50, acc(i), bold=True), gap * 0.95, h * 0.12)
                lab = fit(txt(e["label"], 40, wrap_at=14, center=True), gap * 0.95, h * 0.3)
                g = VGroup(year, lab).arrange(DOWN, buff=0.1)
                side = UP if i % 2 == 0 else DOWN
                g.next_to(dot, side, buff=0.3)
                items.append((dot, g))
        self.settle(head, VGroup(line, *[VGroup(d, g) for d, g in items]))
        self.play(Create(line), run_time=0.6)
        times = self.times or self.spread(n)
        for i, (dot, g) in enumerate(items):
            self.at(times[i])
            self.play(GrowFromCenter(dot), FadeIn(g, shift=RIGHT * 0.2 if PORTRAIT else UP * 0.1),
                      run_time=self.rt(0.6, self.next_time(i)))
        self.finish()


class T_compare(Base):
    def construct(self):
        p = self.p
        head, top = self.header(p.get("title"))
        c, w, h = self.area(top)
        verdict_h = h * 0.16 if p.get("verdict") else 0
        col_w = w * 0.46
        max_h = h - verdict_h - 0.2
        sides = []
        for k, side in enumerate((p["left"], p["right"])):
            title = fit(txt(side["title"], 58, acc(k), bold=True), col_w * 0.9, max_h * 0.15)
            ps = VGroup(*[txt("• " + s, 42, wrap_at=chars(13, 26)) for s in side["points"]])
            ps.arrange(DOWN, buff=0.35, aligned_edge=LEFT)
            fit(ps, col_w * 0.88, max_h * 0.7)
            sides.append((title, ps))
        col_h = min(max_h, max(t.height + ps.height for t, ps in sides) + 1.4)  # panels as tall as their points
        block = col_h + (verdict_h + 0.2 if verdict_h else 0)
        y = c[1] + block / 2 - col_h / 2
        cols, points = [], []
        for k, (title, ps) in enumerate(sides):
            x = c[0] + (-1 if k == 0 else 1) * (w / 2 - col_w / 2)
            panel = RoundedRectangle(width=col_w, height=col_h, corner_radius=0.25, color=acc(k),
                                     fill_opacity=0.08, stroke_width=4).move_to([x, y, 0])
            title.move_to([x, y + col_h / 2 - 0.25 - title.height / 2, 0])
            ps.next_to(title, DOWN, buff=0.4)
            cols.append(VGroup(panel, title))
            points.append(list(ps))
        badge = Circle(radius=0.42, color=PAL["muted"], stroke_width=3, fill_color=PAL["background"], fill_opacity=1)
        vs = VGroup(badge, fit(txt("VS", 44, PAL["text"], bold=True), 0.56, 0.5)).move_to([c[0], y, 0])
        vs.set_z_index(2)
        verdict = None
        if p.get("verdict"):
            verdict = fit(txt(p["verdict"], 48, acc(1), bold=True, wrap_at=chars(28, 56), center=True), w, verdict_h)
            verdict.move_to([c[0], y - col_h / 2 - 0.2 - verdict_h / 2, 0])
        self.settle(head, VGroup(*cols, *[m for pts in points for m in pts], vs, *([verdict] if verdict else [])))
        steps = [cols[0], *points[0], cols[1], *points[1]]
        times = self.spread(len(steps))
        for i, m in enumerate(steps):
            self.at(times[i])
            extra = [FadeIn(vs)] if m is cols[1] else []
            nxt = times[i + 1] if i + 1 < len(times) else None
            self.play(FadeIn(m, shift=UP * 0.15), *extra, run_time=self.rt(0.5, nxt))
        if verdict:
            self.play(Write(verdict), run_time=0.8)
        self.finish()


class T_formula(Base):
    def construct(self):
        p = self.p
        head, top = self.header(p.get("title"))
        c, w, h = self.area(top)
        if SPEC.get("latex") and p.get("tex"):
            f = MathTex(p["tex"], color=PAL["text"])
        else:
            f = txt(p["text"], 120, bold=True, font=_math_font())
        fit(f, w * 0.9, h * 0.3)
        legend = VGroup()
        for i, lg in enumerate(p.get("legend") or []):
            row = VGroup(txt(lg["symbol"], 58, acc(i), bold=True), txt("— " + lg["meaning"], 50, PAL["text"],
                                                                         wrap_at=chars(22, 44)))
            row.arrange(RIGHT, buff=0.3)
            legend.add(row)
        if len(legend):
            legend.arrange(DOWN, buff=0.35, aligned_edge=LEFT)
            fit(legend, w * 0.9, h * 0.5)
        g = VGroup(f, legend).arrange(DOWN, buff=0.9) if len(legend) else VGroup(f)
        g.move_to(c)
        self.settle(head, g)
        box = SurroundingRectangle(f, color=acc(1), buff=0.3, corner_radius=0.15, stroke_width=5)
        self.play(Write(f), run_time=min(1.6, max(0.8, DUR * 0.25)))
        self.play(Create(box), run_time=0.5)
        times = self.spread(len(legend), start=self.now() + 0.2)
        for i, row in enumerate(legend):
            self.at(times[i])
            self.play(FadeIn(row, shift=RIGHT * 0.2), run_time=0.45)
        self.finish()


class T_process(Base):
    def construct(self):
        p = self.p
        head, top = self.header(p.get("title"))
        c, w, h = self.area(top)
        n = len(p["steps"])
        boxes = []
        for i, st in enumerate(p["steps"]):
            t = txt(st["text"], 50, wrap_at=chars(18, 14), center=True)
            r = RoundedRectangle(width=t.width + 0.6, height=t.height + 0.5, corner_radius=0.2, color=acc(i),
                                 fill_opacity=0.12, stroke_width=4)
            boxes.append(VGroup(r, t))
        g = VGroup(*boxes).arrange(DOWN if PORTRAIT else RIGHT, buff=0.7)
        fit(g, w * (0.8 if p.get("loop") else 0.95), h * 0.92).move_to(c + (LEFT * w * 0.06 if p.get("loop") else 0))
        self.settle(head, g)
        arrows = []
        for a, b in zip(boxes, boxes[1:], strict=False):
            if PORTRAIT:
                arrows.append(Arrow(a.get_bottom(), b.get_top(), buff=0.08, color=PAL["muted"], stroke_width=5))
            else:
                arrows.append(Arrow(a.get_right(), b.get_left(), buff=0.08, color=PAL["muted"], stroke_width=5))
        times = self.times or self.spread(n)
        for i, b in enumerate(boxes):
            self.at(times[i])
            anims = [FadeIn(b, shift=(DOWN if PORTRAIT else RIGHT) * 0.2)]
            if i > 0:
                anims.insert(0, GrowArrow(arrows[i - 1]))
            self.play(*anims, run_time=self.rt(0.6, self.next_time(i)))
        if p.get("loop") and n > 1:
            start = boxes[-1].get_right() if PORTRAIT else boxes[-1].get_bottom()
            end = boxes[0].get_right() if PORTRAIT else boxes[0].get_bottom()
            loop = CurvedArrow(start, end, angle=math.pi / 2 if PORTRAIT else -math.pi / 2, color=acc(1),
                               stroke_width=5)
            self.play(Create(loop), run_time=0.8)
        self.finish()


class T_quote(Base):
    def construct(self):
        p = self.p
        c, w, h = self.area(BOX_TOP)
        mark = txt("“", 260, acc(1), bold=True)
        body = txt(p["text"], 66, italic=True, wrap_at=chars(22, 42), center=True)
        who = txt("— " + p["author"] + (f", {p['context']}" if p.get("context") else ""), 46, PAL["muted"])
        g = VGroup(mark, body, who).arrange(DOWN, buff=0.4, aligned_edge=LEFT)
        fit(g, w * 0.92, h * 0.92).move_to(c)
        self.play(FadeIn(mark, shift=DOWN * 0.3), run_time=0.4)
        self.play(FadeIn(body, lag_ratio=0.02), run_time=min(3.0, max(1.0, VOICE * 0.6)))
        self.play(FadeIn(who, shift=UP * 0.15), run_time=0.5)
        self.finish()


class T_photo(Base):
    """A credited photo (file prepared by the images stage) with a caption and a slow push-in."""

    def construct(self):
        p = self.p
        c, w, h = self.area(BOX_TOP)
        cap = None
        if p.get("caption"):
            cap = fit(txt(p["caption"], 56, bold=True, wrap_at=chars(24, 48), center=True), w, h * 0.16)
        credit = fit(txt(p.get("credit") or "Wikimedia Commons", 26, PAL["muted"], wrap_at=chars(52, 104),
                         center=True), w, h * 0.08)
        room = h - credit.height - 0.3 - ((cap.height + 0.3) if cap else 0)
        img = ImageMobject(SPEC["image"])
        img.scale_to_fit_width(w * 0.94)
        if img.height > room * 0.94:
            img.scale_to_fit_height(room * 0.94)
        frame = SurroundingRectangle(img, color=acc(0), buff=0.04, stroke_width=4)
        pic = Group(img, frame)
        Group(pic, *([cap] if cap else []), credit).arrange(DOWN, buff=0.3).move_to(c)
        self.play(FadeIn(img, scale=0.96), Create(frame), run_time=0.8)
        self.play(FadeIn(credit), *([FadeIn(cap, shift=UP * 0.15)] if cap else []), run_time=0.5)
        rest = DUR - self.now() - 0.05
        if rest > 0.5:  # a slow push-in keeps the picture alive while the narration runs
            self.play(pic.animate.scale(1.03), run_time=rest, rate_func=linear)
        self.finish()


__all__ = [n for n in dir() if n.startswith("T_")] + ["Base", "SPEC"]
