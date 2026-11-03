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
pytest -q   → 108 passed in 96.99s  (ảnh thật + tốc độ + căn giữa: +12; CLI thật: 96; sửa Threads + redact: 93; đợt Manim: 88; đợt củng cố: 75)
ruff check . → All checks passed!
```

Bộ test gồm:

- `tests/test_hardening.py` (mới): fingerprint, history, QC nội dung, safe zone, parse log ffmpeg;
- `tests/test_manim.py` (mới): tham số template, mốc cue, vùng nội dung theo 3 format, topic pack, bước duyệt + approve, validator, render e2e có cache, cảnh Manim tự viết;
- test core, voices, workflow;
- test worker qua HTTP thật trên 127.0.0.1.

Test cần ffmpeg chạy được vì có `STUDIO_FFMPEG_DIR`.

## 9. knowledge_explainer + Manim, demo 9:16 thật

Project `projects\knowledge_explainer61103_bau-troi-xanh`:

- chủ đề `science`, giọng `edge-vi-hoaimy`, format `short_9x16`;
- kịch bản "Vì sao bầu trời màu xanh?" dán tay vào `work/llm/explainer.response.json`, không gọi LLM;
- 6 cảnh dùng các template `title`, `process`, `formula`, `bar_chart`, `compare`, `bullets`.

| Bước | Kết quả |
|---|---|
| `studio run` | dừng ở `review`, có `TODO_MANUAL.md` (exit 3) |
| `studio approve` rồi `studio run --strict` | exit 0. Video 1080x1920, 55,93 s. Render 71 s trên CPU, khoảng 7–12 s mỗi cảnh |
| QC | **PASS**, 0 cảnh báo. −14,1 LUFS, true peak −1,5 dB. 64 caption, không caption nào ra ngoài vùng an toàn |

Lần render đầu có 2 lỗi hiển thị, đã sửa:

- ký hiệu `∝` hiện thành ô vuông vì Arial thiếu glyph; công thức nay dùng font toán khi máy có;
- tiêu đề nhiều dòng bị căn trái; nay căn giữa.

Đã render lại và kiểm tra bằng ảnh khung hình.

Đợt này cũng tìm ra một lỗi cũ: video hoàn toàn im lặng làm `loudnorm` trả NaN. Lỗi đã sửa và có test.

## 10. knowledge_explainer với AI CLI thật trên laptop (claude, codex, agy)

Mỗi CLI viết một kịch bản 6 cảnh (chọn bằng `--set llm_chain=<cli>`), giọng `edge-vi-hoaimy`, format `short_9x16`.
CLI dùng tài khoản đã đăng nhập sẵn, không dùng API key. Không tự động hóa trình duyệt.

| CLI (phiên bản) | Chủ đề | Viết kịch bản | Video | QC `--strict` |
|---|---|---|---|---|
| claude 2.1.287 | finance: lãi kép | khoảng 40 s | 56,33 s | **PASS**, 0 cảnh báo (lần 2, xem dưới) |
| codex-cli 0.163.0 | science: bốn mùa | 109 s (sau khi sửa schema) | 38,60 s | **PASS**, 0 cảnh báo |
| agy 1.4.2 | history: Bạch Đằng 938 | 189–292 s | 45,63 s | **PASS**, 0 cảnh báo |

Cả 3 video đều 1080x1920, h264 + aac. Render Manim 67–86 s trên CPU. Đã xem ảnh khung hình của từng video.

Lỗi tìm ra và đã sửa:

- **codex** trả HTTP 400: chế độ schema nghiêm ngặt không nhận object tự do (`params`). Schema gửi cho codex nay
  đổi object đó thành chuỗi JSON, `knowledge_explainer` giải mã lại. Chạy lại thì thành công.
- **agy** 2 lần trả lời không có JSON sau khoảng 25 s, cả 2 lần đều khi chạy song song với CLI khác. Chạy riêng
  thì 3/3 lần thành công. Chưa rõ nguyên nhân. Đã nâng timeout agy lên 600 s (một lần mất 292 s, sát mức 300 s cũ).
  Lỗi nay kèm phần đầu câu trả lời và `status` của agy.
- Lời đọc của agy có chú thích trong ngoặc vuông, ví dụ `[Lưu Cằng Tháo]`, mà TTS sẽ đọc thành tiếng. Prompt nay
  cấm ngoặc vuông, và bước `explainer` tự xóa `[...]` khỏi lời đọc.

Khi duyệt kịch bản agy (bước `review`), đã sửa tay trong `project.json` trước khi `approve`:

- nguồn "Báo cáo khai quật bãi cọc Bạch Đằng (Yên Giang), 1988": bãi cọc Yên Giang gắn với trận năm 1288, không
  phải năm 938. Đã thay bằng Toàn thư.
- trích dẫn Lê Văn Hưu ghi "Đại Việt sử ký toàn thư (1272)": năm 1272 là bộ Đại Việt sử ký của Lê Văn Hưu. Đã sửa ngữ cảnh.

Như vậy bước duyệt tay là cần thiết, nhất là với chủ đề lịch sử.

Lần render đầu của video claude: edge-tts lỗi mạng sau 7 lần thử, project chuyển cả sang giọng Piper và `--strict`
dừng với exit 5 (đúng thiết kế, xem AUDIT_REPORT §3 mục 5). `studio run --strict --from voice` chạy lại thì qua
với giọng edge.

## 11. Ảnh thật, căn giữa và tốc độ đọc 1.25x (3 CLI, chạy lại)

Ba thay đổi:

- bước `images` lấy ảnh từ Wikimedia Commons qua API chính thức (MediaWiki, không cần key). Chỉ nhận giấy phép
  tự do (PD, CC0, CC BY, CC BY-SA) và hiện credit trên màn hình, kèm mục "Images" trong `metadata.md`;
- khối nội dung Manim và phụ đề căn giữa;
- `audio.speed: 1.25` cho `knowledge_explainer`.

Không tự động hóa Chrome hay ChatGPT/Flow (bất biến 5). Bước duyệt `review` do Claude làm thay người dùng: kiểm từng
sự kiện, từng ảnh, rồi `studio approve`.

| CLI | Chủ đề | Ảnh Commons | Video | QC `--strict` |
|---|---|---|---|---|
| claude | lãi kép | chân dung Franklin (Duplessis, PD); sàn NYSE (Highsmith, PD) | 50,47 s | **PASS**, 0 cảnh báo |
| codex | bốn mùa | Bondi Beach 2014 (CC BY-SA 4.0); "The Midnight Sun in McMurdo Sound" (Ponting, PD) | 35,73 s | **PASS**, 0 cảnh báo |
| agy | Bạch Đằng 938 | phòng trưng bày cọc, Bảo tàng Quảng Ninh (CC BY-SA 4.0); tranh thủy chiến Bạch Đằng (CC0) | 41,57 s | **PASS**, 0 cảnh báo |

Cả 3 video đều 1080x1920, giọng `edge-vi-hoaimy` ở +25%. Đã xem ảnh khung hình: nội dung nằm giữa theo chiều ngang,
và khối tiêu đề + nội dung nằm giữa theo chiều dọc.

Lỗi tìm ra và đã sửa:

- Commons search cần đủ mọi từ, nên truy vấn dài của codex ("Bondi Beach Sydney Australia summer beachgoers") không
  ra kết quả. Nay tự thử lại với truy vấn ngắn dần (`_relaxed`).
- Lần render đầu của video claude: edge-tts báo "No audio received", project chuyển sang piper và `--strict` dừng
  với exit 5. Đã đo: `+0%` thành công 6/8 lần, `+25%` thành công 8/8 lần, nên lỗi do dịch vụ chứ không do tốc độ.
  `studio run --strict --from voice --overwrite` chạy lại thì qua.
- agy lần đầu trả lời không có JSON. Chạy lại riêng thì thành công sau 256 s.
- agy viết chú thích `[Southern Han]`, `[Thanh Hóa]` trong chữ trên màn hình. Bước `explainer` nay xóa `[...]` có
  chữ khỏi params (khoảng số như `[0, 10]` vẫn giữ; template `formula` không đụng tới).
- Commons trả tên tác giả lặp ("Unknown author Unknown author"). Nay gộp lại thành "không rõ tác giả".

Khi duyệt kịch bản agy, đã sửa tay:

- scene_03 gắn bãi cọc khai quật ở Yên Giang với năm 938. Bãi cọc ở Quảng Yên thuộc trận năm 1288. Đã viết lại lời
  đọc, chú thích ảnh và nguồn.
- chú thích ảnh scene_05 ghi "dòng sông" nhưng ảnh là tranh vẽ trận thủy chiến. Đã đổi thành "Tranh minh họa thủy
  chiến trên sông Bạch Đằng".

Ảnh Commons đúng từ khóa nhưng chưa chắc đúng nội dung, nên bước duyệt ảnh vẫn cần thiết (AUDIT_REPORT §3 mục 8).

## Chưa kiểm được trong đợt này

- PC GPU thật qua Tailscale: worker mới chạy trên 127.0.0.1 của laptop.
- Reddit, URL fetch, TTS trả phí: cần key hoặc dịch vụ thật, chưa có mock. Threads có mock (`tests/test_sources.py`) nhưng chưa thử với token thật. Xem AUDIT_REPORT §3.
- Phát sóng hoặc upload (YouTube): chưa làm, là bước tiếp theo.
- Các bước web (ảnh ChatGPT, clip Google Flow) vẫn là bước thủ công, không tự động hóa qua Chrome.
- Render cảnh `manim` từ xa trên worker.
