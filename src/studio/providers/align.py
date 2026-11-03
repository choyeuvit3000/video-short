"""Word timing for providers that return none: faster-whisper alignment, else proportional estimate."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from ..core.errors import ProviderUnavailable
from ..core.logging_utils import get_logger
from ..core.subtitles import Word, estimate_words

log = get_logger()
_models: dict[tuple, object] = {}
_NORM_RE = re.compile(r"[^\w]+", re.UNICODE)


def _norm(t: str) -> str:
    return _NORM_RE.sub("", t.lower())


def faster_whisper_words(audio: Path, lang: str, *, model: str = "small", device: str = "auto",
                         compute_type: str = "auto") -> list[Word]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ProviderUnavailable("faster-whisper not installed (extra [align])", code="align_unavailable") from e
    if device == "auto":
        try:
            import ctranslate2

            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"
    key = (model, device, compute_type)
    m = _models.get(key)
    if m is None:
        log.info("loading faster-whisper %s on %s/%s (first run downloads the model)", model, device, compute_type)
        try:
            m = WhisperModel(model, device=device, compute_type=compute_type)
        except Exception as e:  # download failure, CUDA libs missing...
            raise ProviderUnavailable(f"faster-whisper load failed: {e}", code="align_unavailable") from e
        _models[key] = m
    segments, _ = m.transcribe(str(audio), language=lang, word_timestamps=True, vad_filter=False)
    out = []
    for seg in segments:
        for w in seg.words or []:
            out.append(Word(w.word.strip(), int(w.start * 1000), int(w.end * 1000)))
    return out


def map_onto_text(text: str, recognized: list[Word], duration_ms: int) -> list[Word]:
    """Keep the narration's exact words (spelling, accents) and borrow timings from the recognizer."""
    tokens = text.split()
    if not tokens:
        return []
    if not recognized:
        return estimate_words(text, duration_ms)
    a = [_norm(t) for t in tokens]
    b = [_norm(w.text) for w in recognized]
    times: list[tuple[int, int] | None] = [None] * len(tokens)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            r = recognized[blk.b + k]
            times[blk.a + k] = (r.start_ms, r.end_ms)
    # interpolate gaps between anchors
    i = 0
    n = len(tokens)
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 and times[i - 1] else 0
        right = times[j][0] if j < n and times[j] else duration_ms
        right = max(right, left + 50 * (j - i))
        step = (right - left) / (j - i)
        for k in range(i, j):
            times[k] = (int(left + step * (k - i)), int(left + step * (k - i + 1)))
        i = j
    return [Word(t, s, e) for t, (s, e) in zip(tokens, times, strict=True)]
