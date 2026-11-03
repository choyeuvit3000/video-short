# video-short · AI Shorts Studio v2

Studio dựng video ngắn/dài chạy trên Windows, ưu tiên công cụ local và miễn phí. Có nhiều **workflow** theo thể loại và mức chi phí (đọc bài Reddit/Threads, slideshow ảnh AI, clip Google Flow, ...). Mỗi workflow dùng chung một lõi gồm FFmpeg, giọng đọc, caption từng từ, QC và đóng gói.

- **Tool có sẵn chạy trước, AI chỉ dùng khi cần.** Ghép, cắt, caption, mix nhạc, QC đều do FFmpeg và Python đảm nhận. AI CLI (Claude / agy / Codex) chỉ viết kịch bản, dịch và làm storyboard.
- **Bước AI trên web là bước thủ công có checklist** (ChatGPT ảnh, Google Flow video). Tool không scrape, không tự click và không lưu cookie.
- **Giọng đọc quản lý tập trung** trong `voices/`, gồm ba loại: free (edge-tts), local (Piper CPU, sau này thêm GPU) và API trả phí (mặc định tắt, có trần ngân sách).
- **Thiết kế cho nhiều máy.** Laptop là máy điều khiển; PC RTX 3080 ở nhà là GPU node (worker sẽ có ở milestone M3.5).

## Bắt đầu nhanh (laptop)

Hướng dẫn đầy đủ: [docs/SETUP_LAPTOP.md](docs/SETUP_LAPTOP.md). Tóm tắt:

```powershell
winget install Gyan.FFmpeg astral-sh.uv
uv venv --python 3.11 .venv
uv pip install -e ".[piper,align,dev]"
.\.venv\Scripts\Activate.ps1
studio doctor
studio voices install piper-vi-vais1000      # giọng offline dự phòng (~60 MB)
```

Video đầu tiên, đọc một bài viết bạn dán vào file text:

```powershell
studio new story_reader "ban-cung-phong" --lang vi --text-file .\bai_viet.md -f short_9x16 -f long_16x9
studio run "projects\story_reader\<ngay>_ban-cung-phong_short"
# kết quả: output\final.mp4, output\captions.srt, output\metadata.md, output\qc_report.json
```

## Workflow

| ID | Tên | Trạng thái | Hình ảnh | Chi phí |
|---|---|---|---|---|
| S1 | `story_reader` | **ready** | card bài viết + nền lặp | ~0 |
| S2 | `text_quote` | planned | chữ động trên nền | ~0 |
| M1 | `listicle_stock` | planned | stock Pexels/Pixabay | ~0 |
| M2 | `ai_slideshow` | planned | ảnh AI + Ken Burns | credits / GPU nhà |
| L1 | `ai_cinematic` | **ready** | clip Google Flow (thủ công) | credits Flow |
| L2 | `longform_explainer` | planned | mix stock + ảnh + chart | thấp |
| XL | `motion_3d` | planned | Remotion / Blender | thời gian máy |

Nên chọn workflow nào và các stage của từng workflow: [docs/WORKFLOWS.md](docs/WORKFLOWS.md).

## Lệnh chính

```text
studio doctor [--gpu]                   kiểm tra ffmpeg, libass, font, CLI AI, GPU
studio workflows                        liệt kê workflow
studio new WF NAME [-f FORMAT]... [--lang vi|en] [--text-file F | --url U | --brief-file F]
                   [--voice ID] [--set key=value]... [--dir DIR]
studio run DIR [--from STAGE] [--only STAGE]... [--force] [--overwrite] [--strict]
studio status DIR                       trạng thái từng stage
studio validate|voice|render|qc|package DIR
studio voices list|install|preview|test
studio discover reddit SUB [--period day] | studio discover threads QUERY
```

Exit code: `0` ok · `1` lỗi · `2` dữ liệu không hợp lệ · `3` **đang chờ bước thủ công** (đọc `TODO_MANUAL.md`) · `4` vượt ngân sách · `5` QC fail.

## Thư mục

```text
config/      studio.yaml (mặc định), formats.yaml, nodes.yaml, local.yaml (riêng từng máy, gitignored)
workflows/   recipe từng workflow: workflow.yaml + prompts/ + README
assets/      shared/ (font, nhạc, sfx, caption style...) + workflows/<wf>/ + library.json
voices/      registry.yaml, free/, api/, local/ (manifest + models/), clones/, samples/
projects/    <workflow>/<yyyymmdd_slug>/ — project.json, source/, clips/, images/, audio/, work/, output/, logs/
src/studio/  core/ pipeline/ providers/ renderers/ workflows/ cli.py
scripts/     create_test_fixtures.ps1, smoke_test_windows.ps1
docs/        hướng dẫn
```

## Tài liệu

- [docs/SETUP_LAPTOP.md](docs/SETUP_LAPTOP.md): cài trên máy điều khiển
- [docs/SETUP_GPU_NODE.md](docs/SETUP_GPU_NODE.md): cài trên PC RTX 3080, viết dạng checklist để Claude Code trên PC làm theo
- [docs/WORKFLOWS.md](docs/WORKFLOWS.md): chọn workflow, các stage, cách thêm workflow mới
- [docs/WORKFLOW_MANUAL.md](docs/WORKFLOW_MANUAL.md): làm bước thủ công (ChatGPT, Flow, dán kết quả AI)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): kiến trúc, `project.json`, timing, đa máy
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md): xử lý lỗi thường gặp

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest -q        # offline, các test FFmpeg tự bỏ qua nếu không có ffmpeg
.\.venv\Scripts\ruff.exe check .
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_windows.ps1   # render thật 3 project, --strict
```

## Bản quyền & an toàn

- Nội dung Reddit/Threads thuộc về tác giả. Credit tự động có trong `metadata.md`; nên biến đổi nội dung (tóm tắt, dịch, bình luận) thay vì đọc nguyên văn.
- Chỉ dùng nền, nhạc và font bạn có quyền dùng. Ghi nguồn và license vào `assets/library.json`.
- Không có tính năng xóa watermark. Video có phần do AI tạo được đánh dấu `ai_generated` trong metadata.
- Key API chỉ để trong `.env` (gitignored), không bao giờ ghi vào repo hay log.
