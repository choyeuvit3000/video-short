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

`StudioError(code, scene_id)` → `0` ok · `1` lỗi chung / ffmpeg · `2` validation · `3` waiting_manual · `4` budget · `5` QC fail.

Mỗi lần chạy ghi một file log trong `logs/` của project, có prefix `[stage][scene_id]`.

## Đa máy (M3.5, đang thiết kế)

```text
Laptop (controller)                          PC RTX 3080 "home-gpu" (worker)
studio run ─► scheduler ──HTTP+token──► studio-worker (FastAPI, queue SQLite)
   chọn node theo capability,               ├─ ffmpeg h264_nvenc
   khung giờ, online, độ dài queue          ├─ faster-whisper CUDA large-v3
   fallback: chờ | CPU | free/API           ├─ TTS GPU (F5-TTS-VI / VieNeu / XTTS)
                                            └─ ComfyUI 127.0.0.1:8188 (SDXL/Flux, Wan/LTX)
```

- `config/nodes.yaml` mô tả từng node: `url`, `token_env`, `capabilities`, `schedule`, `policy`.
- Job khai báo yêu cầu, ví dụ `requires: {service: comfyui, min_vram_gb: 8}`. Node ngoài khung giờ thì job ở trạng thái `waiting_node` hoặc chạy theo fallback.
- File được truyền theo content hash, nên file worker đã có thì không gửi lại. Model nặng cài trực tiếp trên worker.
- Laptop gửi job xong có thể ngắt mạng; khi kết nối lại thì chạy `studio jobs pull`.
- Bảo mật:
  - chỉ đi qua Tailscale, không mở port public;
  - token dài, lưu trong `.env`;
  - worker chỉ nhận các loại job định nghĩa sẵn, không có endpoint shell;
  - ComfyUI không bao giờ được expose.

## Phân vai AI

| Công cụ | Dùng cho |
|---|---|
| Claude CLI | kịch bản VI/EN, hook, viết lại/dịch, storyboard JSON, metadata |
| agy (Gemini) | dự phòng; research ngữ cảnh dài, chọn bài; vision QC (sau này) |
| Codex | phát triển và sửa code, template Remotion/Blender; dự phòng LLM |
| ChatGPT web / Google Flow | ảnh keyframe, clip (manual gate) |
| Không cần AI | cắt ghép, Ken Burns, caption, mix, card, QC, align phụ đề, tải stock |
