"""Editable Vietnamese narration cleanup. Source articles and original stories stay untouched."""

from __future__ import annotations

import re

from .errors import ValidationError

DIGITS = "không một hai ba bốn năm sáu bảy tám chín".split()
TERMS = {
    "PGS.TS": "phó giáo sư, tiến sĩ",
    "ĐGNL": "đánh giá năng lực",
    "TP.HCM": "thành phố Hồ Chí Minh",
    "AI": "trí tuệ nhân tạo",
    "TTS": "giọng đọc máy",
    "LLM": "mô hình ngôn ngữ",
    "pipeline": "quy trình",
    "hook": "câu mở đầu",
    "prompt": "câu lệnh",
    "default": "mặc định",
    "shortcuts": "lối tắt",
    "network": "mạng lưới",
    "clustering": "sự kết nhóm",
}
FOREIGN_NAMES = {"Megan", "Steven", "Stephen", "Jackson", "Allison", "Cassandra", "Gavin", "Warner", "Sherman"}


def integer(n):
    n = int(n)
    if n < 0:
        return "âm " + integer(-n)
    if n < 10:
        return DIGITS[n]
    if n < 100:
        a, b = divmod(n, 10)
        head = "mười" if a == 1 else DIGITS[a] + " mươi"
        tail = "" if not b else " mốt" if b == 1 and a > 1 else " lăm" if b == 5 else " " + DIGITS[b]
        return head + tail
    if n < 1000:
        a, b = divmod(n, 100)
        return DIGITS[a] + " trăm" + ("" if not b else " lẻ " + DIGITS[b] if b < 10 else " " + integer(b))
    for scale, label in [(10**9, "tỷ"), (10**6, "triệu"), (1000, "nghìn")]:
        if n >= scale:
            a, b = divmod(n, scale)
            tail = (
                (" không trăm " + ("lẻ " + DIGITS[b] if b < 10 else integer(b)))
                if 0 < b < 100
                else " " + integer(b)
                if b
                else ""
            )
            return integer(a) + " " + label + tail
    return str(n)


def numeric(s):
    s = s.strip()
    if len(s) > 1 and s.startswith("0") and s.isdigit():
        return " ".join(DIGITS[int(x)] for x in s)
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        return integer(s.replace(".", ""))
    if "," in s or "." in s:
        if len(re.findall("[,.]", s)) > 1:
            raise ValidationError("Cần xác định cách đọc số: " + s, code="speech_ambiguous_number")
        a, b = re.split("[,.]", s, maxsplit=1)
        return integer(a) + " phẩy " + " ".join(DIGITS[int(x)] for x in b)
    return integer(s)


def normalize(text, *, lexicon=None, slash="trên"):
    """5/10 defaults to a ratio; explicit ngày or full d/m/y is a date."""
    if slash not in {"trên", "phần"}:
        raise ValidationError("Choose trên or phần for ratios", code="speech_ratio")
    t = re.sub(
        r"(?i)(gọi|tổng đài|số khẩn cấp)\s+(?:số\s+)?(911|113|114|115)\b",
        lambda m: m[1] + " " + " ".join(DIGITS[int(x)] for x in m[2]),
        text,
    )
    t = re.sub(
        r"\$(\d+(?:[.,]\d+)*)",
        lambda m: numeric(m[1].replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+", m[1]) else m[1]) + " đô la Mỹ",
        t,
    )
    for source, target in sorted((lexicon or {}).items(), key=lambda x: -len(x[0])):
        if not source or not str(target).strip():
            raise ValidationError("Empty pronunciation/name mapping", code="speech_lexicon")
        t = re.sub(r"(?<!\w)" + re.escape(source) + r"(?!\w)", lambda m, target=target: str(target), t, flags=re.I)
    for a, b in TERMS.items():
        t = re.sub(r"\b" + re.escape(a) + r"\b", b, t, flags=0 if a.isupper() else re.I)

    def date(m):
        d, mo, y = m.group(1), m.group(2), m.group(3)
        return integer(d) + " tháng " + integer(mo) + (" năm " + integer(y) if y else "")

    t = re.sub(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", date, t)
    t = re.sub(r"(?i)(ngày\s+)(\d{1,2})/(\d{1,2})\b", lambda m: m[1] + integer(m[2]) + " tháng " + integer(m[3]), t)
    t = re.sub(
        r"(?<!\w)(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)(?!\w)",
        lambda m: numeric(m[1]) + " " + slash + " " + numeric(m[2]),
        t,
    )
    t = re.sub(
        r"(?<!\w)(\d+(?:[.,]\d+)?)\s*[–—-]\s*(\d+(?:[.,]\d+)?)(?!\w)",
        lambda m: numeric(m[1]) + " đến " + numeric(m[2]),
        t,
    )
    t = re.sub(r"(\d{1,2}):(\d{2})", lambda m: integer(m[1]) + " giờ " + integer(m[2]) + " phút", t)
    t = re.sub(r"(?<!\w)-(?=\d)", "âm ", t)
    t = re.sub(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)", lambda m: numeric(m[0]), t)
    t = t.replace("%", " phần trăm").replace("°C", " độ Cê")
    for symbol, spoken in {"+": "cộng", "=": "bằng", "×": "nhân", "÷": "chia", "<": "nhỏ hơn", ">": "lớn hơn"}.items():
        t = t.replace(symbol, " " + spoken + " ")
    t = re.sub(r"\b(?:USD)\b", "đô la Mỹ", t, flags=re.I)
    t = re.sub(r"\b(?:VND|VNĐ)\b", "đồng", t, flags=re.I)
    return re.sub(r"[ \t]+", " ", t).strip()


def issues(text):
    out = []
    if re.search(r"[\d%°/×÷≈±=<>$]", text):
        out.append("Còn chữ số/ký hiệu chưa được chuẩn hóa cách đọc")
    if re.search(r"\b[A-ZĐ]{2,}\b", text):
        out.append("Còn chữ viết tắt cần chốt cách đọc")
    for name in sorted(FOREIGN_NAMES):
        if re.search(r"\b" + name + r"\b", text, re.I):
            out.append("Tên riêng cần bảng tên/cách đọc: " + name)
    return out


def project_edit(folder):
    import json

    p = folder / "project.json"
    if p.is_file():
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        o = d.get("options", {})
        for s in d.get("scenes", []):
            s["narration"] = normalize(
                s.get("narration", ""), lexicon=o.get("speech_lexicon"), slash=o.get("ratio_reading", "trên")
            )
    else:
        p = folder / "vi.json"
        if not p.is_file():
            p = folder / "merged_plan.json"
            if p.is_file():
                d = json.loads(p.read_text(encoding="utf-8-sig"))
                for beat in d.get("beats", []):
                    beat["narration"] = normalize(beat.get("narration", ""))
                p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            return
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        lex = {**d.get("character_map", {}), **d.get("speech_lexicon", {})}
        d["paragraphs"] = [
            normalize(t, lexicon=lex, slash=d.get("ratio_reading", "trên")) for t in d.get("paragraphs", [])
        ]
        if d.get("part_hooks"):
            d["part_hooks"] = [normalize(t, lexicon=lex) for t in d["part_hooks"]]
        if d.get("hook"):
            d["hook"] = normalize(d["hook"], lexicon=lex)
        for role, names in d.get("cast", {}).items():
            if isinstance(names, list):
                d["cast"][role] = [lex.get(n, n) for n in names]
            elif role == "names" and isinstance(names, dict):
                d["cast"][role] = {lex.get(n, n): voice for n, voice in names.items()}
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
