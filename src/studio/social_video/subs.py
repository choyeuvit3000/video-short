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
    from ..core.subtitles import Word, build_ass

    aligned = [Word(w["text"], round((w["start"] + offset) * 1000),
                    round((w["end"] + offset) * 1000)) for w in words]
    ass, _ = build_ass(aligned, width=width, height=height,
                       style={"font": font, "color": "#FFFFFF", "inactive_color": "#C8CDD2",
                              "outline_color": "#16212B", "outline": 1.5, "shadow": 0.5,
                              "box": False, "mode": "karaoke", "lines": 2, "max_words": 9,
                              "max_chars": 40, "line_chars": 22, "smooth_phrases": True, "fade_ms": 50},
                       caption={"font_size": 52 * width / 1080, "margin_v": max(margin_v, round(310 * height / 1920)),
                                "margin_h": round(110 * width / 1080)})
    out.write_text(ass, encoding="utf-8")
