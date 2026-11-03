# AUDIT_REPORT — đối chiếu README với code

Ngày: 2026-11-03. Phạm vi: toàn bộ `src/studio/`, `workflows/`, `voices/`, `config/`, `scripts/`, `tests/`.

Cách làm:

- đọc code từng module và so với những gì README và `docs/` hứa;
- những điểm quan trọng thì kiểm lại bằng cách chạy thật (xem [TEST_REPORT.md](TEST_REPORT.md)).

Quy ước trạng thái:

| Ký hiệu | Nghĩa |
|---|---|
| **Có** | Đã cài đặt, có test tự động, đã chạy thật |
| **Một phần** | Có code nhưng thiếu nhánh, thiếu test hoặc chưa chạy với dịch vụ thật |
| **Khung** | Chỉ có `workflow.yaml` hoặc README đánh dấu `planned`, chưa có stage chạy được |

## 1. Bảng tính năng

### Lõi và pipeline

| Tính năng | Trạng thái | Ghi chú |
|---|---|---|
| Schema `project.json` v2 + nâng cấp từ v1 | **Có** | `core/schema.py`, có test |
| Validator (file thiếu, timing, path traversal) | **Có** | `core/validator.py`, `core/paths.resolve_inside` |
| Format 9:16 / 16:9 | **Có** | `square_1x1` có trong `formats.yaml` nhưng chưa có test |
| Stage runner, `state.json`, manual gate (exit 3) và resume | **Có** | Demo 2 chạy thật |
| Bỏ qua stage không đổi khi chạy lại | **Có** *(mới trong đợt này)* | `pipeline/fingerprint.py` cho render, qc và package |
| Cache segment theo cảnh | **Có** *(mới)* | file `.key` cạnh `seg_<id>.mp4` và `background.mp4` |
| Giữ bản render cũ | **Có** *(mới)* | `output/history/<thời điểm>/`, giữ 3 bản |
| Ghi file cuối atomic, không đụng media đầu vào | **Có** | test và demo 2 kiểm mtime của clip đầu vào |
| Exit code 0/1/2/3/4/5/6 | **Có** | exit 5 có test từ đợt này; `--from` và `--force` mới chỉ test gián tiếp |
| Cost ledger + trần ngân sách | **Có** | mặc định `max_cost_usd: 0` |

### Render và QC

| Tính năng | Trạng thái | Ghi chú |
|---|---|---|
| Clip / ảnh tĩnh Ken Burns / card / màu | **Có** | |
| Trộn nhạc, ducking | **Có** | |
| Chuẩn hóa độ to (−14 LUFS) | **Có** *(mới)* | `render.loudnorm` |
| Phụ đề ASS từng từ + SRT | **Có** | lề được đẩy vào `safe_zone` *(mới)* |
| QC kỹ thuật (codec, độ phân giải, fps, thời lượng, SRT) | **Có** | |
| QC nội dung: loudness, im lặng, khung đen, đứng hình | **Có** *(mới)* | `core/qc_analysis.py`, một lượt ffmpeg |
| QC phụ đề so với safe zone (đo bằng font thật) | **Có** *(mới)* | trước đợt này `safe_zone` khai báo nhưng không dùng |

### Giọng đọc

| Tính năng | Trạng thái | Ghi chú |
|---|---|---|
| edge-tts (VI/EN) | **Có** | cần internet; thỉnh thoảng lỗi "No audio was received" (xem TEST_REPORT §3) |
| Piper (CPU, offline) | **Có** | `piper-vi-vais1000` đã cài; `piper-en-lessac` khai báo nhưng chưa tải model |
| Fallback cả project sang giọng khác | **Có** | không trộn giọng trong một video; chạy thật trong demo 2 |
| Căn thời gian từng từ (faster-whisper / ước lượng) | **Có** | |
| TTS trả phí (ElevenLabs, OpenAI) | **Một phần** | adapter có, tắt mặc định, `voice_id` vẫn là placeholder, chưa gọi thật |
| Giọng GPU (F5-TTS-VI, VieNeu, XTTS) | **Khung** | chỉ có mục trong registry |

### Nguồn nội dung và LLM

| Tính năng | Trạng thái | Ghi chú |
|---|---|---|
| Văn bản dán / file | **Có** | |
| URL bài viết | **Một phần** | có code, chưa có test với HTML thật hoặc mock |
| Reddit OAuth, `discover` | **Một phần** | chưa có test, chưa chạy với key thật |
| Threads API | **Một phần, có lỗi** | `discover` gợi ý `studio new ... --url <url>`, nhưng `from_url` từ chối URL threads.net/threads.com (đã kiểm trong code) |
| LLM qua `claude -p` / `agy -p` / `codex exec` | **Một phần** | test dùng chain offline; cờ CLI thật chưa có test tích hợp |
| Dán tay `work/llm/<task>.response.json` | **Có** | demo 2 dùng đường này |

### Workflow

| Workflow | Trạng thái | Ghi chú |
|---|---|---|
| `story_reader` | **Có** | demo 1 |
| `ai_cinematic` | **Có** | demo 2 (clip mẫu thay cho Flow) |
| `text_quote`, `listicle_stock`, `ai_slideshow` | **Khung** | M4 |
| `longform_explainer` | **Khung** | M6 |
| `motion_3d` | **Khung** | M7 |

### Đa máy (M3.5)

| Tính năng | Trạng thái | Ghi chú |
|---|---|---|
| Worker FastAPI + hàng đợi SQLite, token | **Có** | sai token → 401 (chạy thật) |
| `run --node`, `--no-wait` (exit 6), `jobs pull` | **Có** | `smoke_worker_local.ps1` |
| Truyền file theo hash, pull không ghi đè bản cũ | **Có** | pull giờ cũng chuyển bản cũ vào `output/history/` *(mới)* |
| Loại job | **Một phần** | chỉ có `pipeline`; `tts_gpu`, `whisper_cuda`, `comfyui` là placeholder |
| Chạy trên PC GPU thật qua Tailscale | **Chưa kiểm** | mới chạy worker trên 127.0.0.1 của laptop |

### Khác

| Tính năng | Trạng thái | Ghi chú |
|---|---|---|
| `assets/library.json` | **Khung** | file có nhưng code chưa đọc; thư mục asset còn trống |
| `studio doctor` | **Có** | |

## 2. Những gì đợt củng cố đã sửa

1. Chạy lại không còn render lại mọi thứ: render, qc và package được bỏ qua khi đầu vào và đầu ra không đổi. Cảnh không đổi không encode lại.
2. QC kiểm tra nội dung chứ không chỉ container: phát hiện audio câm, quãng im lặng dài, khung đen, clip đứng hình và phụ đề tràn khỏi vùng an toàn hoặc khung hình.
3. `safe_zone` trong `formats.yaml` nay được dùng thật: lề phụ đề nằm trong vùng an toàn, và QC đo lại.
4. Render lần hai không làm mất bản trước (`output/history/`), kể cả khi kéo kết quả về từ worker.
5. Âm lượng được chuẩn hóa về −14 LUFS.
6. Fixture test nhẹ hơn: bộ test từ 152 s xuống khoảng 51 s.

## 3. Lỗ hổng còn lại, theo mức ưu tiên

| # | Vấn đề | Mức | Đề xuất |
|---|---|---|---|
| 1 | Luồng Threads gãy: `discover` in lệnh `--url` mà `from_url` không nhận | Cao | Cho `from_url` gọi Threads API khi gặp URL Threads, hoặc in lệnh đúng |
| 2 | `_guard` trong `cli.py` in `FAILED {e}` mà không qua `redact()`; nếu thông báo lỗi chứa token (ví dụ URL có query) thì token hiện ra console | Cao | Bọc bằng `redact()` như log file |
| 3 | Dịch vụ ngoài chưa có test kể cả mock: Reddit, Threads, URL fetch, cờ của claude/agy/codex CLI, TTS trả phí | Trung bình | Thêm test mock HTTP và CLI |
| 4 | Lớp CLI ít test: `--from`, `--force`, nhánh fallback qua CLI | Trung bình | Test bằng `typer.testing.CliRunner` |
| 5 | README quick-start không nhắc extra `[worker]`; `piper-en-lessac` chưa cài; registry ghi provider class `manual` không tồn tại | Thấp | Sửa tài liệu và registry |
| 6 | 5/7 workflow mới là khung; loại job GPU là placeholder | Theo lộ trình | M4, M6, M7 |
| 7 | edge-tts thỉnh thoảng lỗi liên tục dù đã thử lại 7 lần (khoảng 25 s). Khi đó project chuyển sang piper, và `--strict` fail vì cảnh báo fallback | Thấp | Đây là hành vi đúng (không trộn giọng, không báo thành công giả). Chỉ cần chạy lại `studio run`: cảnh đã có giọng edge lấy từ cache |
