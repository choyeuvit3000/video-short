# Xử lý lỗi thường gặp

Bắt đầu bằng hai bước:

- Đọc `logs/run_*.log` trong thư mục project. Mỗi dòng có prefix `[stage][scene_id]`.
- Xem trạng thái các stage bằng `studio status <dir>`.

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| `ffmpeg not found` | Mở terminal mới sau khi cài winget, hoặc đặt `STUDIO_FFMPEG_DIR=<thư mục bin>` trong `.env` |
| Chữ tiếng Việt bị lỗi trong terminal / `UnicodeEncodeError` | `$env:PYTHONIOENCODING="utf-8"`; dùng Windows Terminal |
| `edge-tts failed ... No audio was received` | Dịch vụ miễn phí thỉnh thoảng không trả audio (ngẫu nhiên, không do nội dung). Tool đã tự thử lại 7 lần; vẫn lỗi thì cả project chuyển sang giọng `fallback` (Piper). Cài sẵn `studio voices install piper-vi-vais1000`. Muốn đọc lại bằng edge: `studio run <dir> --from voice --overwrite` |
| `model not installed - run: studio voices install ...` | Giọng local chưa tải; chạy đúng lệnh được gợi ý |
| Exit 3, có `TODO_MANUAL.md` | Không phải lỗi: đang chờ bạn làm bước thủ công, xem [WORKFLOW_MANUAL.md](WORKFLOW_MANUAL.md) |
| `needs_llm` (exit 2) | Nguồn khác ngôn ngữ nhưng `rewrite: none`. Đổi `options.rewrite` thành `auto` hoặc `llm` |
| LLM CLI lỗi / hết quota | Tự chuyển sang CLI kế tiếp; hết CLI thì manual gate. Kiểm tra `claude -p "hi"` chạy được trong terminal. Có thể bỏ CLI khỏi `providers.llm` trong `config/local.yaml` |
| `voice_too_long` (timing fixed) | Rút ngắn `narration` hoặc tăng `duration_sec` của cảnh đó |
| `stale_timeline` | Đã sửa scenes sau khi tạo giọng: chạy `studio run <dir> --from voice` |
| `unreadable_media [scene_x]` | File clip/ảnh của cảnh đó hỏng hoặc tải chưa xong; tải lại đúng tên |
| `path_traversal` / `absolute path` | Đường dẫn trong `project.json` phải tương đối theo project hoặc dạng `asset:...` |
| QC fail (exit 5) | Xem `output/qc_report.json`, gồm `errors`, `warnings` và phần đo chi tiết ở `checks`. `--strict` coi cảnh báo là lỗi, ví dụ cảnh báo về việc chuyển giọng fallback |
| QC: `audio is essentially silent` | Có lời đọc hoặc nhạc nhưng tiếng gần như câm: file audio thủ công bị trống, hoặc giọng hỏng. Nghe file trong `audio/` |
| QC: `loudness ... outside` / `true peak` | Bình thường render đã chuẩn hóa về -14 LUFS (`render.loudnorm`). Nếu bạn tắt loudnorm, hãy chỉnh âm lượng nguồn |
| QC: `continuous silence inside the narration` | Có một quãng câm dài giữa lời đọc của cảnh đó (TTS lỗi, file audio thủ công có khoảng trống) |
| QC: `black frames` / `clip frozen` | Clip của cảnh đó bị đen hoặc đứng hình (clip tải chưa xong, clip ngắn hơn cảnh). Cảnh kiểu `color` không bị kiểm tra khung đen |
| QC: `caption(s) leave the safe zone` / `run off the frame` | Có một từ quá dài so với khung phụ đề. Giảm `caption.font_size` trong `formats.yaml`, đổi `size_scale` của style, hoặc sửa narration |
| Log ghi `up to date - skipped` nhưng bạn muốn render lại | Đầu vào không đổi nên stage được bỏ qua. Ép làm lại: `studio run DIR --from render --force` |
| `output/history/` ngày càng lớn | Chỉ giữ `output.keep_history` bản (mặc định 3). Đặt 0 để ghi đè như trước |
| `budget_exceeded` (exit 4) | Giọng/API trả phí vượt `budget.max_cost_usd`; tăng trần trong `project.json` nếu chấp nhận chi phí |
| Reddit 401/403 | Kiểm tra `REDDIT_CLIENT_ID/SECRET/USER_AGENT` trong `.env`. App Reddit có thể cần được duyệt. Tạm thời dán text vào file và dùng `--text-file` |
| Link Threads | Threads không có API đọc một bài bất kỳ theo URL: copy nội dung vào file text |
| `.ps1 cannot be loaded` | `powershell -ExecutionPolicy Bypass -File .\scripts\...ps1` (chỉ áp dụng cho lần chạy đó) |
| `gradients` filter missing | FFmpeg quá cũ: cài bản Gyan full build, hoặc đặt `video.background: "color:#101828"` |
| GPU PC: `h264_nvenc` lỗi | Cập nhật driver NVIDIA; tạm bỏ `render.encoder` trong `config/local.yaml` để dùng libx264 |
| `WAITING NODE` (exit 6) | Không phải lỗi: job đã gửi lên worker và chưa xong (hoặc PC đang ngoài giờ / bạn đang dùng PC). Chạy `studio jobs pull <dir>` sau; `studio nodes status` cho biết lý do tạm dừng |
| `node_offline` | Laptop không gọi được worker: kiểm tra Tailscale đang bật ở cả hai máy, `url` của node trong `config/local.yaml`, task `studio-worker` trên PC (log ở `<data_dir>\worker.log`) |
| `node_auth` (401) | Token trong `.env` của laptop và PC khác nhau, hoặc thiếu biến `token_env` của node |
| `worker_token` khi `worker serve` | PC chưa có token trong `.env`, hoặc token ngắn hơn 24 ký tự |
| `worker_bind` | Không bind `0.0.0.0`; đặt `worker.host` là IP Tailscale của PC (`tailscale ip -4`) |
| Có file `*.remote.*` sau khi pull | Bạn đã sửa file đó trên laptop sau khi gửi job: bản trên laptop được giữ nguyên, bản của worker nằm ở `.remote`. So sánh rồi giữ bản muốn dùng |
| `tts_wrong_node` | Giọng chỉ cài trên GPU node (`location: node:...`): chạy với `--node <id>` hoặc đổi giọng |
| Job kẹt ở `queued` | PC ngoài `schedule`, người dùng đang dùng PC, hoặc GPU bận. `studio nodes status` hiện lý do; `studio jobs cancel <dir>` để hủy |
| GPU PC: faster-whisper không dùng CUDA | Thiếu cuBLAS/cuDNN 9 trên PATH, xem bước 4 của [SETUP_GPU_NODE.md](SETUP_GPU_NODE.md) |

Khi báo lỗi cho Claude/Codex, gửi kèm `logs/run_*.log`, `state.json` và lệnh đã chạy. Không gửi `.env`.
