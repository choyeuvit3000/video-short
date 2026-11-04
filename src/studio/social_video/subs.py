"""Word-highlight (karaoke style) .ass subtitles from TTS word timings."""
from __future__ import annotations

from pathlib import Path

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font},70,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,6,3,2,70,70,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
HIGHLIGHT = r"{\c&H00E5FF&\fscx108\fscy108}"  # yellow (BGR) + slight pop
RESET = r"{\c&HFFFFFF&\fscx100\fscy100}"
BREAKS = (".", ",", "!", "?", ":", ";", "…")


def _ts(sec: float) -> str:
    sec = max(sec, 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def group_words(words: list[dict], max_words: int = 4) -> list[list[dict]]:
    """Vietnamese words are syllables, so groups of 3-4 keep short phrases together."""
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or w["text"].endswith(BREAKS):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def write_ass(words: list[dict], offset: float, out: Path, width: int, height: int,
              font: str, margin_v: int = 260) -> None:
    lines = [HEADER.format(w=width, h=height, font=font, margin_v=margin_v)]
    groups = group_words(words)
    for g, group in enumerate(groups):
        # A group stays up until the next one starts, never longer, so two
        # groups are never on screen together.
        next_start = groups[g + 1][0]["start"] if g + 1 < len(groups) else None
        for i, w in enumerate(group):
            start = w["start"] + offset
            if i + 1 < len(group):
                end = group[i + 1]["start"]
            else:
                end = w["end"] + 0.25
                if next_start is not None:
                    end = min(end, next_start)
            end += offset
            text = " ".join(
                (HIGHLIGHT + _esc(x["text"]) + RESET) if j == i else _esc(x["text"])
                for j, x in enumerate(group))
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Main,,0,0,0,,{text}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
