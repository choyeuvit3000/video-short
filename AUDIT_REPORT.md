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
| Tốc độ đọc `audio.speed` (mặc định 1.25 cho knowledge) | **Có** | edge `rate`, piper `length_scale`, mock; đổi tốc độ thì cache TTS tạo lại *(mới)* |
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
| Threads API | **Có** (keyword search) | API không lấy được bài theo URL. `discover threads` lưu bài tìm được vào `cache/threads/posts.json`, rồi `--url <permalink>` đọc lại từ đó. URL chưa có trong cache thì báo dán text |
| LLM qua `claude -p` / `agy -p` / `codex exec` | **Có** | đã chạy thật cả 3 CLI trên laptop (TEST_REPORT §10); test tự động dùng chain offline + mock CLI |
| Dán tay `work/llm/<task>.response.json` | **Có** | demo 2 dùng đường này |

### Workflow

| Workflow | Trạng thái | Ghi chú |
|---|---|---|
| `story_reader` | **Có** | demo 1 |
| `ai_cinematic` | **Có** | demo 2 (clip mẫu thay cho Flow) |
| `knowledge_explainer` + visual `manim` | **Có** | 12 template ManimCE (thêm `photo`), 8 topic pack, bước duyệt nguồn và ảnh; demo 9:16 (TEST_REPORT §9–§11) |
| Ảnh thật từ Wikimedia Commons (bước `images`) | **Có** | API chính thức, chỉ giấy phép tự do, credit trên màn hình và trong `metadata.md`; HTTP mock trong test, chạy thật 3 video *(mới)* |
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
7. Phát hiện khi thêm Manim: video hoàn toàn không có tiếng (không lời đọc, không nhạc) làm `loudnorm` trả NaN và encode AAC thất bại. Nay bỏ qua loudnorm khi project im lặng.
8. Luồng Threads chạy được: `discover threads` lưu kết quả API vào cache, `--url` tra lại theo permalink (threads.net và threads.com đều được, bỏ qua query string). Có test trong `tests/test_sources.py`.
9. Dòng `FAILED` / `WAITING` trên console đi qua `redact()` và escape markup. `redact()` nay che được cả `Authorization: Bearer <token>` và `?access_token=`, còn câu như "THREADS_ACCESS_TOKEN not set" vẫn đọc được. Lỗi HTTP của Threads chỉ báo mã trạng thái, không kèm URL có token.
10. Chạy thật với claude, codex và agy (TEST_REPORT §10). Codex từ chối schema có object tự do (`params`): schema gửi cho codex nay đổi object đó thành chuỗi JSON, và `knowledge_explainer` giải mã lại. Lời đọc bỏ chú thích `[...]` (TTS đọc cả ngoặc). Project chọn được CLI bằng `--set llm_chain=codex_cli`.
11. Ảnh thật, căn giữa, tốc độ 1.25x (TEST_REPORT §11). Hộp nội dung Manim và lề phụ đề nay đối xứng trái/phải (lấy lề lớn hơn của `safe_zone`), khối tiêu đề + nội dung được căn giữa theo chiều dọc. Chú thích `[...]` bị xóa cả khỏi chữ trên màn hình (khoảng số như `[0, 10]` vẫn giữ). Tên tác giả lặp của Commons được gộp.

## 3. Lỗ hổng còn lại, theo mức ưu tiên

| # | Vấn đề | Mức | Đề xuất |
|---|---|---|---|
| 1 | Dịch vụ ngoài chưa có test mock đầy đủ: Reddit, URL fetch (Threads đã có), cờ của claude/agy/codex CLI, TTS trả phí | Trung bình | Thêm test mock HTTP và CLI |
| 2 | Lớp CLI ít test: `--from`, `--force`, nhánh fallback qua CLI | Trung bình | Test bằng `typer.testing.CliRunner` |
| 3 | README quick-start không nhắc extra `[worker]`; `piper-en-lessac` chưa cài; registry ghi provider class `manual` không tồn tại | Thấp | Sửa tài liệu và registry |
| 4 | 5/8 workflow mới là khung; loại job GPU là placeholder | Theo lộ trình | M4, M6, M7 |
| 5 | edge-tts thỉnh thoảng lỗi liên tục dù đã thử lại 7 lần (khoảng 25 s). Khi đó project chuyển sang piper, và `--strict` fail vì cảnh báo fallback | Thấp | Đây là hành vi đúng (không trộn giọng, không báo thành công giả). Chỉ cần chạy lại `studio run`: cảnh đã có giọng edge lấy từ cache |
| 6 | agy (Antigravity) chậm, khoảng 3–5 phút cho 6 cảnh, và 2 lần trả lời không có JSON sau khoảng 25 s khi chạy song song với CLI khác. Chạy riêng thì 3/3 lần thành công | Thấp | Chạy agy một mình; timeout đã nâng lên 600 s; lỗi nay kèm phần đầu câu trả lời để chẩn đoán |
| 7 | Worker trên PC phải có manim (extra `[gpu]` đã gồm manim) thì mới render từ xa được cảnh `manim` | Thấp | Ghi trong SETUP_GPU_NODE.md |
| 8 | Tìm ảnh Commons còn lỏng: kết quả đúng từ khóa nhưng có thể không đúng nội dung (vd. ảnh phòng trưng bày thay vì cận cảnh cọc) hoặc không đúng sự kiện | Trung bình | Bước `review` liệt kê ảnh để người duyệt; đổi `params.query` rồi `--from images --force`, hoặc đặt file riêng vào `params.file` |
