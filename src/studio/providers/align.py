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


def faster_whisper_words(
    audio: Path, lang: str, *, model: str = "small", device: str = "auto", compute_type: str = "auto"
) -> list[Word]:
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


def map_onto_text(text: str, recognized: list[Word], duration_ms: int, *, strict: bool = False) -> list[Word]:
    """Keep the narration's exact words (spelling, accents) and borrow timings from the recognizer."""
    tokens = text.split()
    if not tokens:
        return []
    if not recognized:
        if strict:
            raise ProviderUnavailable("Không nhận được mốc lời nói; cần căn lại phụ đề", code="alignment_review")
        return estimate_words(text, duration_ms)
    if strict:
        from ..core.speech_checks import audit_numbers

        if any(c["evidence"] == "MISSING_MARKER" for c in audit_numbers(text, recognized)["checks"]):
            raise ProviderUnavailable("ASR thiếu từ đọc số quan trọng; cần nghe/sửa, không tự nội suy chữ phẩy", code="speech_number")
    # Ignore hallucinated zero-length/out-of-range tails; normalize numeric ASR tokens to spoken forms.
    from ..core.speech_edit import normalize

    clean = []
    for w in recognized:
        if w.end_ms <= w.start_ms or w.start_ms >= duration_ms or w.end_ms < 0:
            continue
        pieces = normalize(w.text).split()
        for i, t in enumerate(pieces):
            start = max(0, w.start_ms) + (min(duration_ms, w.end_ms) - max(0, w.start_ms)) * i / max(1, len(pieces))
            end = max(0, w.start_ms) + (min(duration_ms, w.end_ms) - max(0, w.start_ms)) * (i + 1) / max(1, len(pieces))
            clean.append(Word(t, int(start), int(end)))
    recognized = clean
    a = [_norm(t) for t in tokens]
    b = [_norm(w.text) for w in recognized]
    times: list[tuple[int, int] | None] = [None] * len(tokens)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    matched = sum(blk.size for blk in sm.get_matching_blocks())
    if strict and matched / max(1, len(tokens)) < 0.9:
        raise ProviderUnavailable(
            "ASR không khớp đủ lời đọc; cần kiểm tra/căn lại trước khi tạo phụ đề", code="alignment_review"
        )
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
    result = []
    cursor = 0
    for t, (s, e) in zip(tokens, times, strict=True):
        s = min(duration_ms - 1, max(cursor, s))
        e = min(duration_ms, max(s + 1, e))
        result.append(Word(t, s, e))
        cursor = e
    return result
