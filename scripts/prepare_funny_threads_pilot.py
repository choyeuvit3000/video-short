"""Prepare an editable, source-bound funny Threads pilot before speech generation."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from studio.social_video.quality import sha256

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "projects/social_video/work/funny_threads/pilot_20261107"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def crop(name, time, bounds):
    source = WORK / "reference_native" / f"{time}.jpg"
    im = Image.open(source)
    box = tuple(round(v * (im.width if i % 2 == 0 else im.height)) for i, v in enumerate(bounds))
    out = WORK / "source_crops" / f"{name}.png"
    out.parent.mkdir(exist_ok=True)
    im.crop(box).save(out)
    return {"path": str(out), "sha256": sha256(out), "reference_time": time, "source_crop_pixels": box}


def main():
    crops = {
        "post": crop("post", 1, (0.067, 0.398, 0.933, 0.603)),
        "author_image": crop("author_image", 12.5, (0.067, 0.275, 0.933, 0.726)),
        "comment_1": crop("comment_1", 15, (0.067, 0.427, 0.933, 0.533)),
        "comment_1_photo": crop("comment_1_photo", 17.5, (0.069, 0.259, 0.931, 0.932)),
        "comment_2": crop("comment_2", 20, (0.067, 0.253, 0.933, 0.874)),
        "comment_3": crop("comment_3", 23, (0.041, 0.256, 0.906, 0.874)),
    }
    source = next(Path("C:/Users/Administrator/Downloads").glob("*UxPHHJbIr74*.mp4"))
    provenance = {
        "platform": "threads",
        "author": "nhinguyen_207",
        "url": None,
        "capture_method": (
            "Authentic screenshot regions extracted from the creator-supplied reference video, "
            "not a new Threads capture"
        ),
        "reference_video": str(source),
        "reference_video_sha256": sha256(source),
        "reference_creator_credit": "NẮNG AUDIO; user-supplied video UxPHHJbIr74",
        "original_thread_url_status": "NOT_SUPPLIED_NOT_VERIFIED",
        "use": "Local editorial pilot for creator review; no upload authorized",
        "crops": crops,
    }
    write(WORK / "source.json", provenance)
    beats = [
        {
            "id": "post",
            "kind": "post",
            "author": "nhinguyen_207",
            "source_crop": "post",
            "voice": "Ngọc Huyền",
            "region": "Bắc",
            "gender": "female",
            "speed": 1.15,
            "narration": (
                "Góc con gái. Có bà nào thấy việc hở chân ngực có nét riêng hơn là hở khe ngực không? "
                "Tại lâu lâu tôi vén áo lên, thấy hở một ít dưới chân ngực rất đẹp luôn."
            ),
            "label": "BÀI GỐC",
            "post_pause_seconds": 0.5,
        },
        {
            "id": "author_image",
            "kind": "post",
            "author": "nhinguyen_207",
            "source_crop": "author_image",
            "voice": "Ngọc Huyền",
            "region": "Bắc",
            "gender": "female",
            "speed": 1.15,
            "narration": "Lục tung cái Pin để tìm ra giống cái ý tui nói.",
            "label": "CHỦ BÀI ĐƯA ẢNH",
            "post_pause_seconds": 0.45,
        },
        {"id": "reaction_1", "kind": "reaction", "narration": "", "reaction": "xin-anh-minh-hoa", "duration": 1.2},
        {
            "id": "comment_1",
            "kind": "comment",
            "author": "phanva_yve",
            "source_crop": "comment_1",
            "media_crop": "comment_1_photo",
            "voice": "Mỹ Duyên",
            "region": "Nam",
            "gender": "female",
            "speed": 1.15,
            "narration": "Này hở chân ngực nè, nhưng mà hơi răm quá. Hãng Barbie gì á, tui quên rồi.",
            "label": "BÌNH LUẬN MỘT",
            "post_pause_seconds": 0.6,
        },
        {
            "id": "comment_2",
            "kind": "comment",
            "author": "gnasche_f",
            "source_crop": "comment_2",
            "voice": "Quang Sơn",
            "region": "Trung",
            "gender": "male",
            "speed": 1.15,
            "narration": "Như này hả bà?",
            "min_duration": 3.2,
            "label": "BÌNH LUẬN HAI",
            "post_pause_seconds": 0.6,
        },
        {
            "id": "comment_3",
            "kind": "comment",
            "author": "phungmy51",
            "source_crop": "comment_3",
            "voice": "Minh Đức",
            "region": "Bắc",
            "gender": "male",
            "speed": 1.15,
            "narration": "Này đúng không?",
            "min_duration": 3.2,
            "label": "BÌNH LUẬN BA",
            "post_pause_seconds": 0.6,
        },
        {"id": "reaction_2", "kind": "reaction", "narration": "", "reaction": "binh-luan-thanh-album", "duration": 1.6},
        {
            "id": "closing",
            "kind": "editorial",
            "voice": "Ngọc Huyền",
            "region": "Bắc",
            "gender": "female",
            "speed": 1.15,
            "narration": "Hỏi gu mặc áo, bình luận thành album luôn. Bạn thấy ai hiểu đề nhất?",
            "label": "BẠN THẤY AI HIỂU ĐỀ NHẤT?",
            "post_pause_seconds": 0.35,
        },
    ]
    plan = {
        "mode": "funny_threads",
        "project_id": WORK.name,
        "title": "Hỏi gu mặc áo, bình luận thành album",
        "source": provenance,
        "beats": beats,
        "status": "SCRIPT_PENDING_CREATOR",
        "render_kind": "requested_pilot_for_review",
        "audio_policy": {
            "cast_per_comment": True,
            "pause_between_comments_seconds": 0.6,
            "speech_speed": 1.15,
            "music_relative_to_voice_db": -22,
            "no_speech_time_stretch_after_acceptance": True,
            "note": "Voice casting is performed reading, not a claim about the real commenters' genders or accents.",
        },
        "normalization_notes": [
            "niche → có nét riêng",
            "t → tôi; nma → nhưng mà; Brand → hãng",
            "hở bà → hả bà; nì đúng hem → này đúng không; emojis not spoken",
            "Original screenshot text remains unchanged; spoken reading is lightly normalized.",
        ],
        "background": {
            "path": str(ROOT / "assets/shared/backgrounds/29503c8f6bf4_015.mp4"),
            "start_seconds": 5,
            "darken": 0.20,
            "selection": "local user-imported Minecraft, separate from the reference",
        },
        "music_id": "music:kevin-macleod/fluffing-a-duck",
        "cover": {
            "duration_frames": 3,
            "fps": 30,
            "placement": "middle",
            "standalone_png": str(WORK / "cover_preview.png"),
        },
        "review_policy": {
            "maximum_creator_checkpoints": 3,
            "approvals": [],
            "script": "PENDING",
            "voice_mix": "PENDING",
            "final": "PENDING",
        },
    }
    write(WORK / "merged_plan.json", plan)
    write(
        WORK / "posts.json",
        [
            {
                "author": "nhinguyen_207",
                "url": None,
                "platform": "threads",
                "parts": [crops[k]["path"] for k in ["post", "author_image"]],
                "part_texts": [b["narration"] for b in beats if b["kind"] == "post"],
                "comments": [
                    {"author": b["author"], "text": b["narration"], "image": crops[b["source_crop"]]["path"]}
                    for b in beats
                    if b["kind"] == "comment"
                ],
                "media": [],
                "provenance": provenance["capture_method"],
            }
        ],
    )
    write(
        WORK / "video_brief.json",
        {
            "answers": {
                "goal": "Một video funny Threads để người tạo duyệt phong cách và dàn giọng",
                "audience": "Người Việt xem riêng tư, thích ảnh bài và bình luận vui",
                "platform": "private",
                "target_seconds": 45,
                "source_policy": "faithful",
                "narration": "verbatim",
                "voice": "vieneu-gallery-ngoc-huyen",
                "speech_speed": 1.15,
                "background": "minecraft",
                "subtitles": "none",
                "pacing": "brisk",
                "reference": (
                    "Four creator-supplied funny Threads reference videos; "
                    "explicit later Minecraft and multi-voice preference"
                ),
            }
        },
    )
    # Visual composition uses genuine screenshot pixels. Only editorial labels are drawn.
    ink, yellow, paper = "#152b24", "#ffdc5d", "#fff8e8"
    im = Image.new("RGB", (1080, 1920), ink)
    d = ImageDraw.Draw(im)

    def bold(size):
        return ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", size)

    d.rounded_rectangle((64, 172, 386, 229), radius=10, fill=yellow)
    d.text((84, 185), "THREADS VUI", font=bold(34), fill=ink)
    d.text((65, 284), "HỎI GU MẶC ÁO", font=bold(78), fill=paper)
    d.text((64, 397), "BÌNH LUẬN", font=bold(108), fill=paper)
    d.text((64, 529), "THÀNH ALBUM", font=bold(100), fill=yellow)
    card = Image.open(crops["comment_2"]["path"]).convert("RGB")
    card = ImageOps.contain(card, (830, 1000), Image.Resampling.LANCZOS)
    x, y = (1080 - card.width) // 2, 735
    d.rounded_rectangle((x - 9, y - 9, x + card.width + 9, y + card.height + 9), radius=15, fill=paper)
    im.paste(card, (x, y))
    cat = Image.open(ROOT / "assets/shared/overlays/funny_originals/binh-luan-thanh-album/binh-luan-thanh-album.png")
    cat = cat.crop((130, 100, 590, 490)).resize((230, 195), Image.Resampling.LANCZOS)
    im.paste(cat, (820, 650))
    d.text((64, 1810), "Nguồn bài: @nhinguyen_207", font=bold(28), fill=paper)
    im.save(WORK / "cover_preview.png")
    # Include all actual voice choices and full text in the reviewable script.
    lines = [
        "# Video thử funny Threads — chờ duyệt kịch bản",
        "",
        "Dọc 1080 × 1920, khoảng 40–50 giây theo tiếng thực; không ép đủ thời lượng.",
        "Nguồn ảnh: trích vùng bài/bình luận từ video mẫu UxPHHJbIr74 do bạn gửi; chưa xác minh được URL bài gốc.",
        "Giữ nguyên chữ trên ảnh; lời đọc dưới đây đã chuẩn hóa tiếng lóng/viết tắt.",
        "Các giọng mới vẫn là giọng thử cho video này, cần bạn nghe bản phối; không tự thêm vào random.",
        "",
    ]
    for b in beats:
        lines += [f"## {b['id']} — {b.get('label', 'Meme')}", ""]
        if b.get("narration"):
            lines += [
                f"Giọng: {b['voice']} — {b['gender']}, miền {b['region']}, tốc độ một phẩy mười lăm.",
                "",
                b["narration"],
                "",
            ]
        else:
            lines += [f"Meme gốc của dự án: {b['reaction']}; {b['duration']} giây.", ""]
    lines += [
        "Nhạc: Fluffing a Duck — Kevin MacLeod, CC BY 4.0; nhỏ dưới giọng, ngắt nhẹ trước phản ứng.",
        "SFX ngắn: pop, boing, ding; không lặp cùng một cue. Nghỉ khoảng sáu phần mười giây giữa các bình luận.",
        "Nền Minecraft riêng giảm sáng hai mươi phần trăm; ảnh bìa ba khung hình giữa clip, xuất thêm PNG.",
        (
            "Tham khảo mới L_Wex-oc6_8: học cú đối chiếu bài/bình luận và bìa ảnh phản ứng + thẻ bài, "
            "không bê lại toàn bộ video."
        ),
    ]
    (WORK / "KICH_BAN_DUYET.md").write_text("\n".join(lines), encoding="utf-8")
    print(WORK / "KICH_BAN_DUYET.md")


if __name__ == "__main__":
    main()
