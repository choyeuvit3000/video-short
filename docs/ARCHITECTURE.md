# Kiến trúc

## Luồng tổng quát

```text
studio new  ──► projects/<wf>/<id>/project.json   (defaults từ workflows/<wf>/workflow.yaml + formats.yaml)
studio run  ──► runner: stage[i](ctx, opts) ──► state.json (running/done/failed/waiting_manual)
                 │
                 ├─ source/script/scenes/storyboard  ── providers/source, providers/llm (CLI chain → manual)
                 ├─ validate                          ── core/validator
                 ├─ voice     ── voices registry → providers/tts (edge|piper|mock|manual|paid) → align → timeline.json
                 ├─ render    ── renderers/render: seg_<scene>.mp4 → concat → mix/ducking → ASS captions → final
                 ├─ qc        ── core/qc (ffprobe) → output/qc_report.json
                 └─ package   ── core/metadata → output/metadata.md
```

## Thư mục project

```text
project.json  state.json  cost.json  TODO_MANUAL.md
source/   source.md | source.json | brief.md          (đầu vào, không bao giờ bị ghi đè)
clips/ images/ audio/ music/                           (media người dùng)
subtitles/<scene>.srt                                  (sinh ra)
work/     llm/ script.json card.png timeline.json words.json seg_*.mp4 captions.ass ...
output/   final.mp4 captions.srt qc_report.json metadata.md
logs/     run_<time>_<cmd>.log
```

## project.json (schema v2)

Các trường chính:

- `workflow`, `language` (vi|en), `timing_mode` (`audio_driven`|`fixed`)
- `video{format, subtitle_mode, caption_style, background}`
- `audio{voice_profile, source, background_music, music_volume_db, ducking}`
- `source{url, author, community, credit_text...}`, `budget{max_cost_usd}`, `options{...}`
- `scenes[]{scene_id, narration, duration_sec, visual{type, path, ken_burns, overlay...}, image_prompt, video_prompt}`

Các loại `visual.type`:

| Loại | Nội dung |
|---|---|
| `clip` | video, được fit, trim hoặc freeze cho đủ độ dài cảnh |
| `still` | ảnh + Ken Burns |
| `background` | nền chung của project |
| `color` | màu đơn |

`overlay` là ảnh PNG đặt chồng lên cảnh (ví dụ card bài viết). Đường dẫn tính tương đối theo project, hoặc `asset:<path>` tính theo `assets/`. Đường dẫn tuyệt đối và `..` bị từ chối.

File v1 của spec gốc (`video.width`, `scenes[].video_path`...) được tự động nâng lên v2 khi load.

## Timing

- **audio_driven**: độ dài cảnh = độ dài giọng + `scene_tail_pad_sec` (0.25 s), làm tròn theo frame, tối thiểu `min_scene_sec`.
- **fixed**: dùng `duration_sec` của từng cảnh. Giọng dài hơn cảnh quá `voice_overflow_tolerance_ms` (200 ms) → lỗi `voice_too_long`.

## Giọng đọc

`voices/registry.yaml` khai báo ngôn ngữ mặc định và giọng dự phòng khi offline. Các profile nằm trong `voices/free|api|local/*.yaml`. Mỗi profile có:

- `id`, `lang`, `tier`, `provider`
- `status` (ready|disabled|planned|experimental)
- `location` (any|laptop|node:<id>)
- `params`, `cost_per_1k_chars`, `fallback`

Khi giọng đã chọn không chạy được, **cả project** chuyển sang `fallback`. Giọng không bao giờ bị trộn trong một video, và QC sẽ ghi cảnh báo về việc chuyển giọng. Giọng trả phí phải có `status: ready` và còn `budget.max_cost_usd` (kiểm tra qua cost ledger trước khi gọi).

Mốc thời gian từng từ lấy theo chuỗi `providers.align`:

1. `provider_words`: edge-tts trả về WordBoundary;
2. `faster_whisper`: align bằng faster-whisper;
3. `estimate`: chia theo số ký tự.

## Caption

Style trong `assets/shared/caption_styles/*.yaml`:

- `bold_pop`: highlight từng từ, dùng cho short;
- `clean_box`: chữ trong hộp, dùng cho long.

Kích thước, lề và số từ mỗi dòng lấy theo format. Caption ASS được in lên video bằng libass. Song song đó, studio xuất `captions.srt` gộp từ SRT của từng cảnh, thời gian tính theo mili giây nguyên.

## Lỗi và exit code

`StudioError(code, scene_id)` → `0` ok · `1` lỗi chung / ffmpeg · `2` validation · `3` waiting_manual · `4` budget · `5` QC fail · `6` waiting_node (job đang nằm ở worker, chưa xong).

Mỗi lần chạy ghi một file log trong `logs/` của project, có prefix `[stage][scene_id]`.

## Đa máy (M3.5)

```text
Laptop (controller)                               PC RTX 3080 "home-gpu" (worker)
studio run DIR --node auto|home-gpu               studio worker serve  (Task Scheduler, pythonw)
  1. stage sinh nội dung chạy local               ├─ FastAPI, chỉ bind IP Tailscale, Bearer token
     (source/script/scenes/storyboard/media)       ├─ queue.db (SQLite): queued → running → done/failed/cancelled
  2. select_node: enabled + token + online         ├─ blobs/ab/<sha256>  (file lưu theo hash, GC sau 7 ngày)
     + đang trong schedule                         └─ job "pipeline": validate, voice, render, qc, package
  3. POST /v1/blobs/missing → PUT blob thiếu          (ffmpeg h264_nvenc, faster-whisper CUDA, TTS GPU sau này)
  4. POST /v1/jobs  ───────────────────────────►
  5. chờ (poll) hoặc --no-wait → exit 6
  6. studio jobs pull ◄── kết quả: output/, audio/, subtitles/, work/, logs/, state
```

- **`config/nodes.yaml`** mô tả từng node: `url`, `token_env`, `capabilities`, `schedule` (timezone + `"mon-fri 08:30-17:30"`, cho phép qua nửa đêm), `policy`. `config/local.yaml` của từng máy patch node theo `id` (ví dụ bật `enabled`, đổi `url` thành IP Tailscale).
- **Chọn node** (`src/studio/nodes/__init__.py`): `--node auto` lấy node worker đầu tiên đang dùng được và đang trong giờ; không có thì chạy local. `--node home-gpu` gửi kể cả ngoài giờ (job nằm chờ trong queue của PC); node không dùng được thì `--fallback local` (mặc định) chạy trên laptop, `--fallback fail` báo lỗi.
- **Chỉ các stage cuối chạy trên worker** (`REMOTE_STAGES`). Stage sinh nội dung (LLM, manual gate) luôn chạy trên laptop vì cần CLI AI và người dùng.
- **Truyền file theo content hash** (`nodes/bundle.py`): laptop gửi manifest `path → sha256` của project và các asset được tham chiếu (nền, nhạc, caption style, font). Worker chỉ đòi các hash nó chưa có. Hash phía laptop được cache trong `cache/hashes.json` theo mtime + size.
- **Trên worker** (`worker/jobs.py`): dựng lại project trong `data_dir/jobs/<id>/project` + thư mục asset riêng (`paths.asset_overlay`), chạy từng stage, kiểm tra cancel giữa các stage, đưa file mới/đã đổi vào blob store, xóa workspace.
- **Pull** (`nodes/remote.py`): ghi file về project trên laptop (qua file tạm rồi rename). File bạn đã sửa trên laptop sau khi gửi job **không bị ghi đè**: bản của worker được lưu thành `<tên>.remote<đuôi>`. `state.json` được merge, message mỗi stage có prefix `[home-gpu]`. Thông tin job nằm trong `work/remote_job.json` và chỉ mục `cache/remote_jobs.json`.
- **Worker tự nhường máy**: chỉ lấy job khi trong `schedule`, người dùng đã rời chuột/bàn phím ≥ `worker.idle_minutes` và GPU không bị chương trình khác dùng ≥ `worker.busy_gpu_util` %. Job đang chạy dở khi worker bị tắt được đưa lại vào hàng đợi.
- **Giọng chỉ có trên node** (`location: node:home-gpu` trong manifest) bị từ chối khi chạy ở máy khác (`tts_wrong_node`), để không trộn giọng.
- **Bảo mật**:
  - chỉ đi qua Tailscale, không mở port public; `worker serve` từ chối bind `0.0.0.0` trừ khi bật `worker.allow_any_interface`;
  - token ≥ 24 ký tự trong `.env` (`token_env` của node), so sánh bằng `hmac.compare_digest` ở mọi endpoint, thiếu hoặc sai token → 401;
  - API chỉ nhận job `type: pipeline` với danh sách stage cố định, mọi trường lạ bị từ chối (422), đường dẫn file phải tương đối và không có `..`; không có endpoint shell, không có trang `/docs`;
  - blob được kiểm tra lại sha256 khi upload, có giới hạn dung lượng (`worker.max_upload_gb`);
  - ComfyUI chỉ ở `127.0.0.1:8188`, không bao giờ expose.

## Phân vai AI

| Công cụ | Dùng cho |
|---|---|
| Claude CLI | kịch bản VI/EN, hook, viết lại/dịch, storyboard JSON, metadata |
| agy (Gemini) | dự phòng; research ngữ cảnh dài, chọn bài; vision QC (sau này) |
| Codex | phát triển và sửa code, template Remotion/Blender; dự phòng LLM |
| ChatGPT web / Google Flow | ảnh keyframe, clip (manual gate) |
| Không cần AI | cắt ghép, Ken Burns, caption, mix, card, QC, align phụ đề, tải stock |
