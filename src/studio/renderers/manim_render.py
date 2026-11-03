"""Manim (Community Edition) scenes as a visual type: `visual: {type: manim, template: <name>, params: {...}}`.

Two kinds of scene:
- template - one of TEMPLATES below (title, bullets, counter, bar_chart, line_chart, function_graph, timeline,
  compare, formula, process, quote). An LLM (or you) only fills JSON params, which are validated here;
  no generated code ever runs. Code: renderers/manim_scenes/templates.py.
- custom   - `visual: {type: manim, file: manim/<name>.py, scene_class: <Class>}`: a Manim file in the
  project that you wrote or reviewed yourself. It runs as Python on this machine, like any script.

Both are rendered by `python -m manim render` (argument list, never a shell) at the format's exact size,
fps and the scene's duration, into work/manim/<scene_id>.mp4, cached by a key over everything they depend on.
A JSON spec (size, duration, palette, safe content box, word cue times) is passed via STUDIO_MANIM_SPEC.

Animations follow the narration: list-like templates (bullets, bar_chart, timeline, process) reveal item i at
the time its `cue` word is spoken (word timings from the voice stage), otherwise evenly over the voice.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..core.cache import build_cached, cache_key
from ..core.errors import StudioError, ToolMissingError
from ..core.logging_utils import get_logger, redact
from ..core.project import ProjectContext

log = get_logger()

MANIM_REV = 1  # bump when templates.py or the spec changes the picture for the same inputs
TEMPLATE_SCRIPT = Path(__file__).parent / "manim_scenes" / "templates.py"
DEFAULT_PALETTE = {"background": "#101626", "text": "#F4F6FB", "muted": "#9AA4B8",
                   "accent": ["#4CC9F0", "#FFD166", "#EF476F", "#06D6A0"]}
DEFAULT_FONT = "Arial"


# ------------------------------------------------------------------ template params


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")


Short = Field(min_length=1, max_length=60)


class Item(_P):
    text: str = Field(min_length=1, max_length=70)
    cue: str | None = Field(default=None, max_length=40, description="word of the narration that reveals it")


class TitleP(_P):
    """Big title card: chapter openers, hooks."""
    title: str = Field(min_length=1, max_length=80)
    subtitle: str | None = Field(default=None, max_length=120)
    kicker: str | None = Field(default=None, max_length=30, description="small label above, e.g. the topic")


class BulletsP(_P):
    """Up to 6 short points revealed one by one."""
    title: str | None = Field(default=None, max_length=60)
    items: list[Item] = Field(min_length=1, max_length=6)


class CounterP(_P):
    """A number counting up to a value: statistics, money, distances."""
    label: str = Field(min_length=1, max_length=70)
    end: float
    start: float = 0
    decimals: int = Field(default=0, ge=0, le=3)
    prefix: str = Field(default="", max_length=8)
    suffix: str = Field(default="", max_length=16)
    note: str | None = Field(default=None, max_length=90, description="small source/context line")


class Bar(_P):
    label: str = Field(min_length=1, max_length=24)
    value: float = Field(ge=0)
    cue: str | None = Field(default=None, max_length=40)


class BarChartP(_P):
    """Bars growing one by one (values >= 0)."""
    title: str | None = Field(default=None, max_length=60)
    bars: list[Bar] = Field(min_length=2, max_length=8)
    unit: str = Field(default="", max_length=16)
    highlight: int | None = Field(default=None, ge=0, description="index of the bar to colour as the answer")

    @model_validator(mode="after")
    def _check(self) -> BarChartP:
        if self.highlight is not None and self.highlight >= len(self.bars):
            raise ValueError("highlight is out of range")
        if max(b.value for b in self.bars) <= 0:
            raise ValueError("at least one bar must be > 0")
        return self


class Series(_P):
    name: str = Field(min_length=1, max_length=24)
    values: list[float] = Field(min_length=2, max_length=40)


class LineChartP(_P):
    """Data over time (prices, population, temperature); up to 3 series drawn left to right."""
    title: str | None = Field(default=None, max_length=60)
    x_labels: list[str] = Field(min_length=2, max_length=40)
    series: list[Series] = Field(min_length=1, max_length=3)
    unit: str = Field(default="", max_length=16)

    @model_validator(mode="after")
    def _check(self) -> LineChartP:
        for s in self.series:
            if len(s.values) != len(self.x_labels):
                raise ValueError(f"series '{s.name}' has {len(s.values)} values for {len(self.x_labels)} x_labels")
        return self


CurveKind = Literal["linear", "quadratic", "exponential", "compound", "logistic", "sine", "normal"]


class Curve(_P):
    """linear a*x+b · quadratic a*x²+b*x+c · exponential a*e^(b*x) · compound a*(1+b)^x ·
    logistic a/(1+e^(-b*(x-c))) · sine a*sin(b*x+c) · normal: bell curve, a = sigma, b = mean."""
    kind: CurveKind
    a: float = 1
    b: float = 0
    c: float = 0
    label: str | None = Field(default=None, max_length=30)


class FunctionGraphP(_P):
    """Plot of built-in formulas (no code): compound interest, growth, waves, bell curves."""
    title: str | None = Field(default=None, max_length=60)
    curves: list[Curve] = Field(min_length=1, max_length=3)
    x_range: tuple[float, float] = (0, 10)
    x_label: str = Field(default="", max_length=20)
    y_label: str = Field(default="", max_length=20)

    @model_validator(mode="after")
    def _check(self) -> FunctionGraphP:
        if self.x_range[1] <= self.x_range[0]:
            raise ValueError("x_range must be [min, max] with max > min")
        for c in self.curves:
            if c.kind == "normal" and c.a <= 0:
                raise ValueError("normal curve needs a (sigma) > 0")
        return self


class Event(_P):
    year: str = Field(min_length=1, max_length=14, description="'1945', '200 TCN', 'Thế kỷ 15'")
    label: str = Field(min_length=1, max_length=50)
    cue: str | None = Field(default=None, max_length=40)


class TimelineP(_P):
    """Dated events along a line, in order: history, the story of a discovery."""
    title: str | None = Field(default=None, max_length=60)
    events: list[Event] = Field(min_length=2, max_length=8)


class Side(_P):
    title: str = Field(min_length=1, max_length=30)
    points: list[str] = Field(min_length=1, max_length=5)


class CompareP(_P):
    """Two columns side by side: A vs B (stocks vs bonds, Rome vs Carthage)."""
    title: str | None = Field(default=None, max_length=60)
    left: Side
    right: Side
    verdict: str | None = Field(default=None, max_length=80)


class Legend(_P):
    symbol: str = Field(min_length=1, max_length=8)
    meaning: str = Field(min_length=1, max_length=50)


class FormulaP(_P):
    """A formula written as plain Unicode text (A = P·(1 + r)ⁿ) with a legend of its symbols.
    `tex` is used instead when a LaTeX install is found."""
    title: str | None = Field(default=None, max_length=60)
    text: str = Field(min_length=1, max_length=60)
    tex: str | None = Field(default=None, max_length=120)
    legend: list[Legend] = Field(default_factory=list, max_length=5)


class ProcessP(_P):
    """Steps joined by arrows: how something works, a cycle (loop=true)."""
    title: str | None = Field(default=None, max_length=60)
    steps: list[Item] = Field(min_length=2, max_length=6)
    loop: bool = False


class QuoteP(_P):
    """A short quotation with its author; only real, verifiable quotes."""
    text: str = Field(min_length=1, max_length=220)
    author: str = Field(min_length=1, max_length=60)
    context: str | None = Field(default=None, max_length=60, description="e.g. the year or the work")


TEMPLATES: dict[str, type[_P]] = {
    "title": TitleP, "bullets": BulletsP, "counter": CounterP, "bar_chart": BarChartP, "line_chart": LineChartP,
    "function_graph": FunctionGraphP, "timeline": TimelineP, "compare": CompareP, "formula": FormulaP,
    "process": ProcessP, "quote": QuoteP,
}
# which list in the params is revealed item by item, following the narration
CUED_LIST = {"bullets": "items", "bar_chart": "bars", "timeline": "events", "process": "steps"}

EXAMPLES: dict[str, dict[str, Any]] = {
    "title": {"kicker": "TÀI CHÍNH", "title": "Lãi kép", "subtitle": "Kỳ quan thứ tám của thế giới?"},
    "bullets": {"title": "Vì sao bầu trời màu xanh?", "items": [
        {"text": "Ánh sáng mặt trời gồm nhiều màu", "cue": "ánh"},
        {"text": "Không khí tán xạ màu xanh mạnh nhất", "cue": "tán"}]},
    "counter": {"label": "Khoảng cách tới Mặt Trời", "end": 149.6, "decimals": 1, "suffix": " triệu km"},
    "bar_chart": {"title": "Dân số 2023 (triệu)", "unit": "tr", "highlight": 0, "bars": [
        {"label": "Ấn Độ", "value": 1428}, {"label": "Trung Quốc", "value": 1425}, {"label": "Mỹ", "value": 340}]},
    "line_chart": {"title": "Giá vàng (USD/oz)", "x_labels": ["2019", "2020", "2021", "2022", "2023"],
                   "series": [{"name": "Vàng", "values": [1393, 1770, 1799, 1801, 1943]}]},
    "function_graph": {"title": "100 triệu sau 30 năm", "x_range": [0, 30], "x_label": "năm", "curves": [
        {"kind": "compound", "a": 100, "b": 0.05, "label": "5%/năm"},
        {"kind": "compound", "a": 100, "b": 0.1, "label": "10%/năm"}]},
    "timeline": {"title": "Chiến tranh thế giới II", "events": [
        {"year": "1939", "label": "Đức tấn công Ba Lan"}, {"year": "1945", "label": "Chiến tranh kết thúc"}]},
    "compare": {"left": {"title": "Cổ phiếu", "points": ["Lợi nhuận cao hơn", "Biến động mạnh"]},
                "right": {"title": "Trái phiếu", "points": ["Ổn định hơn", "Lợi nhuận thấp hơn"]}},
    "formula": {"title": "Công thức lãi kép", "text": "A = P·(1 + r)ⁿ", "legend": [
        {"symbol": "P", "meaning": "tiền gốc"}, {"symbol": "r", "meaning": "lãi suất mỗi kỳ"},
        {"symbol": "n", "meaning": "số kỳ"}]},
    "process": {"title": "Quang hợp", "steps": [
        {"text": "Lá hấp thụ ánh sáng"}, {"text": "Nước + CO₂"}, {"text": "Đường + O₂"}]},
    "quote": {"text": "Điều khó hiểu nhất về vũ trụ là nó có thể hiểu được.", "author": "Albert Einstein",
              "context": "1936"},
}


def validate_params(template: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Validated, normalised params (raises StudioError code=bad_manim_params with a readable reason)."""
    model = TEMPLATES.get(template)
    if model is None:
        raise StudioError(f"unknown manim template '{template}' (known: {', '.join(TEMPLATES)})",
                          code="unknown_manim_template")
    try:
        return model.model_validate(params or {}).model_dump(mode="json")
    except ValidationError as e:
        reasons = "; ".join(f"{'.'.join(str(x) for x in err['loc']) or 'params'}: {err['msg']}" for err in e.errors())
        raise StudioError(f"manim template '{template}': {reasons}", code="bad_manim_params") from None


def catalog(templates: list[str] | None = None) -> str:
    """Markdown list of templates with a one-line purpose and an example - used in LLM prompts."""
    lines = []
    for name in templates or list(TEMPLATES):
        doc = " ".join((TEMPLATES[name].__doc__ or "").split())
        lines.append(f"- `{name}`: {doc}\n  example params: `{json.dumps(EXAMPLES[name], ensure_ascii=False)}`")
    return "\n".join(lines)


def manim_available() -> bool:
    return importlib.util.find_spec("manim") is not None


def latex_available() -> bool:
    return shutil.which("latex") is not None


# ------------------------------------------------------------------ timing + layout


def _norm(word: str) -> str:
    w = unicodedata.normalize("NFC", word).lower()
    return re.sub(r"[^\w]+", "", w)


def item_times(cues: list[str | None], words: list[dict], voice_sec: float, *, lead: float = 0.6) -> list[float]:
    """Reveal time (s, scene-relative) per item: the start of its cue word if spoken, else evenly spaced.

    `words` are the scene's word timings ({text, start_ms, end_ms}). Times never go backwards, and a cue is
    searched only after the previous item's word, so repeated words resolve in narration order.
    """
    n = len(cues)
    if n == 0:
        return []
    end = max(voice_sec * 0.85, lead + 0.4 * n)
    even = [lead + (end - lead) * i / max(n, 1) for i in range(n)]
    tokens = [(_norm(w["text"]), w["start_ms"] / 1000) for w in words]
    times: list[float] = []
    pos = 0
    for i, cue in enumerate(cues):
        t = None
        if cue:
            first = _norm(cue.split()[0]) if cue.split() else ""
            for j in range(pos, len(tokens)):
                if first and tokens[j][0].startswith(first):
                    t, pos = tokens[j][1], j + 1
                    break
        times.append(even[i] if t is None else t)
    for i in range(1, n):  # monotonic, at least 0.25 s apart
        times[i] = max(times[i], times[i - 1] + 0.25)
    return [round(t, 3) for t in times]


def content_box(fmt, *, captions: bool) -> dict[str, int]:
    """Pixel box for the animation: inside the safe zone and above the burned-in captions."""
    from .render import caption_box

    safe = fmt.safe_zone or {}
    x0 = int(safe.get("left", 0))
    x1 = fmt.width - int(safe.get("right", 0))
    y0 = int(safe.get("top", 0))
    y1 = fmt.height - int(safe.get("bottom", 0))
    if captions:
        cap = caption_box(fmt)
        cap_top = fmt.height - cap["margin_v"] - 2 * int(cap.get("font_size", 48))  # room for 2 caption lines
        y1 = min(y1, cap_top - int(fmt.height * 0.02))
    if y1 - y0 < fmt.height * 0.3:  # very small formats: keep a usable box
        y1 = min(fmt.height, y0 + int(fmt.height * 0.3))
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def _scene_words(ctx: ProjectContext, scene_id: str) -> list[dict]:
    p = ctx.dir / "subtitles" / f"{scene_id}.words.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("words", [])
    except (OSError, ValueError):
        return []


def build_spec(ctx: ProjectContext, scene, dur_ms: int, voice_ms: int) -> dict[str, Any]:
    p = ctx.project
    fmt = ctx.fmt
    v = scene.visual
    palette = {**DEFAULT_PALETTE, **(p.options.get("palette") or {})}
    captions = p.video.subtitle_mode == "burn_in" and any(s.narration.strip() for s in p.scenes)
    spec: dict[str, Any] = {
        "rev": MANIM_REV, "scene_id": scene.scene_id, "width": fmt.width, "height": fmt.height, "fps": fmt.fps,
        "duration": round(dur_ms / 1000, 3), "voice": round(voice_ms / 1000, 3),
        "box": content_box(fmt, captions=captions), "palette": palette,
        "font": p.options.get("manim_font") or DEFAULT_FONT, "latex": latex_available(),
        "footer": p.options.get("on_screen_note") if p.scenes and scene.scene_id == p.scenes[0].scene_id else None,
        "language": p.language,
    }
    if v.file:
        spec["custom"] = True
    else:
        params = validate_params(v.template or "", v.params)
        spec["template"] = v.template
        spec["params"] = params
        list_key = CUED_LIST.get(v.template or "")
        if list_key:
            cues = [it.get("cue") for it in params[list_key]]
            spec["times"] = item_times(cues, _scene_words(ctx, scene.scene_id), voice_ms / 1000)
    return spec


# ------------------------------------------------------------------ render


def _class_name(template: str) -> str:
    return "T_" + template


def render_manim(ctx: ProjectContext, scene, dur_ms: int, voice_ms: int) -> tuple[Path, str]:
    """Render the scene's Manim animation; returns (mp4 path, cache key)."""
    if not manim_available():
        raise ToolMissingError('manim is not installed - uv pip install -e ".[manim]"', code="manim_missing",
                               scene_id=scene.scene_id)
    v = scene.visual
    spec = build_spec(ctx, scene, dur_ms, voice_ms)
    if v.file:
        script = ctx.resolve(v.file, what="manim file")
        cls = v.scene_class or ""
        if not script.is_file() or not cls:
            raise StudioError("custom manim scene needs an existing `file` and a `scene_class`",
                              code="bad_manim_params", scene_id=scene.scene_id)
    else:
        script, cls = TEMPLATE_SCRIPT, _class_name(spec["template"])
    out_dir = ctx.work / "manim"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{scene.scene_id}.mp4"
    # never `import manim` here: it installs its own logging handlers in this process
    key = cache_key("manim", MANIM_REV, spec, cls, ctx.hashes.sha(script), importlib.metadata.version("manim"))

    def build() -> None:
        spec_file = out_dir / f"{scene.scene_id}.spec.json"
        spec_file.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
        media = out_dir / f"_media_{scene.scene_id}"
        shutil.rmtree(media, ignore_errors=True)
        args = [sys.executable, "-m", "manim", "render", str(script), cls,
                "--format", "mp4", "-r", f"{spec['width']},{spec['height']}", "--fps", str(spec["fps"]),
                "--disable_caching", "--media_dir", str(media), "-o", scene.scene_id,
                "--progress_bar", "none", "-v", "WARNING"]
        env = {**os.environ, "STUDIO_MANIM_SPEC": str(spec_file), "PYTHONIOENCODING": "utf-8"}
        timeout = int(ctx.settings.get("manim.timeout_sec", 900))
        log.info("[render][%s] manim %s (%.1fs)", scene.scene_id, v.template or f"{v.file}:{cls}", spec["duration"])
        try:
            r = subprocess.run(args, cwd=out_dir, env=env, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            raise StudioError(f"manim timed out after {timeout}s", code="manim_failed",
                              scene_id=scene.scene_id) from None
        made = [f for f in media.rglob(f"{scene.scene_id}.mp4") if "partial_movie_files" not in f.parts]
        if r.returncode != 0 or not made:
            tail = "\n".join((r.stderr or r.stdout or "").strip().splitlines()[-12:])
            raise StudioError(f"manim failed (exit {r.returncode}):\n{redact(tail)}", code="manim_failed",
                              scene_id=scene.scene_id)
        out.unlink(missing_ok=True)
        shutil.move(str(made[0]), out)
        shutil.rmtree(media, ignore_errors=True)

    build_cached(out, key, build)
    return out, key
