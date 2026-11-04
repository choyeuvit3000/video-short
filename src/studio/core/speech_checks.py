"""Pronunciation evidence stays separate from semantic ASR number expansion."""

from __future__ import annotations

import hashlib
import json
import re

NUMBER_WORDS = set(
    "không một hai ba bốn tư năm lăm sáu bảy tám chín mười mươi trăm nghìn ngàn triệu tỷ lẻ linh âm".split()
)


def critical_numbers(text):
    tokens = list(re.finditer(r"\w+", text.casefold()))
    found = []
    for i, token in enumerate(tokens):
        if token[0] not in {"phẩy", "trên", "phần"} or not 0 < i < len(tokens) - 1:
            continue
        if tokens[i - 1][0] not in NUMBER_WORDS or tokens[i + 1][0] not in NUMBER_WORDS:
            continue
        left, right = i - 1, i + 1
        while left > 0 and tokens[left - 1][0] in NUMBER_WORDS:
            left -= 1
        while right < len(tokens) - 1 and tokens[right + 1][0] in NUMBER_WORDS:
            right += 1
        found.append({"phrase": text[tokens[left].start() : tokens[right].end()], "marker": token[0]})
    return found


def audit_numbers(text, recognized):
    raw = " ".join(w.text for w in recognized)
    raw_tokens = re.findall(r"\w+", raw.casefold())
    checks = critical_numbers(text)
    for check in checks:
        marker = check["marker"]
        needed = sum(c["marker"] == marker for c in checks)
        explicit = raw_tokens.count(marker)
        symbolic = bool(re.search(r"\d\s*[,.]\s*\d" if marker == "phẩy" else r"\d\s*/\s*\d", raw))
        if marker == "phần" and re.search(r"\d\s*[%‰]", raw):
            symbolic = True
        check["evidence"] = (
            "ASR_MARKER_PRESENT" if explicit >= needed else "ASR_NUMERIC_AMBIGUOUS" if symbolic else "MISSING_MARKER"
        )
    return {
        "status": "REVIEW_REQUIRED" if checks else "NO_CRITICAL_NUMBER",
        "raw_transcript": raw,
        "checks": checks,
        "instruction": (
            "Nghe chữ phẩy/trên/phần trong tệp thật. ASR trả chữ số không chứng minh phát âm đủ; "
            "không tự duyệt bằng điểm khớp phụ đề."
        ),
    }


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def text_sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def save_audit(folder, scene_id, audio, text, recognized, *, source="faster_whisper"):
    report = audit_numbers(text, recognized)
    report.update(audio_sha256=file_sha(audio), text_sha256=text_sha(text), recognition_source=source)
    out = folder / "work/speech_checks" / (scene_id + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
