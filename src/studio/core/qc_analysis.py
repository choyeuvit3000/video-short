"""Content checks for QC: what the viewer hears and sees, not just the container.

- `analyze_av`: one ffmpeg decode pass -> loudness (EBU R128 integrated + true peak), silences,
  black frames and frozen frames.
- `caption_layout`: measures every burned-in caption (work/captions.ass, the file that was really burned)
  with the real font and checks it stays inside the format's safe zone (platform UI) and the frame.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from .ffmpeg import run_ffmpeg

_NUM = r"(-?\d+(?:\.\d+)?|-?inf)"
_BLACK = re.compile(r"black_start:\s*" + _NUM + r"\s+black_end:\s*" + _NUM)
_FREEZE = re.compile(r"lavfi\.freezedetect\.freeze_(start|end):\s*" + _NUM)
_SIL_START = re.compile(r"silence_start:\s*" + _NUM)
_SIL_END = re.compile(r"silence_end:\s*" + _NUM)
_LUFS = re.compile(r"Integrated loudness:\s*I:\s*" + _NUM + r"\s*LUFS", re.S)
_PEAK = re.compile(r"True peak:\s*Peak:\s*" + _NUM + r"\s*dBFS", re.S)


def _f(s: str) -> float:
    return float(s)  # float() understands "-inf"


def _close(starts: list[float], ends: list[float], duration: float) -> list[tuple[float, float]]:
    """Pair start/end events; an interval still open at the end of the file ends at `duration`."""
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else duration
        if e > s:
            out.append((round(s, 3), round(e, 3)))
    return out


def parse_analysis(log: str, duration: float) -> dict[str, Any]:
    black = [(round(_f(a), 3), round(_f(b), 3)) for a, b in _BLACK.findall(log)]
    fs, fe = [], []
    for kind, v in _FREEZE.findall(log):
        (fs if kind == "start" else fe).append(_f(v))
    lufs = _LUFS.findall(log)
    peak = _PEAK.findall(log)
    return {
        "integrated_lufs": _f(lufs[-1]) if lufs else None,
        "true_peak_db": _f(peak[-1]) if peak else None,
        "silence": _close([_f(x) for x in _SIL_START.findall(log)], [_f(x) for x in _SIL_END.findall(log)], duration),
        "black": black,
        "freeze": _close(fs, fe, duration),
    }


def analyze_av(path: Path, duration: float, *, silence_db: float = -45.0, min_silence: float = 0.5,
               black_pix_th: float = 0.10, min_black: float = 0.2, min_freeze: float = 1.0) -> dict[str, Any]:
    """Decode once (video downscaled - the checks don't need full resolution) and parse the filter logs."""
    vf = (f"scale=270:-2,blackdetect=d={min_black}:pix_th={black_pix_th},"
          f"freezedetect=n=-60dB:d={min_freeze}")
    af = f"ebur128=peak=true,silencedetect=n={silence_db}dB:d={min_silence}"
    log = run_ffmpeg(["-nostats", "-i", str(path), "-vf", vf, "-af", af, "-f", "null", "-"],
                     stage="qc", loglevel="info")
    return parse_analysis(log, duration)


def overlap(intervals: list[tuple[float, float]], start: float, end: float) -> float:
    return sum(max(0.0, min(b, end) - max(a, start)) for a, b in intervals)


# ------------------------------------------------------------------ captions


_STYLE_FIELDS = ("Name", "Fontname", "Fontsize", "PrimaryColour", "SecondaryColour", "OutlineColour", "BackColour",
                 "Bold", "Italic", "Underline", "StrikeOut", "ScaleX", "ScaleY", "Spacing", "Angle", "BorderStyle",
                 "Outline", "Shadow", "Alignment", "MarginL", "MarginR", "MarginV", "Encoding")
_TAGS = re.compile(r"\{[^}]*\}")


def read_ass(path: Path) -> tuple[dict[str, str], list[str]]:
    """The 'Caption' style and the text of every Dialogue line (override tags removed)."""
    style: dict[str, str] = {}
    texts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Style:") and not style:
            style = dict(zip(_STYLE_FIELDS, (v.strip() for v in line[6:].split(",")), strict=False))
        elif line.startswith("Dialogue:"):
            texts.append(_TAGS.sub("", line.split(",", 9)[9]))
    return style, texts


def _font_dirs(extra: list[Path]) -> list[Path]:
    dirs = list(extra)
    if sys.platform == "win32":
        dirs.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
        dirs.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs += [Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path.home() / ".fonts"]
    return [d for d in dirs if d.is_dir()]


def find_font(name: str, bold: bool, extra_dirs: list[Path]) -> Path | None:
    """Font file for an ASS font name: project fonts first (by family name), then common system file names."""
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    want = name.lower()
    for d in extra_dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            try:
                family, sub = ImageFont.truetype(str(f), 20).getname()
            except OSError:
                continue
            if (family or "").lower() == want and (("bold" in (sub or "").lower()) == bold):
                return f
    base = want.replace(" ", "")
    names = ([f"{base}bd.ttf", f"{base}b.ttf", f"{base}-bold.ttf"] if bold else []) + [f"{base}.ttf"]
    if base in ("arial", "dejavusans"):
        names += ["dejavusans-bold.ttf" if bold else "dejavusans.ttf"]
    for d in _font_dirs([]):
        found = {f.name.lower(): f for f in d.rglob("*") if f.name.lower() in names}
        for n in names:  # bold file before the regular one
            if n in found:
                return found[n]
    return None


class _Measure:
    """Text width in ASS pixels. libass sizes a font so ascent+descent == Fontsize (VSFilter rule)."""

    def __init__(self, font_file: Path | None, size: float):
        self.size = size
        self.font = None
        if font_file is not None:
            from PIL import ImageFont

            self.font = ImageFont.truetype(str(font_file), 200)
            asc, desc = self.font.getmetrics()
            self.scale = size / (asc + desc)

    def width(self, text: str) -> float:
        if self.font is None:
            return len(text) * self.size * 0.6  # rough average for bold sans fonts
        return self.font.getlength(text) * self.scale


def _wrap(words: list[str], m: _Measure, box: float) -> list[float]:
    """Greedy wrap like libass: widths of the resulting lines (a single word wider than the box overflows)."""
    lines: list[float] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}" if cur else w
        if cur and m.width(trial) > box:
            lines.append(m.width(cur))
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(m.width(cur))
    return lines


def caption_layout(ass: Path, *, width: int, height: int, safe: dict[str, int],
                   font_dirs: list[Path]) -> dict[str, Any]:
    style, texts = read_ass(ass)
    size = float(style.get("Fontsize", 48))
    bold = style.get("Bold", "0") not in ("0", "")
    outline = float(style.get("Outline", 0))
    shadow = float(style.get("Shadow", 0))
    ml, mr, mv = (int(style.get(k, 0)) for k in ("MarginL", "MarginR", "MarginV"))
    font_file = find_font(style.get("Fontname", "Arial"), bold, font_dirs)
    m = _Measure(font_file, size)
    box = width - ml - mr
    s_top, s_bot = safe.get("top", 0), safe.get("bottom", 0)
    s_left, s_right = safe.get("left", 0), safe.get("right", 0)
    outside_safe: list[str] = []
    outside_frame: list[str] = []
    max_lines = 0
    for text in dict.fromkeys(texts):  # highlight mode repeats each chunk once per word
        line_widths = []
        for part in text.split("\\N"):
            line_widths += _wrap(part.split(), m, box)
        if not line_widths:
            continue
        max_lines = max(max_lines, len(line_widths))
        lw = max(line_widths)
        x0 = ml + (box - lw) / 2 - outline
        x1 = ml + (box + lw) / 2 + outline + shadow
        y1 = height - mv + outline + shadow
        y0 = height - mv - len(line_widths) * size - outline
        if x0 < 0 or x1 > width or y0 < 0 or y1 > height:
            outside_frame.append(text)
        elif x0 < s_left or x1 > width - s_right or y0 < s_top or y1 > height - s_bot:
            outside_safe.append(text)
    return {
        "font": style.get("Fontname"),
        "font_file": font_file.name if font_file else None,
        "measured": "font" if font_file else "estimate",
        "font_size": size,
        "margins": {"left": ml, "right": mr, "bottom": mv},
        "safe_zone": safe,
        "captions_checked": len(dict.fromkeys(texts)),
        "max_lines": max_lines,
        "outside_safe_zone": outside_safe,
        "outside_frame": outside_frame,
    }
