"""Limited Southern spelling ambiguity; raw recognition is never rewritten."""

import re
import unicodedata

from ..core.speech_checks import critical_numbers
from ..core.subtitles import Word

SOUTHERN_PROFILES = {"vieneu-gallery-thai-son"}
REFERENCE = (
    "https://www.cambridge.org/core/journals/journal-of-the-international-phonetic-association/article/"
    "div-classtitlestress-and-phrasal-prominence-in-tone-languages-the-case-of-southern-vietnamesediv/"
    "13F3BF93FCA2C9BD365B2AC012C35B7D"
)
REGIONAL_REFERENCE = "https://iris.unive.it/bitstream/10278/5039801/1/Phan%20et%20al%20-%20JSEALS_Special_Publication_9_ISVL1%20UPDATED.pdf"


def _fold_tone(token):
    return unicodedata.normalize("NFD", token.casefold()).replace("\u0303", "\u0309")


def for_alignment(text, recognized, *, southern=False):
    """Match only one-to-one tone-merged spellings; no missing words or consonant edits."""
    expected = re.findall(r"\w+", text.casefold())
    actual = [re.findall(r"\w+", word.text.casefold()) for word in recognized]
    if not southern or critical_numbers(text) or any(len(t) != 1 for t in actual) or len(actual) != len(expected):
        return recognized, []
    result, ambiguities = [], []
    for token, word, raw in zip(expected, recognized, actual, strict=True):
        same_tone = _fold_tone(token) == _fold_tone(raw[0])
        regional_form = {token, raw[0]} == {"giùm", "dùm"}
        if token != raw[0] and (same_tone or regional_form):
            ambiguities.append({"expected": token, "raw": word.text, "start_ms": word.start_ms, "end_ms": word.end_ms})
            result.append(Word(token, word.start_ms, word.end_ms))
        else:
            result.append(word)
    return result, ambiguities
