# TEST_REPORT — kết quả chạy thật

Ngày: 2026-11-03, trên laptop controller.

- Máy: Windows 11, Ryzen 5 7535HS, không có GPU NVIDIA.
- Phần mềm: FFmpeg 9.0.2 full build (có libass), Python 3.11.
- Mọi kết quả dưới đây là output thật của lệnh đã chạy, không phải ước đoán.

Không dùng API trả phí, không tự động hóa trình duyệt, không đăng nhập tài khoản web nào.

## Tóm tắt theo checklist 8 mục

| # | Yêu cầu | Kết quả |
|---|---|---|
| 1 | `studio doctor` xác nhận FFmpeg, font và dependency | **PASS** |
| 2 | story_reader tạo MP4 9:16 có giọng Việt và phụ đề | **PASS** |
| 3 | ai_cinematic dừng ở bước thủ công và resume thành công | **PASS** (lần resume đầu fail vì edge-tts lỗi, chạy lại thì qua; xem §3) |
| 4 | Chạy lại cùng input không tạo lại stage không đổi | **PASS** |
| 5 | QC bắt được media thiếu, audio hỏng, phụ đề ngoài safe area | **PASS** |
| 6 | Render hai lần không mất output trước | **PASS** |
| 7 | Smoke test không cần API key trả phí | **PASS** |
| 8 | Chạy test thật và báo PASS/FAIL | **PASS**: pytest 75 passed, ruff sạch |

## 1. `studio doctor`

Lệnh: `studio doctor`, exit 0.

| Mục | Kết quả |
|---|---|
| ffmpeg / ffprobe | OK: 9.0.2 full build, có libass |
| Font | OK: `arialbd.ttf` |
| `claude`, `agy`, `codex` CLI | OK: tìm thấy cả ba |
| edge-tts, piper, faster-whisper, fastapi | OK |
| `.env` | không có (không bắt buộc) |

## 2. story_reader 9:16 — giọng Việt + phụ đề

Lệnh: `scripts/demo_videos.ps1`. Thư mục: `projects/_demo/20261103_192439/1 story_reader 9x16/`.

| Mục | Kết quả |
|---|---|
| Exit lần chạy đầu (`studio run --strict`) | 0 |
| Giọng | `edge-vi-hoaimy` (vi-VN-HoaiMyNeural) |
| Thời lượng | 27.267 s (nằm trong 15–30 s) |
| Video | 1080x1920, h264, yuv420p, 30 fps, SAR 1:1 |
| Audio | aac, 48 kHz, stereo, −14.1 LUFS |
| QC | PASS, 0 cảnh báo |
| Phụ đề | burn-in từng từ + `captions.srt`; 0 phụ đề ra ngoài safe zone (đo bằng `arialbd.ttf`) |

Ảnh xem nhanh các khung hình: `projects/_demo/20261103_192439/preview_story_reader.png`.

## 3. ai_cinematic — manual gate rồi resume

Thư mục: `projects/_demo/20261103_192439/2 ai_cinematic 9x16/`.

Storyboard lấy từ câu trả lời AI dán tay (`work/llm/storyboard.response.json`). Clip mẫu sinh bằng FFmpeg (mandelbrot, life, gradients) đứng thay cho clip Google Flow.

| Bước | Kết quả |
|---|---|
| Lần chạy 1 (chưa có clip) | exit **3** (`waiting_manual`); tạo `TODO_MANUAL.md` ghi prompt và tên file đích cho từng cảnh |
| Đặt 3 clip vào `clips/` | |
| Resume lần 1 | exit **5**: edge-tts trả "No audio was received" cho một câu sau 7 lần thử. Project chuyển nguyên bộ sang giọng `piper-vi-vais1000`, đúng thiết kế (không trộn giọng). `--strict` coi cảnh báo fallback là lỗi nên QC fail. Không có file nào bị báo thành công giả |
| Resume lần 2 (cùng lệnh) | exit **0**; giọng `edge-vi-hoaimy` |
| Segment | 3/3 cảnh dùng lại từ cache (`reused 3/3`), không encode lại |
| Bản render của lần trước | chuyển vào `output/history/20261103_192647/`, không bị ghi đè |
| Kết quả | 24.0 s, 1080x1920, −13.7 LUFS, QC PASS, 0 cảnh báo, 0 phụ đề ngoài safe zone |
| `TODO_MANUAL.md` | đã tự xóa |
| Clip đầu vào | mtime không đổi (không bị ghi đè, di chuyển hay đổi tên) |

`demo_summary.json` của lần chạy script ghi `resume_run_exit: 5`. Đó là lần resume 1; lần 2 chạy tay bằng cùng lệnh `studio run "<dir>" --strict`.

Ảnh xem nhanh: `projects/_demo/20261103_192439/preview_ai_cinematic.png`.

## 4. Chạy lại không làm lại stage không đổi

| Kiểm tra | Kết quả |
|---|---|
| Demo 1, chạy `studio run --strict` lần hai | exit 0; `state.json` ghi `skipped: true` cho `render`, `qc`, `package`; mtime của `final.mp4` không đổi |
| Test `test_rerun_skips_unchanged_stages_and_keeps_old_render` | PASS: chạy lại thì bỏ qua. Đổi caption style thì render lại nhưng không tạo lại TTS và dùng lại cả 3 segment. Xóa tay `metadata.md` thì `package` chạy lại. `--force` render lại |
| Test round-trip worker | PASS: sau `jobs pull`, chạy lại trên laptop không render lại video đã render trên worker |

## 5. QC bắt lỗi

Test `test_qc_catches_silent_audio_black_frozen_clip_and_runaway_caption` dựng project lỗi có chủ đích. `studio qc` trả **exit 5** và báo đủ:

| Lỗi cài vào | QC báo |
|---|---|
| File audio thủ công câm | `audio is essentially silent (... LUFS) although the video has narration/music` (lỗi) |
| Clip toàn đen, đứng hình | `black frames` và `clip frozen` (cảnh báo, kèm `scene_id`) |
| Một từ rất dài trong narration | `caption(s) run off the frame` (lỗi) |

Các test khác:

| Test | Nội dung |
|---|---|
| `test_caption_layout_against_safe_zone` (3 trường hợp: từ 10, 19, 25 ký tự) | lần lượt: trong safe zone, ra ngoài safe zone, ra ngoài khung hình |
| Validator (có từ trước) | thiếu clip, ảnh hoặc audio → exit 2 trước khi render; path traversal bị từ chối |
| QC kỹ thuật | sai độ phân giải, codec, thời lượng, SRT hỏng → FAIL |

## 6. Render hai lần không mất output

| Kiểm tra | Kết quả |
|---|---|
| Demo 2 | bản render trước nằm trong `output/history/20261103_192647/` |
| `test_rerun_skips_unchanged_stages_and_keeps_old_render` | sau `--force`, bản cũ có trong `output/history/` |
| `test_history_keeps_only_newest` | giữ đúng `output.keep_history` bản mới nhất |
| `test_pull_moves_the_old_final_render_to_history` | `jobs pull` chuyển bản cũ vào history trước khi ghi bản từ worker |

## 7. Smoke test không cần API key

Mọi lần chạy dưới đây đều không có `.env`.

| Lệnh | Kết quả |
|---|---|
| `scripts/smoke_test_windows.ps1` | **SMOKE PASSED**: 3 project (clip fixed 9:16, story_reader 9:16, bản 16:9), `--strict`, QC 0 cảnh báo, −13.4 / −14.0 LUFS, phụ đề trong safe zone. Thư mục có dấu cách và tiếng Việt: `F:\Temp\studio smoke\thử nghiệm 20261103_191921` |
| `scripts/smoke_worker_local.ps1` | **WORKER SMOKE PASSED**: sai token → 401; `run --node` → exit 0, QC PASS, log kéo về; `--no-wait` → exit 6; `jobs pull` → exit 0 |

Demo dùng edge-tts, dịch vụ miễn phí cần internet. Muốn offline hoàn toàn: `demo_videos.ps1 -Voice piper-vi-vais1000`.

## 8. Test tự động

```text
pytest -q   → 75 passed in 50.86s
ruff check . → All checks passed!
```

Bộ test gồm:

- `tests/test_hardening.py` (mới): fingerprint, history, QC nội dung, safe zone, parse log ffmpeg;
- test core, voices, workflow;
- test worker qua HTTP thật trên 127.0.0.1.

Test cần ffmpeg chạy được vì có `STUDIO_FFMPEG_DIR`.

## Chưa kiểm được trong đợt này

- PC GPU thật qua Tailscale: worker mới chạy trên 127.0.0.1 của laptop.
- Reddit, Threads, URL fetch, TTS trả phí: cần key hoặc dịch vụ thật, chưa có mock. Xem AUDIT_REPORT §3.
- Phát sóng hoặc upload (YouTube): chưa làm, là bước tiếp theo.
