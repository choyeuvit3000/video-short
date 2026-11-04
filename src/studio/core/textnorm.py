"""Text clean-up before TTS: URLs, emoji, emoticons, @/# marks and Vietnamese chat shorthand.

Applied when scenes are built (not inside the voice stage) so the on-screen text, captions and speech all match.
"""

from __future__ import annotations

import re
import unicodedata

URL_RE = re.compile(r"https?://\S+|www\.\S+")
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F\U0000200D]+")
EMOTICON_RE = re.compile(r"[:;=]-?[)(DPp]+|(?<!\w)[xX]D+(?!\w)|\^\^|<3")
TAG_RE = re.compile(r"[@#](?=\w)")

# Common Vietnamese chat shorthand, so comments and posts read aloud naturally.
TEENCODE_VI = {
    "ko": "không", "k": "không", "kh": "không", "hok": "không", "khum": "không",
    "dc": "được", "đc": "được", "vs": "với", "j": "gì", "z": "vậy", "r": "rồi",
    "ng": "người", "mn": "mọi người", "mng": "mọi người", "bth": "bình thường",
    "ms": "mới", "trc": "trước", "cx": "cũng", "cg": "cũng", "bt": "biết",
    "ntn": "như thế nào", "nma": "nhưng mà", "mk": "mình", "mik": "mình", "e": "em",
    "a": "anh", "tr": "trời", "vl": "vãi", "vcl": "vãi", "ib": "nhắn tin", "sp": "sản phẩm",
    "lm": "làm", "đt": "điện thoại", "dt": "điện thoại", "ok": "ô kê", "oke": "ô kê",
}
# Lowercase only (plus "Ko"-style capitals for 2+ letters): a capital "A!" in prose is an interjection, not "anh".
_CODES = sorted(set(TEENCODE_VI) | {k.capitalize() for k in TEENCODE_VI if len(k) > 1}, key=len, reverse=True)
TEENCODE_RE = re.compile(r"(?<![\w@])(" + "|".join(map(re.escape, _CODES)) + r")(?!\w)")


def clean_for_speech(text: str, lang: str = "vi") -> str:
    """Text as it should be read aloud (and shown in captions). Paragraph breaks are kept."""
    text = unicodedata.normalize("NFC", text)
    text = URL_RE.sub("", text)
    text = EMOJI_RE.sub("", text)
    text = EMOTICON_RE.sub("", text)
    if lang == "vi":
        text = TEENCODE_RE.sub(lambda m: TEENCODE_VI[m.group(1).lower()], text)
    text = TAG_RE.sub("", text)
    if lang == "vi":
        from .speech_edit import normalize
        text=normalize(text)
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paras if p)
