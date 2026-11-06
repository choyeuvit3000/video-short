"""Prepare the creator-requested visual-only Flow trial from existing Cồn Mù artwork.

No TTS, account automation, paid generation, approvals, or production render is performed.
Reruns preserve imported clips and the original story's approval ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from studio.core.errors import ManualGateRequired
from studio.core.project import ProjectContext, scaffold
from studio.core.schema import Project
from studio.pipeline.runner import RunOptions, run_pipeline

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "flow_trials" / "con_mu_20261106"
ART = ROOT / "assets" / "shared" / "story_illustrations" / "con_mu_stick_v1"
STYLE = (
    "Use the uploaded image as the exact starting frame. Make one continuous eight-second "
    "16:9 animated shot in this same hand-drawn ink and muted watercolor stick-figure style "
    "on textured paper. Locked tripod camera: absolutely no zoom, pan, tilt, roll, shake, "
    "parallax or reframing. Preserve every person's identity, face, anatomy, clothing and "
    "proportions. Animate the one basic character action specified below; all other "
    "people and objects remain still. Use natural restrained movement. No new people, extra limbs, "
    "photorealism, 3D, speech, lip movement, captions, transitions, cuts or new text. "
    "Keep the paper and ink outlines stable. Do not add music or voices. "
)
SHOTS = [
    ("ferry_night", "Hạnh ngẩng đầu", (
        "Hạnh, the seated woman in brown on the right, slowly raises her head from the cloth bag "
        "to look at An, the man in blue on the left, blinks once and holds the new gaze. "
        "Her hands remain around the same cloth bag on her lap, feet stay on the floor. "
        "An, the engine including flywheel, boat and background remain still. "
        "Keep mist at its original thin density, no growing fog or steam. No speaking or standing."
    )),
    ("yellow_sandals", "Nước nhỏ từ vạt áo", (
        "The seated woman slowly slides both yellow-sandaled feet backwards together by three "
        "centimeters, then rests them on the floor. Keep the feet, toes and sandals intact. "
        "Her brown hem follows with a tiny natural sway. A few clear water drops fall into "
        "the existing puddle. No walking, standing, lifting feet or extra limbs."
    )),
    ("hanh_altar", "Bà Bảy chỉ di ảnh", (
        "The elderly woman with white hair and olive blouse slowly raises her nearer arm "
        "and points toward the framed portrait, then holds the gesture. Keep the same thin "
        "drawn arm, one hand with normal anatomy, no extra limbs or photorealistic fingers. "
        "The man stays still. Very thin incense smoke rises slowly. The portrait must remain "
        "a completely static drawing. Keep the single shoe, cloth bag, room and morning light intact."
    )),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(flow_url: str = "") -> None:
    scenes = []
    for i, (key, _, motion) in enumerate(SHOTS, 1):
        scenes.append({
            "scene_id": f"scene_{i:02d}", "duration_sec": 8, "narration": "",
            "visual": {"type": "clip", "path": f"clips/scene_{i:02d}.mp4", "fit_mode": "pad"},
            "image_prompt": f"Existing approved Cồn Mù artwork: {key}.png; do not regenerate.",
            "video_prompt": STYLE + motion,
            "source_note": "Visual experiment only; story fiction, not real-case footage.",
        })
    if not (PROJECT / "project.json").exists():
        scaffold(PROJECT, Project.model_validate({
            "project_id": "con_mu_flow_trial_20261106", "workflow": "ai_cinematic",
            "title": "Cồn Mù — thử chuyển động nhân vật", "language": "vi",
            "description": "Thử nghiệm hình ảnh hư cấu. Chưa phải bản thay thế video đã duyệt.",
            "platforms": [], "timing_mode": "fixed", "ai_generated": True,
            "video": {"format": "long_16x9", "subtitle_mode": "none", "background": "color:#000000"},
            "audio": {"source": "manual", "speed": 1.0},
            "options": {"allow_still_fallback": False, "strict_clip_validation": True, "require_video_clips": True,
                        "clip_min_short_side": 720, "scene_count": 3, "clip_sec": 8,
                        "experiment_only": True, "flow_project_url": flow_url},
            "scenes": scenes,
        }))
    ctx = ProjectContext(PROJECT)
    ctx.project.title = "Cồn Mù — thử chuyển động nhân vật"
    for scene, (_, _, action) in zip(ctx.project.scenes, SHOTS, strict=True):
        scene.video_prompt = STYLE + action
    if flow_url:
        ctx.project.options["flow_project_url"] = flow_url
    flow_url = ctx.project.options.get("flow_project_url", "")
    ctx.project.options.update(allow_still_fallback=False, require_video_clips=True, strict_clip_validation=True)
    ctx.save()
    # A fixed output day is shared with any later resume; no host-date ambiguity.
    location = ctx.work / "output_location.json"
    if not location.exists():
        location.write_text('{"date":"2026-11-06","mode":"ai_cinematic"}', encoding="utf-8")
    bundle = ctx.work / "flow_handoff"
    bundle.mkdir(exist_ok=True)
    library = json.loads((ART / "library.json").read_text(encoding="utf-8"))
    # Library root includes descriptive fields as well as its asset array.
    entries = next(v for v in library.values() if isinstance(v, list) and v
                   and isinstance(v[0], dict) and "asset_key" in v[0])
    by_key = {a["asset_key"]: a for a in entries}
    manifest = {"scope": "VISUAL_EXPERIMENT_ONLY", "provider": "Google Flow web",
                "flow_project_url": flow_url, "model_requested": "Veo 3.1 - Fast",
                "user_request": "thử nghiệm luồng bán thủ công video AI đi",
                "provider_choice": "Google Flow (đề xuất)",
                "human_approval_created": False,
                "planned_attempts": 4, "automatic_retry": False,
                "revision_request": "cho nhân vật chuyển động cơ bản đi mới xứng đáng hơn ảnh tĩnh chứ",
                "revision_note": "One environment-only baseline plus three character-action shots", "shots": []}
    sheet = Image.new("RGB", (960, 3 * 304), "#eee5d7")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 23)
    lines = ["# Cồn Mù — thử nghiệm Google Flow", "", "Ba cảnh, mỗi cảnh tám giây, khung ngang.",
             "Chỉ thử chuyển động nhân vật; không thay video đã duyệt, không tạo giọng mới.",
             "Mỗi cảnh một kết quả. Dừng để đánh giá trước khi gen lại.", "",
             f"Dự án Flow: {flow_url or 'Chưa tạo trên web'}", "", "## Thao tác từng cảnh", "",
             "Tải PNG tương ứng lên Flow → chọn làm khung hình đầu → dán prompt cùng tên.",
             "Chọn video, Veo 3.1 Fast, mười sáu trên chín, một kết quả, tám giây.",
             "Kiểm tra số tín dụng trong hộp xác nhận. Không mua thêm hay đổi gói.",
             "Giữ watermark nếu có. Tải bản gốc, lưu đúng đường dẫn clip bên dưới.", ""]
    for i, (key, title, _) in enumerate(SHOTS, 1):
        scene = ctx.project.scene(f"scene_{i:02d}")
        source = ART / f"{key}.png"
        if sha(source) != by_key[key]["sha256"]:
            raise RuntimeError(f"Approved source hash changed: {source}")
        image = bundle / f"{scene.scene_id}.png"
        shutil.copy2(source, image)
        shutil.copy2(source, PROJECT / "images" / image.name)
        prompt = bundle / f"{scene.scene_id}.prompt.txt"
        prompt.write_text(STYLE + SHOTS[i - 1][2] + "\n", encoding="utf-8")
        preview = Image.open(source).convert("RGB")
        preview.thumbnail((480, 270))
        y = (i - 1) * 304
        sheet.paste(preview, (0, y + 34))
        draw.text((12, y + 5), f"{i}. {title}", fill="#292622", font=font)
        draw.text((500, y + 80), "Máy quay cố định\nChuyển động rất nhẹ\nMột clip · tám giây",
                  fill="#292622", font=font, spacing=12)
        manifest["shots"].append({"scene_id": scene.scene_id, "title": title,
                                  "keyframe": str(image), "source": str(source),
                                  "keyframe_sha256": sha(image), "prompt": str(prompt),
                                  "prompt_sha256": sha(prompt), "target": str(ctx.resolve(scene.visual.path)),
                                  "status": "PRESENT_NEEDS_QC" if ctx.resolve(scene.visual.path).is_file()
                                  else "WAITING_FOR_REAL_CLIP"})
        lines += [f"### {i}. {title}", f"- Ảnh: `{image}`", f"- Prompt: `{prompt}`",
                  f"- Clip nhập về: `{ctx.resolve(scene.visual.path)}`", ""]
    sheet.save(bundle / "contact_sheet.jpg", quality=94)
    lines += ["## Kiểm tra trước khi ghép", "",
              "Clip phải có hình động thật, đủ tám giây, tỷ lệ mười sáu trên chín, "
              "cạnh ngắn ít nhất bảy trăm hai mươi điểm ảnh.",
              "Xem đầu/giữa/cuối: không rung máy, không đổi nét vẽ, mặt, tay, số người, màu dép hoặc đạo cụ.",
              "Giữ nguyên ảnh thiếu clip ở trạng thái chờ; không lấy ảnh zoom để đánh dấu hoàn tất.",
              "Âm thanh Flow không được tự thay lời Ngọc Huyền đã duyệt. Bản thử hình có thể không tiếng.",
              "Đây là kiểm tra tài sản hình, không tạo phiếu duyệt giả hoặc tiêu tốn thêm một mốc duyệt video.", "",
              "Sau khi nhập đủ clip, chạy bước media để xác nhận:", "", "```powershell",
              f'.\\.venv\\Scripts\\python.exe -m studio run "{PROJECT}" --only media', "```", "",
              "QC kỹ thuật không thay thế việc xem lỗi biến dạng. Bản ghép thử phải được gắn nhãn thử nghiệm."]
    (bundle / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (PROJECT / "FLOW_HANDOFF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        run_pipeline(ctx, RunOptions(only=["storyboard", "media"]))
    except ManualGateRequired:
        print(f"WAITING_FOR_REAL_CLIPS: {PROJECT / 'FLOW_HANDOFF.md'}")
    print(bundle)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow-url", default="", help="URL dự án Flow hiện có; không tự mở web")
    main(parser.parse_args().flow_url)
