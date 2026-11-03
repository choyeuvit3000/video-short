"""Word timings, SRT read/write/merge and ASS caption generation. All times are integer milliseconds."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import ValidationError


@dataclass
class Word:
    text: str
    start_ms: int
    end_ms: int


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    text: str


# ---------------------------------------------------------------- word timings


def save_words(path: Path, words: list[Word], *, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timing_source": source, "words": [asdict(w) for w in words]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def load_words(path: Path) -> tuple[list[Word], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Word(**w) for w in data.get("words", [])], data.get("timing_source", "unknown")


_TOKEN_RE = re.compile(r"\S+")


def estimate_words(text: str, duration_ms: int, *, lead_ms: int = 0) -> list[Word]:
    """Spread words over `duration_ms` proportionally to their length (+ pauses at punctuation).

    Only an approximation - callers must label it `estimate` so nobody mistakes it for real alignment.
    """
    tokens = _TOKEN_RE.findall(text)
    if not tokens or duration_ms <= 0:
        return []
    weights = []
    for t in tokens:
        w = len(t) + 2
        if t[-1] in ".!?…":
            w += 6
        elif t[-1] in ",;:":
            w += 3
        weights.append(w)
    total = sum(weights)
    words, cur = [], float(lead_ms)
    span = duration_ms - lead_ms
    for t, w in zip(tokens, weights, strict=True):
        d = span * w / total
        words.append(Word(t, int(round(cur)), int(round(cur + d))))
        cur += d
    return words


def shift_words(words: list[Word], offset_ms: int) -> list[Word]:
    return [Word(w.text, w.start_ms + offset_ms, w.end_ms + offset_ms) for w in words]


# ---------------------------------------------------------------- grouping into caption chunks


def group_words(words: list[Word], *, max_words: int, max_chars: int, max_gap_ms: int = 600) -> list[list[Word]]:
    chunks: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            text_len = len(" ".join(x.text for x in cur)) + 1 + len(w.text)
            gap = w.start_ms - cur[-1].end_ms
            ends_sentence = cur[-1].text[-1:] in ".!?…"
            if len(cur) >= max_words or text_len > max_chars or gap > max_gap_ms or ends_sentence:
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def chunks_to_cues(chunks: list[list[Word]]) -> list[Cue]:
    cues = []
    for i, ch in enumerate(chunks):
        start = ch[0].start_ms
        end = ch[-1].end_ms
        if i + 1 < len(chunks):
            nxt = chunks[i + 1][0].start_ms
            # hold the chunk until the next one if the gap is short, never overlap
            end = nxt if 0 <= nxt - end <= 400 else min(end + 200, nxt)
        cues.append(Cue(start, max(end, start + 1), " ".join(w.text for w in ch)))
    return cues


# ---------------------------------------------------------------- SRT


def _ts(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


_TS_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")


def _parse_ts(s: str) -> int:
    m = _TS_RE.fullmatch(s.strip())
    if not m:
        raise ValidationError(f"bad SRT timestamp: {s!r}", code="srt_error")
    h, mi, se, ms = m.groups()
    return ((int(h) * 60 + int(mi)) * 60 + int(se)) * 1000 + int(ms.ljust(3, "0"))


def write_srt(path: Path, cues: list[Cue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, c in enumerate(cues, 1):
        lines += [str(i), f"{_ts(c.start_ms)} --> {_ts(c.end_ms)}", c.text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_srt(text: str) -> list[Cue]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        if "-->" not in lines[0]:
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            raise ValidationError(f"bad SRT block: {block[:60]!r}", code="srt_error")
        a, _, b = lines[0].partition("-->")
        cues.append(Cue(_parse_ts(a), _parse_ts(b.split()[0]), "\n".join(lines[1:])))
    return cues


def read_srt(path: Path) -> list[Cue]:
    return parse_srt(path.read_text(encoding="utf-8-sig"))


def shift_cues(cues: list[Cue], offset_ms: int) -> list[Cue]:
    return [Cue(c.start_ms + offset_ms, c.end_ms + offset_ms, c.text) for c in cues]


def check_cues(cues: list[Cue], *, duration_ms: int | None = None) -> list[str]:
    """Return problems: negative/zero length, going backwards, beyond the video end."""
    problems = []
    prev_start = -1
    for i, c in enumerate(cues, 1):
        if c.start_ms < 0 or c.end_ms <= c.start_ms:
            problems.append(f"cue {i}: invalid time range")
        if c.start_ms < prev_start:
            problems.append(f"cue {i}: not monotonic")
        if duration_ms is not None and c.end_ms > duration_ms + 50:
            problems.append(f"cue {i}: ends after the video ({c.end_ms} ms > {duration_ms} ms)")
        prev_start = c.start_ms
    return problems


# ---------------------------------------------------------------- ASS

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, \
Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, \
MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_ts(ms: int) -> str:
    cs = max(0, int(round(ms / 10)))
    h, rem = divmod(cs, 360_000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def hex_to_ass(color: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR"""
    c = color.lstrip("#")
    if len(c) != 6:
        raise ValidationError(f"bad color {color!r}", code="config_error")
    r, g, b = c[0:2], c[2:4], c[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def build_ass(
    words: list[Word],
    *,
    width: int,
    height: int,
    style: dict[str, Any],
    caption: dict[str, Any],
) -> tuple[str, list[Cue]]:
    """Create ASS text (word-highlight captions) and the matching chunk-level cues for the SRT sidecar."""
    font = style.get("font", "Arial")
    size = int(caption.get("font_size", 72) * float(style.get("size_scale", 1.0)))
    primary = hex_to_ass(style.get("color", "#FFFFFF"))
    outline = hex_to_ass(style.get("outline_color", "#000000"))
    back = hex_to_ass(style.get("shadow_color", "#000000"), alpha=int(style.get("shadow_alpha", 96)))
    highlight = hex_to_ass(style.get("highlight_color", "#FFE14D"))
    bold = -1 if style.get("bold", True) else 0
    border_style = 3 if style.get("box", False) else 1
    outline_w = float(style.get("outline", 5))
    shadow = float(style.get("shadow", 2))
    margin_v = int(caption.get("margin_v", 200))
    margin_h = int(caption.get("margin_h", 60))
    upper = bool(style.get("uppercase", False))
    styles = (
        f"Style: Caption,{font},{size},{primary},{primary},{outline},{back},{bold},0,0,0,100,100,0,0,"
        f"{border_style},{outline_w},{shadow},2,{margin_h},{margin_h},{margin_v},1"
    )
    lines = [ASS_HEADER.format(w=width, h=height, styles=styles)]
    chunks = group_words(words, max_words=int(caption.get("max_words", 3)), max_chars=int(caption.get("max_chars", 18)))
    cues = chunks_to_cues(chunks)
    mode = style.get("mode", "highlight")
    for ch, cue in zip(chunks, cues, strict=True):
        texts = [_ass_escape(w.text.upper() if upper else w.text) for w in ch]
        if mode == "highlight" and len(ch) > 1:
            for i, w in enumerate(ch):
                start = cue.start_ms if i == 0 else w.start_ms
                end = ch[i + 1].start_ms if i + 1 < len(ch) else cue.end_ms
                if end <= start:
                    continue
                parts = [
                    f"{{\\c{highlight}}}{t}{{\\c{primary}}}" if j == i else t for j, t in enumerate(texts)
                ]
                lines.append(f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Caption,,0,0,0,,{' '.join(parts)}")
        else:
            lines.append(f"Dialogue: 0,{_ass_ts(cue.start_ms)},{_ass_ts(cue.end_ms)},Caption,,0,0,0,,{' '.join(texts)}")
    return "\n".join(lines) + "\n", cues
