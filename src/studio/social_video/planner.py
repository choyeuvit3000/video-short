"""Edit plan ("EDL"): which post goes where, what is said, which meme pops when.

Backends:
  api        Anthropic API (needs ANTHROPIC_API_KEY or an `ant auth login` profile)
  cli        Claude Code headless: `claude -p` (needs `claude` logged in once)
  heuristic  keyword rules, no AI
  manual     write plan_request.md and stop; Claude Code fills plan.json
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess

from .util import log

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "intro_narration": {"type": "string"},
        "outro_narration": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "post_index": {"type": "integer"},
                    "hook": {"type": "string"},
                    "narration": {"type": "string"},
                    "memes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "at": {"type": "number"},
                                "duration": {"type": "number"},
                                "image_id": {"type": "string"},
                                "caption_top": {"type": "string"},
                                "caption_bottom": {"type": "string"},
                                "sound_id": {"type": "string"},
                            },
                            "required": ["at", "duration", "image_id", "caption_top",
                                         "caption_bottom", "sound_id"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["post_index", "hook", "narration", "memes"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "intro_narration", "outro_narration", "segments"],
    "additionalProperties": False,
}

NARRATION_RULES = {
    "summary": "1-3 câu tiếng Việt (tối đa ~45 từ): tóm ý chính của bài + một câu bình luận dí dỏm. "
               "Bài tiếng Anh thì tóm tắt bằng tiếng Việt.",
    "read": "Đọc lại nội dung bài bằng tiếng Việt tự nhiên (tối đa ~80 từ), đổi teencode/viết tắt "
            "thành chữ đầy đủ, dịch nếu là tiếng Anh.",
    "none": "Để chuỗi rỗng.",
}


def build_prompt(posts: list[dict], lib: dict, cfg: dict, day: str) -> str:
    max_memes = cfg["memes"]["per_segment_max"]
    mode = cfg["narration_mode"] if cfg["tts"]["enabled"] else "none"
    post_lines = []
    for p in posts:
        cmts = "\n".join(f"    - @{c['author']}: {c['text'][:300]}" for c in p["comments"])
        post_lines.append(
            f"[{p['index']}] @{p['author']} ({p['time']})\n{p['text'][:1800]}"
            + (f"\n  Bình luận nổi bật:\n{cmts}" if cmts else ""))
    images = [i for i in lib["items"] if i["kind"] == "image"]
    sounds = [i for i in lib["items"] if i["kind"] == "sound"]
    img_lines = "\n".join(
        f"{i['id']} | {i['name']}" + (f" | {i['panels']} ô chữ" if i.get("panels", 1) > 1 else "")
        + (" | gif" if i.get("animated") else "") for i in images)
    snd_lines = "\n".join(
        f"{s['id']} | {s['name']} | {s.get('duration', 0):.1f}s"
        + (" | VN" if s.get("tag") in ("vn-trending", "vn-curated") else "") for s in sounds)

    return f"""Bạn là biên tập viên video ngắn (9:16) cho một người Việt xem riêng tư mỗi sáng.
Video ngày {day} ghép ảnh chụp các bài Threads dưới đây, có giọng đọc AI tiếng Việt và chèn meme
(ảnh bật lên + hiệu ứng âm thanh) để xem cho vui và nắm nhanh thông tin.

## Bài đăng
{chr(10).join(post_lines)}

## Thư viện ảnh meme (id | tên)
{img_lines or "(trống)"}

## Thư viện âm thanh meme (id | tên | độ dài; VN = đang hot ở Việt Nam)
{snd_lines or "(trống)"}

## Yêu cầu
- segments: mỗi bài đúng một segment, có thể sắp lại thứ tự (bài hay/quan trọng lên trước). post_index là số trong [ ].
- hook: tít ngắn tối đa 8 từ, gây tò mò, hiện ở đầu khung hình.
- narration: {NARRATION_RULES[mode]} Viết số, ký hiệu, viết tắt thành chữ để máy đọc đúng. Không emoji.
- intro_narration: 1 câu chào + tóm tắt hôm nay có gì. outro_narration: 1 câu kết ngắn. (Để rỗng nếu narration là rỗng.)
- memes: 0-{max_memes} cái mỗi segment, chỉ chèn khi thật sự hợp ngữ cảnh/punchline; bài nghiêm túc hoặc nhạy cảm (tang sự, tai nạn, bệnh tật, tranh chấp) thì không chèn.
  - at: vị trí trong segment, tỉ lệ 0.0-1.0 (punchline thường ở 0.6-0.9). duration: 1.2-3.0 giây.
  - image_id / sound_id: chỉ dùng id có trong thư viện, hoặc "" nếu không dùng. Có thể chỉ có âm thanh hoặc chỉ có ảnh.
  - caption_top / caption_bottom: chữ meme tiếng Việt (tối đa 6 từ) viết đè lên ảnh; chỉ dùng với meme 1 bức ảnh (ảnh ghép nhiều khung như Drake, Expanding Brain hoặc gif thì để "").
  - Ưu tiên âm thanh VN khi hợp; không dùng lại cùng một meme hai lần trong video.
- title: tên video ngắn.
Chỉ trả về một object JSON đúng các khóa trên, không kèm giải thích."""


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def _image_block(path) -> dict:
    """Downscale to the API's useful size and send as base64 JPEG."""
    import base64
    import io

    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((1568, 1568))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                       "data": base64.b64encode(buf.getvalue()).decode()}}


def plan_with_api(prompt: str, cfg: dict, schema: dict = SCHEMA,
                  images: list | None = None) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    content = [_image_block(p) for p in images or []] + [{"type": "text", "text": prompt}]
    # fallbacks="default": if a safety classifier declines, the API retries on
    # Anthropic's recommended fallback model inside the same call.
    resp = client.beta.messages.create(
        model=cfg["ai"]["api_model"],
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": cfg["ai"]["effort"],
                       "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude từ chối yêu cầu (refusal)")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def plan_with_cli(prompt: str, cfg: dict, cwd=None) -> dict:
    """With `cwd` set, Claude may use its Read tool there to look at screenshots."""
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("không tìm thấy lệnh claude")
    cmd = [exe, "-p", "--output-format", "json"]
    if cwd:
        cmd += ["--allowedTools", "Read"]
    if cfg["ai"]["cli_model"]:
        cmd += ["--model", cfg["ai"]["cli_model"]]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd,
                          encoding="utf-8", errors="replace", timeout=900)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p trả về không phải JSON: {proc.stdout[:300]} {proc.stderr[:300]}")
    if data.get("is_error"):
        raise RuntimeError(f"claude -p lỗi: {data.get('result')}")
    return _extract_json(data["result"])


SOUND_HINTS = [
    (r"haha|hihi|=\)\)|lol|cười|vui|hài|😂|🤣", ["laugh", "cười", "hahaha", "baby laughing"]),
    (r"buồn|sad|tiếc|khóc|huhu|mệt", ["sad violin", "violin", "mệt mỏi"]),
    (r"wow|đỉnh|xịn|quá trời|amazing|kỷ lục|10 điểm", ["anime wow", "wow", "10 điểm", "ghê chưa"]),
    (r"\?\s*$|sao vậy|tại sao|why|huh", ["huh", "what"]),
    (r"sếp|deadline|họp|meeting|tăng ca|OT", ["oi doi oi", "ối dồi ôi", "bruh"]),
]


def plan_heuristic(posts: list[dict], lib: dict, cfg: dict) -> dict:
    rng = random.Random(len(posts))
    sounds = [i for i in lib["items"] if i["kind"] == "sound" and i.get("duration", 0) <= 4]
    images = [i for i in lib["items"] if i["kind"] == "image" and i.get("panels", 1) <= 2]
    used: set[str] = set()

    def pick_sound(text: str) -> str:
        for pattern, names in SOUND_HINTS:
            if re.search(pattern, text, re.I):
                for s in sounds:
                    if s["id"] not in used and any(n in s["name"].lower() for n in names):
                        used.add(s["id"])
                        return s["id"]
        fresh = [s for s in sounds if s["id"] not in used]
        if not fresh:
            return ""
        s = rng.choice(fresh)
        used.add(s["id"])
        return s["id"]

    segments = []
    for p in posts:
        # Captured text starts with "author\ndate\n"; skip those two lines.
        lines = p["text"].split("\n", 2)
        body = lines[2] if len(lines) > 2 else p["text"]
        body = body.split("\n---\n")[0]
        # drop like/reply/repost counters such as "2,1K" or "630"
        body = "\n".join(ln for ln in body.split("\n")
                         if not re.fullmatch(r"[\d.,]+\s*[KkMm]?", ln.strip()))
        hook = " ".join(body.split()[:8])
        narration = "" if cfg["narration_mode"] == "none" else " ".join(body.split()[:60])
        image = rng.choice(images)["id"] if images and rng.random() < 0.6 else ""
        segments.append({
            "post_index": p["index"], "hook": hook, "narration": narration,
            "memes": [{"at": 0.85, "duration": 2.0, "image_id": image, "caption_top": "",
                       "caption_bottom": "", "sound_id": pick_sound(p["text"])}],
        })
    talk = cfg["narration_mode"] != "none"
    return {
        "title": "Threads hôm nay",
        "intro_narration": f"Hôm nay có {len(posts)} bài Threads mới, xem nhanh nhé." if talk else "",
        "outro_narration": "Hết rồi, hẹn gặp lại ngày mai." if talk else "",
        "segments": segments,
    }


def normalize(plan: dict, posts: list[dict], lib: dict, cfg: dict) -> dict:
    """Drop unknown ids, clamp numbers, make sure every post appears once."""
    ids = {i["id"]: i for i in lib["items"]}
    max_memes = cfg["memes"]["per_segment_max"]
    seen, segments = set(), []
    for seg in plan.get("segments", []):
        idx = seg.get("post_index")
        if not isinstance(idx, int) or idx in seen or not 0 <= idx < len(posts):
            continue
        seen.add(idx)
        memes = []
        for m in seg.get("memes", [])[:max_memes]:
            img = m.get("image_id", "")
            snd = m.get("sound_id", "")
            img = img if ids.get(img, {}).get("kind") == "image" else ""
            snd = snd if ids.get(snd, {}).get("kind") == "sound" else ""
            if not img and not snd:
                continue
            memes.append({
                "at": min(max(float(m.get("at", 0.8)), 0.05), 0.95),
                "duration": min(max(float(m.get("duration", 2.0)), 0.8), 4.0),
                "image_id": img, "sound_id": snd,
                "caption_top": (m.get("caption_top") or "")[:60] if img else "",
                "caption_bottom": (m.get("caption_bottom") or "")[:60] if img else "",
            })
        segments.append({"post_index": idx, "hook": (seg.get("hook") or "")[:80],
                         "narration": seg.get("narration") or "", "memes": memes})
    fallback = plan_heuristic(posts, lib, cfg)["segments"]
    segments += [s for s in fallback if s["post_index"] not in seen]
    return {
        "title": plan.get("title") or "Threads hôm nay",
        "intro_narration": plan.get("intro_narration") or "",
        "outro_narration": plan.get("outro_narration") or "",
        "segments": segments,
    }


def make_plan(posts: list[dict], lib: dict, cfg: dict, day: str, backend: str) -> tuple[dict, str]:
    prompt = build_prompt(posts, lib, cfg, day)
    order = {"auto": ["api", "cli", "heuristic"], "api": ["api"], "cli": ["cli"],
             "heuristic": ["heuristic"]}[backend]
    if backend == "auto" and not has_api_key():
        order.remove("api")
    for name in order:
        try:
            log(f"Lập kịch bản bằng: {name}")
            if name == "api":
                raw = plan_with_api(prompt, cfg)
            elif name == "cli":
                raw = plan_with_cli(prompt, cfg)
            else:
                raw = plan_heuristic(posts, lib, cfg)
            return normalize(raw, posts, lib, cfg), name
        except Exception as exc:
            log(f"  {name} không dùng được: {exc}")
            if backend != "auto":
                raise
    raise RuntimeError("Không lập được kịch bản")
