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
    ORIGIN,
    RIGHT,
    UP,
    AddTextLetterByLetter,
    AnnularSector,
    Arc,
    Arrow,
    Axes,
    Circle,
    Create,
    CurvedArrow,
    DashedLine,
    Dot,
    Ellipse,
    FadeIn,
    Group,
    GrowArrow,
    GrowFromCenter,
    GrowFromEdge,
    ImageMobject,
    Indicate,
    Intersection,
    Line,
    MathTex,
    Paragraph,
    Polygon,
    Rectangle,
    RoundedRectangle,
    Scene,
    SurroundingRectangle,
    Text,
    Transform,
    ValueTracker,
    VGroup,
    VMobject,
    Write,
    always_redraw,
    config,
    linear,
    rotate_vector,
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
    return _installed_font(("Cambria Math", "Segoe UI Symbol", "DejaVu Sans"))


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


def _installed_font(candidates: tuple[str, ...]) -> str:
    try:
        import manimpango
        have = set(manimpango.list_fonts())
    except Exception:  # noqa: BLE001 - any failure -> keep the UI font
        return FONT
    return next((f for f in candidates if f in have), FONT)


def starfield():
    """Small fixed stars (same layout for a scene on every render); a few of them twinkle."""
    rng = np.random.default_rng(sum(ord(ch) for ch in str(SPEC.get("scene_id", ""))) + 7)
    stars = VGroup()
    for _ in range(int(110 * FW * FH / 144)):
        d = Dot([rng.uniform(-FW / 2, FW / 2), rng.uniform(-FH / 2, FH / 2), 0], radius=rng.uniform(0.008, 0.028),
                color="#FFFFFF")
        d.set_opacity(rng.uniform(0.15, 0.7))
        stars.add(d)
    clock = [0.0]

    def twinkle(group, dt):
        clock[0] += dt
        for k, s in enumerate(group[:20]):
            s.set_opacity(0.25 + 0.45 * (0.5 + 0.5 * math.sin(clock[0] * (1.3 + k % 4 * 0.4) + k)))

    stars.add_updater(twinkle)
    stars.set_z_index(-10)
    return stars


class Base(Scene):
    """Timing helpers: `at(t)` waits until scene time t, `finish()` pads to the exact duration."""

    def setup(self):
        self.p = SPEC.get("params") or {}
        self.times = list(SPEC.get("times") or [])
        if SPEC.get("backdrop") == "stars":
            self.add(starfield())
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
        self.show_head(head)

    def show_head(self, head) -> None:
        if head is not None:
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


# ------------------------------------------------------------------ news style: flat icons + cards

# flat-illustration colours (fixed so an icon looks the same in every palette)
I_BLUE, I_LIGHT, I_GOLD, I_GOLD_D = "#3B82F6", "#93C5FD", "#F4B942", "#B7791F"
I_ORANGE, I_GREEN, I_RED, I_WHITE = "#FF7A1A", "#22C55E", "#EF4444", "#F8FAFC"
I_GREY, I_DARK, I_SLATE = "#94A3B8", "#0F172A", "#1F2937"


def _fill(m, color: str, stroke: str | None = None, width: float = 3):
    return m.set_fill(color, opacity=1).set_stroke(stroke or color, width=width if stroke else 0)


def _poly(*pts, color: str, stroke: str | None = None):
    return _fill(Polygon(*[[x, y, 0] for x, y in pts]), color, stroke)


def _solar_panel(w: float, h: float):
    g = VGroup(_fill(Rectangle(width=w, height=h), I_BLUE, I_LIGHT))
    for k in (1, 2):
        g.add(Line([-w / 2 + w * k / 3, -h / 2, 0], [-w / 2 + w * k / 3, h / 2, 0], color=I_LIGHT, stroke_width=2))
    g.add(Line([-w / 2, 0, 0], [w / 2, 0, 0], color=I_LIGHT, stroke_width=2))
    return g


def icon_satellite():
    body = _fill(RoundedRectangle(width=0.7, height=0.8, corner_radius=0.08), I_GOLD, I_GOLD_D)
    win = _fill(Rectangle(width=0.36, height=0.24), I_DARK, I_GOLD_D, 2).shift(UP * 0.08)
    left = _solar_panel(1.1, 0.55).next_to(body, LEFT, buff=0.25)
    right = _solar_panel(1.1, 0.55).next_to(body, RIGHT, buff=0.25)
    struts = VGroup(Line(left.get_right(), body.get_left(), color=I_GREY, stroke_width=5),
                    Line(body.get_right(), right.get_left(), color=I_GREY, stroke_width=5))
    mast = Line(body.get_top(), body.get_top() + UP * 0.3, color=I_GREY, stroke_width=4)
    tip = Dot(mast.get_end(), radius=0.06, color=I_WHITE)
    return VGroup(struts, left, right, body, win, mast, tip)


def icon_planet():
    glow = Circle(radius=1.12).set_stroke(I_LIGHT, width=10, opacity=0.3)
    ball = _fill(Circle(radius=1.0), I_BLUE, I_LIGHT)
    land = VGroup(_fill(Ellipse(width=0.75, height=0.4), I_GREEN).move_to([-0.3, 0.32, 0]),
                  _fill(Ellipse(width=0.55, height=0.36), I_GREEN).move_to([0.35, -0.35, 0]),
                  _fill(Ellipse(width=0.25, height=0.15), I_GREEN).move_to([0.5, 0.42, 0]))
    return VGroup(glow, ball, land)


def icon_server():
    racks = VGroup()
    for _ in range(3):
        r = _fill(RoundedRectangle(width=2.0, height=0.55, corner_radius=0.1), I_SLATE, I_GREY)
        bars = VGroup(*[Line([0, 0, 0], [0.5, 0, 0], color=I_WHITE, stroke_width=4) for _ in range(2)])
        bars.arrange(DOWN, buff=0.12).move_to(r.get_left() + RIGHT * 0.5)
        led = Dot(r.get_right() + LEFT * 0.3, radius=0.07, color=I_GREEN)
        racks.add(VGroup(r, bars, led))
    return racks.arrange(DOWN, buff=0.12)


def icon_chip():
    pins = VGroup()
    for k in range(4):
        o = -0.45 + 0.3 * k
        pins.add(Line([o, 0.65, 0], [o, 0.9, 0]), Line([o, -0.65, 0], [o, -0.9, 0]),
                 Line([0.65, o, 0], [0.9, o, 0]), Line([-0.65, o, 0], [-0.9, o, 0]))
    pins.set_stroke(I_LIGHT, width=5)
    body = _fill(RoundedRectangle(width=1.3, height=1.3, corner_radius=0.12), I_DARK, I_LIGHT, 5)
    core = RoundedRectangle(width=0.75, height=0.75, corner_radius=0.08).set_stroke(I_LIGHT, width=3)
    label = fit(txt("AI", 60, I_LIGHT, bold=True), 0.55, 0.4)
    return VGroup(pins, body, core, label)


def icon_rocket():
    flame = _poly((-0.2, -0.75), (0.2, -0.75), (0, -1.25), color=I_ORANGE)
    fins = VGroup(_poly((-0.3, -0.2), (-0.62, -0.75), (-0.3, -0.6), color=I_RED),
                  _poly((0.3, -0.2), (0.62, -0.75), (0.3, -0.6), color=I_RED))
    body = _fill(RoundedRectangle(width=0.6, height=1.4, corner_radius=0.25), I_WHITE, I_GREY).shift(DOWN * 0.05)
    nose = _poly((-0.3, 0.5), (0.3, 0.5), (0, 1.15), color=I_RED)
    win = _fill(Circle(radius=0.14), I_BLUE, I_GREY).shift(UP * 0.2)
    return VGroup(flame, fins, body, nose, win)


def icon_phone():
    case = _fill(RoundedRectangle(width=0.95, height=1.8, corner_radius=0.15), I_DARK, I_GREY, 5)
    screen = _fill(Rectangle(width=0.78, height=1.38), I_BLUE).shift(UP * 0.07)
    pin = _fill(Circle(radius=0.14), I_RED).move_to(screen.get_center() + UP * 0.1)
    tail = _poly((-0.1, 0.0), (0.1, 0.0), (0, -0.22), color=I_RED).move_to(pin.get_center() + DOWN * 0.15)
    return VGroup(case, screen, tail, pin, Dot(case.get_bottom() + UP * 0.11, radius=0.04, color=I_GREY))


def icon_laptop():
    screen = _fill(RoundedRectangle(width=1.9, height=1.2, corner_radius=0.08), I_DARK, I_GREY, 5)
    inner = _fill(Rectangle(width=1.65, height=0.95), I_BLUE)
    base = _poly((-1.2, -0.7), (1.2, -0.7), (1.0, -0.88), (-1.0, -0.88), color=I_GREY)
    return VGroup(screen, inner, base)


def icon_cloud():
    return VGroup(*[_fill(m, I_WHITE) for m in (
        Circle(radius=0.45).move_to([-0.55, -0.05, 0]), Circle(radius=0.6).move_to([0, 0.22, 0]),
        Circle(radius=0.45).move_to([0.55, -0.05, 0]), Rectangle(width=1.1, height=0.5).move_to([0, -0.25, 0]))])


def icon_bolt():
    return _poly((0.15, 1), (-0.55, -0.1), (-0.05, -0.1), (-0.25, -1), (0.55, 0.2), (0.05, 0.2), color=I_GOLD,
                 stroke=I_ORANGE)


def icon_sun():
    rays = VGroup(*[Line([0.8 * math.cos(a), 0.8 * math.sin(a), 0], [1.05 * math.cos(a), 1.05 * math.sin(a), 0],
                         color=I_GOLD, stroke_width=7) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)])
    return VGroup(rays, _fill(Circle(radius=0.6), I_GOLD, I_ORANGE))


def icon_dish():
    bowl = _fill(AnnularSector(inner_radius=0, outer_radius=0.75, angle=math.pi, start_angle=math.pi), I_WHITE,
                 I_GREY).rotate(-math.pi / 6, about_point=ORIGIN)
    feed = Line(ORIGIN, rotate_vector(UP * 0.55, -math.pi / 6), color=I_GREY, stroke_width=4)
    stand = Line([0, -0.45, 0], [0, -0.95, 0], color=I_GREY, stroke_width=6)
    base = _fill(Rectangle(width=0.9, height=0.12), I_GREY).move_to([0, -1.0, 0])
    return VGroup(stand, base, bowl, feed, Dot(feed.get_end(), radius=0.07, color=I_RED))


def icon_robot():
    head = _fill(RoundedRectangle(width=1.3, height=1.0, corner_radius=0.2), "#CBD5E1", I_GREY)
    eyes = VGroup(*[_fill(Circle(radius=0.13), I_BLUE).move_to([x, 0.08, 0]) for x in (-0.3, 0.3)])
    mouth = Line([-0.25, -0.25, 0], [0.25, -0.25, 0], color=I_DARK, stroke_width=5)
    ant = Line([0, 0.5, 0], [0, 0.8, 0], color=I_GREY, stroke_width=4)
    ears = VGroup(*[_fill(Rectangle(width=0.12, height=0.35), I_GREY).move_to([x, 0, 0]) for x in (-0.71, 0.71)])
    return VGroup(ant, Dot([0, 0.82, 0], radius=0.08, color=I_RED), ears, head, eyes, mouth)


def icon_lock():
    shackle = Arc(radius=0.38, start_angle=0, angle=math.pi).set_stroke(I_GREY, width=12).shift(UP * 0.55)
    legs = VGroup(Line([-0.38, 0.55, 0], [-0.38, 0.3, 0]), Line([0.38, 0.55, 0], [0.38, 0.3, 0]))
    legs.set_stroke(I_GREY, width=12)
    body = _fill(RoundedRectangle(width=1.2, height=0.95, corner_radius=0.12), I_GOLD, I_GOLD_D).shift(DOWN * 0.15)
    hole = VGroup(_fill(Circle(radius=0.1), I_DARK).shift(DOWN * 0.08),
                  _fill(Rectangle(width=0.07, height=0.25), I_DARK).shift(DOWN * 0.25))
    return VGroup(shackle, legs, body, hole)


def icon_coin():
    return VGroup(_fill(Circle(radius=0.9), I_GOLD, I_GOLD_D, 6), Circle(radius=0.72).set_stroke(I_GOLD_D, 3),
                  fit(txt("$", 110, I_GOLD_D, bold=True), 0.6, 0.9))


def icon_user():
    head = _fill(Circle(radius=0.38), I_LIGHT).shift(UP * 0.45)
    body = _fill(AnnularSector(inner_radius=0, outer_radius=0.75, angle=math.pi), I_BLUE).shift(DOWN * 0.75)
    return VGroup(body, head)


def icon_document():
    page = _fill(RoundedRectangle(width=1.3, height=1.7, corner_radius=0.08), I_WHITE, I_GREY)
    lines = VGroup(Line([-0.4, 0.5, 0], [0.4, 0.5, 0], color=I_BLUE, stroke_width=8),
                   *[Line([-0.45, y, 0], [0.45, y, 0], color=I_GREY, stroke_width=5) for y in (0.15, -0.1, -0.35)])
    return VGroup(page, lines)


ICON = {"satellite": icon_satellite, "planet": icon_planet, "server": icon_server, "chip": icon_chip,
        "rocket": icon_rocket, "phone": icon_phone, "laptop": icon_laptop, "cloud": icon_cloud, "bolt": icon_bolt,
        "sun": icon_sun, "dish": icon_dish, "robot": icon_robot, "lock": icon_lock, "coin": icon_coin,
        "user": icon_user, "document": icon_document}


def horizon(c, w: float, h: float):
    """The top of a big planet filling the lower part of the area, with a soft atmosphere line."""
    r = FW * 1.15
    top = c[1] - h * 0.12
    centre = np.array([c[0], top - r, 0.0])
    floor = -FH / 2  # down to the frame edge, dark at the bottom so the captions stay readable
    clip = Rectangle(width=FW, height=top - floor + 0.1).move_to([0, (top + floor) / 2, 0])
    land = Intersection(Circle(radius=r).move_to(centre), clip)
    land.set_fill(["#050B1F", "#0B1F55", "#2563EB"], opacity=1).set_stroke(width=0)
    land.set_sheen_direction(UP)
    glow = VGroup()
    for k, op in enumerate((0.55, 0.3, 0.15)):
        rr = r + 0.06 + 0.1 * k
        a = math.asin(max(-1.0, min(1.0, (floor - centre[1]) / rr)))
        glow.add(Arc(radius=rr, start_angle=a, angle=math.pi - 2 * a, arc_center=centre)
                 .set_stroke(I_LIGHT, width=8 - 2 * k, opacity=op))
    return VGroup(land, glow), top


class T_icons(Base):
    def construct(self):
        p = self.p
        head, top = self.header(p.get("title"))
        c, w, h = self.area(top)
        items = p["items"]
        n = len(items)
        note = fit(txt(p["note"], 150, acc(0), bold=True), w * 0.6, h * 0.2) if p.get("note") else None
        planet, ground = (None, None)
        if p.get("scene") == "planet":
            planet, ground = horizon(c, w, h)
        size = min(w / (n + 0.4) * 0.85, h * (0.3 if planet else 0.42))
        icons, labels = [], []
        for i, it in enumerate(items):
            sky = planet is not None and (i == 0 or n == 1)
            ic = fit(ICON[it["icon"]](), size * (2.0 if sky else 1.4), size * (1.15 if sky else 1))
            if planet is not None and not sky:  # on the ground, the first one in the sky
                x = c[0] + (w * 0.22 if n == 2 else (-1 if i == 1 else 1) * w * 0.28)
                ic.move_to([x, ground + ic.height / 2 + 0.05, 0])
            elif sky:
                x = c[0] - (w * 0.16 if n == 2 else 0)
                ic.move_to([x, ground + (top - ground) * 0.5, 0])
            else:
                ic.move_to([c[0] + (i - (n - 1) / 2) * w / n, c[1] + (h * 0.08 if note else 0), 0])
            icons.append(ic)
            lab = None
            if it.get("label"):
                lab = fit(txt(it["label"], 58, bold=True, wrap_at=chars(16, 24), center=True), w / n * 0.95,
                          h * 0.14)
                lab.next_to(ic, UP if sky else DOWN, buff=0.25)
            labels.append(lab)
        if planet is None:  # one baseline for the labels of a row
            low = min(ic.get_bottom()[1] for ic in icons) - 0.25
            for lab in labels:
                if lab is not None:
                    lab.move_to([lab.get_x(), low - lab.height / 2, 0])
        links = []
        for a, b in zip(icons, icons[1:], strict=False):
            link = p.get("link", "none")
            if link == "arrow" and planet is None:
                start, end = a.get_right() + RIGHT * 0.15, b.get_left() + LEFT * 0.15
                links.append(Arrow(start, end, buff=0, color=PAL["muted"], stroke_width=6,
                                   max_tip_length_to_length_ratio=0.4) if end[0] - start[0] > 0.3 else None)
            elif link == "arrow":
                links.append(Arrow(a.get_center(), b.get_center(), buff=size * 0.6, color=PAL["muted"],
                                   stroke_width=6))
            elif link == "beam":
                links.append(DashedLine(a.get_center(), b.get_center(), buff=size * 0.45, dash_length=0.15,
                                        color=acc(0), stroke_width=5))
            elif link in ("vs", "plus"):
                mark = txt("VS" if link == "vs" else "+", 70, acc(0), bold=True)
                links.append(mark.move_to((a.get_center() + b.get_center()) / 2))
            else:
                links.append(None)
        if note is not None:
            low = min(m.get_bottom()[1] for m in icons + [lab for lab in labels if lab])
            note.next_to([c[0], low, 0], DOWN, buff=0.4)
        content = Group(*icons, *[m for m in labels + links if m is not None], *([note] if note else []))
        if planet is None:
            self.settle(head, content)
        else:
            self.show_head(head)
            self.play(FadeIn(planet, shift=UP * 0.4), run_time=0.8)
        times = self.times or self.spread(n, start=0.4)
        for i, ic in enumerate(icons):
            self.at(times[i])
            anims = [GrowFromCenter(ic)]
            if labels[i] is not None:
                anims.append(FadeIn(labels[i], shift=UP * 0.15))
            if i > 0 and links[i - 1] is not None:
                anims.append(Create(links[i - 1]) if isinstance(links[i - 1], (Arrow, DashedLine))
                             else FadeIn(links[i - 1], scale=1.3))
            self.play(*anims, run_time=self.rt(0.6, self.next_time(i)))
        for k, ic in enumerate(icons):  # a gentle float keeps the picture alive
            if planet is not None and n > 1 and k > 0:
                continue
            y0, t0 = ic.get_y(), self.now()

            def bob(m, y0=y0, k=k, t0=t0):
                m.set_y(y0 + 0.08 * math.sin((self.now() - t0) * 2.2 + k))

            ic.add_updater(bob)
        for ln in links:
            if isinstance(ln, DashedLine):  # a pulse travelling along the beam
                pulse = Dot(radius=0.09, color=acc(0))
                t0 = self.now()

                def run(d, a=ln.get_start(), b=ln.get_end(), t0=t0):
                    d.move_to(a + (b - a) * (((self.now() - t0) / 1.2) % 1))

                pulse.add_updater(run)
                self.add(pulse)
        if note is not None:
            self.play(FadeIn(note, scale=1.4), run_time=0.5)
        self.finish()


class T_terminal(Base):
    def construct(self):
        p = self.p
        c, w, h = self.area(BOX_TOP)
        mono = _installed_font(("Consolas", "Cascadia Mono", "DejaVu Sans Mono", "Courier New"))
        width = w * 0.96
        cols = chars(26, 56)
        prompt = txt("› " + p["prompt"], 52, PAL["muted"], wrap_at=cols, font=mono)
        parts = [prompt]
        speaker = None
        if p.get("speaker"):
            speaker = txt(p["speaker"] + ":", 54, acc(3), bold=True, font=mono)
            parts.append(speaker)
        resp = txt(p["response"], 66, wrap_at=cols, font=mono)
        parts.append(resp)
        body = VGroup(*parts).arrange(DOWN, buff=0.4, aligned_edge=LEFT)
        fit(body, width - 0.9, h * 0.8)
        bar_h = 0.55
        win_h = min(h, max(h * 0.5, body.height + bar_h + 1.0))
        win = _fill(RoundedRectangle(width=width, height=win_h, corner_radius=0.2), "#0B1220", "#334155").move_to(c)
        bar = _fill(Rectangle(width=width - 0.04, height=bar_h), "#1E293B")
        bar.move_to(win.get_top() + DOWN * (bar_h / 2 + 0.02))
        dots = VGroup(*[Dot(radius=0.08, color=col) for col in ("#FF5F57", "#FEBC2E", "#28C840")])
        dots.arrange(RIGHT, buff=0.14).move_to(bar.get_left() + RIGHT * 0.45)
        title = fit(txt(p.get("window") or "Terminal", 34, PAL["muted"], font=mono), width * 0.6, bar_h * 0.6)
        title.move_to(bar)
        body.next_to(bar, DOWN, buff=0.5).align_to(win, LEFT).shift(RIGHT * 0.45)
        self.play(FadeIn(VGroup(win, bar, dots, title), shift=UP * 0.3), run_time=0.6)
        self.play(AddTextLetterByLetter(prompt), run_time=min(1.4, max(0.5, len(p["prompt"]) / 60)))
        if speaker is not None:
            self.play(FadeIn(speaker), run_time=0.3)
        self.play(AddTextLetterByLetter(resp), run_time=self.budget(1, want=max(1.0, len(p["response"]) / 30)))
        cursor = _fill(Rectangle(width=0.18, height=resp[-1].height * 1.3 if len(resp) else 0.4), acc(3))
        cursor.next_to(resp[-1], RIGHT, buff=0.08, aligned_edge=DOWN)
        t0 = self.now()
        cursor.add_updater(lambda m: m.set_opacity(1 if int((self.now() - t0) * 2) % 2 == 0 else 0))
        self.add(cursor)
        self.finish()


def _tick(at, size: float):
    m = VMobject().set_points_as_corners([at + np.array([-0.45, 0.0, 0]) * size,
                                          at + np.array([-0.12, -0.32, 0]) * size,
                                          at + np.array([0.48, 0.38, 0]) * size])
    return m.set_stroke(I_WHITE, width=7)


class T_checklist(Base):
    def construct(self):
        p = self.p
        stamp_h = 0.0
        stamp = None
        if p.get("title"):
            word = txt(p["title"].upper(), 66, acc(0), bold=True)
            frame = RoundedRectangle(width=word.width + 0.6, height=word.height + 0.4, corner_radius=0.12)
            frame.set_stroke(acc(0), width=6)
            stamp = fit(VGroup(frame, word), BOX_W * 0.9, BOX_H * 0.14)
            stamp_h = stamp.height + 0.6
        c, w, h = self.area(BOX_TOP - stamp_h)
        rows = []
        for it in p["items"]:
            ring = Circle(radius=0.24).set_stroke(PAL["muted"], width=4)
            t = txt(it["text"], 64, wrap_at=chars(22, 44))
            row = VGroup(ring, t).arrange(RIGHT, buff=0.35)
            rows.append(row)
        g = VGroup(*rows).arrange(DOWN, buff=0.6, aligned_edge=LEFT)
        fit(g, w * 0.92, h * 0.9).move_to(c)
        if stamp is not None:
            stamp.next_to(g, UP, buff=0.6)
            block = VGroup(stamp, g)
            block.move_to([BOX_C[0], (BOX_TOP + self.bottom) / 2, 0])
            self.play(FadeIn(stamp, scale=1.3), run_time=0.5)
        for r in rows:
            r.set_opacity(0.35)
        self.play(FadeIn(g, shift=UP * 0.2), run_time=0.5)
        for r in rows:
            r.set_opacity(0.35)
        times = self.times or self.spread(len(rows))
        bar = None
        for i, row in enumerate(rows):
            self.at(times[i])
            ring = row[0]
            dot = _fill(Circle(radius=ring.width / 2), acc(3)).move_to(ring)
            new_bar = RoundedRectangle(width=w * 0.98, height=row.height + 0.3, corner_radius=0.15)
            new_bar.set_fill(acc(0), opacity=0.14).set_stroke(acc(0), width=2, opacity=0.6)
            new_bar.move_to([c[0], row.get_y(), 0]).set_z_index(-1)
            anims = [row.animate.set_opacity(1), FadeIn(dot), Create(_tick(ring.get_center(), ring.width))]
            anims.append(FadeIn(new_bar) if bar is None else Transform(bar, new_bar))
            self.play(*anims, run_time=self.rt(0.5, self.next_time(i)))
            bar = bar or new_bar
        self.finish()


class T_source_card(Base):
    def construct(self):
        p = self.p
        c, w, h = self.area(BOX_TOP)
        ink, grey, link = "#0F172A", "#475569", "#2563EB"
        cw = w * 0.94
        cols = chars(22, 46)
        top = VGroup(Dot(radius=0.1, color=acc(0)),
                     txt(p["publisher"] + (f"  ·  {p['date']}" if p.get("date") else ""), 42, grey, bold=True))
        top.arrange(RIGHT, buff=0.2)
        headline = txt(p["headline"], 76, ink, bold=True, wrap_at=cols)
        parts = [top, headline]
        if p.get("excerpt"):
            parts.append(txt(p["excerpt"], 48, grey, wrap_at=chars(30, 60)))
        if p.get("url"):
            parts.append(txt(p["url"], 38, link))
        inner = VGroup(*parts).arrange(DOWN, buff=0.35, aligned_edge=LEFT)
        fit(inner, cw - 0.9, h * 0.66)
        card = _fill(RoundedRectangle(width=cw, height=inner.height + 0.9, corner_radius=0.22), "#F8FAFC", "#CBD5E1")
        inner.move_to(card)
        mark = RoundedRectangle(width=headline.width + 0.3, height=headline.height + 0.2, corner_radius=0.08)
        mark.set_fill(acc(0), opacity=0.22).set_stroke(width=0).move_to(headline)
        lead = "Nguồn" if LANG == "vi" else "Source"
        tag = fit(txt(f"{lead}: {p['publisher']}" + (f" · {p['date']}" if p.get("date") else ""), 52, acc(0),
                      bold=True), w, h * 0.1)
        block = VGroup(VGroup(card, mark, inner), tag).arrange(DOWN, buff=0.45).move_to(c)
        cardg = block[0]
        self.play(FadeIn(card, shift=UP * 0.5), run_time=0.6)
        self.play(FadeIn(inner, lag_ratio=0.15), run_time=0.8)
        self.play(GrowFromEdge(mark, LEFT), FadeIn(tag, shift=UP * 0.15), run_time=0.6)
        rest = DUR - self.now() - 0.05
        if rest > 0.5:
            self.play(cardg.animate.scale(1.025), run_time=rest, rate_func=linear)
        self.finish()


class T_headline(Base):
    def construct(self):
        p = self.p
        c, w, h = self.area(BOX_TOP)
        parts = []
        kicker = txt(p["kicker"], 58, PAL["muted"], wrap_at=chars(26, 50), center=True) if p.get("kicker") else None
        if p.get("style") == "big":
            main = txt(p["text"], 220, acc(0), bold=True)
            main.set_color_by_gradient(acc(0), acc(2))
            fit(main, w * 0.95, h * 0.35)
            pill = None
        else:
            word = txt(p["text"], 100, "#111111", bold=True)
            fit(word, w * 0.82, h * 0.2)
            pill = RoundedRectangle(width=word.width + 0.9, height=word.height + 0.7, corner_radius=0.3)
            pill.set_fill([acc(0), acc(2)], opacity=1).set_stroke(width=0).set_sheen_direction(RIGHT)
            word.move_to(pill)
            main = VGroup(pill, word)
        parts = [m for m in (kicker, main) if m is not None]
        note = txt(p["note"], 50, PAL["muted"], wrap_at=chars(28, 56), center=True) if p.get("note") else None
        if note is not None:
            parts.append(note)
        g = VGroup(*parts).arrange(DOWN, buff=0.5)
        fit(g, w, h * 0.9).move_to(c)
        if kicker is not None:
            self.play(FadeIn(kicker, shift=DOWN * 0.2), run_time=0.5)
        if pill is not None:
            self.play(GrowFromCenter(pill), run_time=0.5)
            self.play(FadeIn(main[1], scale=0.8), run_time=0.4)
        else:
            self.play(Write(main), run_time=min(1.2, max(0.6, DUR * 0.2)))
        if note is not None:
            self.play(FadeIn(note, shift=UP * 0.15), run_time=0.4)
        rest = DUR - self.now() - 0.05
        if rest > 0.5:
            self.play(main.animate.scale(1.04), run_time=rest, rate_func=linear)
        self.finish()


class T_big_numbers(Base):
    def construct(self):
        p = self.p
        head, top = self.header(p.get("title"))
        c, w, h = self.area(top)
        items = p["items"]
        n = len(items)
        dec = int(p.get("decimals", 0))
        vmax = max(i["value"] for i in items)
        note = fit(txt(p["note"], 42, PAL["muted"], wrap_at=chars(32, 64), center=True), w, h * 0.12) \
            if p.get("note") else None
        col_w = w / n
        base = c[1] - h / 2 + h * 0.16 + (note.height + 0.2 if note else 0)
        max_bar = h * 0.42
        cols = []
        for i, it in enumerate(items):
            x = c[0] + (i - (n - 1) / 2) * col_w
            last = i == n - 1
            bh = max(0.12, max_bar * it["value"] / vmax)
            bar = _fill(RoundedRectangle(width=col_w * 0.5, height=bh, corner_radius=min(0.15, bh / 2)),
                        acc(0) if last else "#475569")
            bar.move_to([x, base + bh / 2, 0])
            value = fit(txt(f"{it.get('prefix', '')}{num(it['value'], dec)}{it.get('suffix', '')}", 110,
                            acc(0) if last else PAL["text"], bold=True), col_w * 0.95, h * 0.16)
            value.next_to(bar, UP, buff=0.25)
            label = fit(txt(it["label"], 46, PAL["muted"], wrap_at=chars(12, 20), center=True), col_w * 0.95,
                        h * 0.12)
            label.next_to(bar, DOWN, buff=0.25)
            cols.append((bar, value, label))
        if note is not None:
            note.next_to([c[0], min(lab.get_bottom()[1] for _, _, lab in cols), 0], DOWN, buff=0.35)
        self.settle(head, VGroup(*[m for col in cols for m in col], *([note] if note else [])))
        times = self.times or self.spread(n)
        for i, (bar, value, label) in enumerate(cols):
            self.at(times[i])
            self.play(GrowFromEdge(bar, DOWN), FadeIn(label), run_time=self.rt(0.6, self.next_time(i)))
            self.play(FadeIn(value, shift=UP * 0.2), run_time=0.35)
        self.play(Indicate(cols[-1][1], color=acc(0), scale_factor=1.08), run_time=0.6)
        if note is not None:
            self.play(FadeIn(note), run_time=0.4)
        self.finish()


__all__ = [n for n in dir() if n.startswith("T_")] + ["Base", "SPEC"]
