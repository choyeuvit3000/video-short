"""Font lookup for Pillow (cards) - project assets first, then OS fonts with Vietnamese coverage."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import ImageFont

_SYSTEM = {
    "bold": ["arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf", "NotoSans-Bold.ttf"],
    "regular": ["arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "NotoSans-Regular.ttf"],
}
_DIRS = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/noto"),
    Path("/Library/Fonts"),
]


def find_font(assets_fonts: Path, weight: str = "bold", preferred: str | None = None) -> Path:
    if assets_fonts.is_dir():
        files = sorted([*assets_fonts.glob("*.ttf"), *assets_fonts.glob("*.otf")])
        if preferred:
            files = [f for f in files if preferred.lower() in f.name.lower()] or files
        want = [f for f in files if ("bold" in f.name.lower()) == (weight == "bold")]
        if want or files:
            return (want or files)[0]
    for name in _SYSTEM[weight]:
        for d in _DIRS:
            if (d / name).is_file():
                return d / name
    raise FileNotFoundError("No usable TTF font - put one in assets/shared/fonts/")


def load_font(assets_fonts: Path, size: int, weight: str = "bold") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(find_font(assets_fonts, weight)), size)
