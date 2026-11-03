# Workflow — chọn loại video theo mục tiêu và chi phí

Mỗi workflow là một **recipe dữ liệu** đặt tại `workflows/<tên>/workflow.yaml`, gồm danh sách stage, giá trị mặc định cho `project.json`, phần ghi đè theo format và chuỗi LLM. Code của các stage nằm trong `src/studio/workflows/`.

## Bảng chọn nhanh

| Mục tiêu | Workflow | Vì sao |
|---|---|---|
| Kênh đọc truyện Reddit/Threads, ra nhiều video, chi phí ~0 | **S1 story_reader** | Card bài viết + nền lặp + giọng free, AI chỉ viết lại/dịch |
| Quote, fact ngắn | S2 text_quote *(planned)* | Chữ động, không cần hình |
| Top-N, kiến thức, tin tức | M1 listicle_stock *(planned)* | Stock footage miễn phí (Pexels/Pixabay) |
| Lịch sử, bí ẩn, kể chuyện có minh họa | M2 ai_slideshow *(planned)* | Ảnh AI (ComfyUI trên PC GPU hoặc ChatGPT) + Ken Burns |
| Video "wow", nhân vật nhất quán | **L1 ai_cinematic** | Clip Google Flow, timing cố định (đúng spec gốc) |
| Kiến thức: khoa học, lịch sử, tài chính, toán... | **K knowledge_explainer** | Animation Manim chạy theo lời đọc, có bước duyệt nguồn, chi phí ~0 |
| YouTube dài 8–15 phút | L2 longform_explainer *(planned)* | Chương, B-roll, thumbnail |
| 3D, chuyển cảnh phức tạp | XL motion_3d *(planned)* | Remotion / Blender trên PC GPU |

Thứ tự ưu tiên cho mỗi bước: **tool có sẵn → CPU laptop → GPU node (trong khung giờ) → dịch vụ free → AI CLI theo gói thuê bao → API trả phí** (API trả phí chỉ chạy khi workflow cho phép và còn ngân sách).

## Stage chung

| Stage | Việc | Ghi chú |
|---|---|---|
| `validate` | kiểm tra schema, đường dẫn, file media, timing | lỗi → exit 2, báo theo `scene_id` |
| `voice` | TTS từng cảnh, lấy mốc thời gian từng từ, tạo `work/timeline.json` | có cache theo nội dung; `--overwrite` để tạo lại |
| `render` | render từng cảnh → ghép → mix audio/ducking → caption → `output/final.mp4` | file cuối ghi qua file tạm rồi đổi tên (atomic) |
| `qc` | ffprobe: thời lượng, độ phân giải, codec, caption | `--strict`: có cảnh báo cũng tính là fail (exit 5) |
| `package` | `output/metadata.md` (tiêu đề, mô tả, hashtag, credit, nhãn AI) | |

Các stage **sinh nội dung** (`source`, `script`, `scenes`, `storyboard`) sẽ **giữ kết quả cũ** khi chạy lại. Vì vậy những gì bạn tự sửa trong `project.json` không bị mất. Muốn tạo lại thì dùng `--force`.

## S1 · story_reader (ready)

`source → script → scenes → validate → voice → render → qc → package`

- **source**: lấy từ `source/source.md` (bài bạn dán), `--url` (Reddit qua API chính thức) hoặc `studio discover`. Không có nguồn thì dừng ở manual gate.
- **script**: `options.rewrite` có ba giá trị:
  - `auto`: dùng AI CLI nếu có; không có thì đọc nguyên văn.
  - `llm`: bắt buộc dùng AI.
  - `none`: đọc nguyên văn.

  Nếu ngôn ngữ nguồn khác ngôn ngữ project thì luôn cần AI để dịch.
- **scenes**:
  - `s01_hook` gồm card bài viết trên nền.
  - Các cảnh `sNN` tiếp theo, mỗi cảnh tối đa `scene_max_chars` ký tự.
  - `sNN_cta` là cảnh kêu gọi cuối video.
  - Nền: `background: auto` lấy file trong `assets/workflows/story_reader/backgrounds/`; thư mục trống thì dùng gradient.
- Timing `audio_driven`: mỗi cảnh dài bằng giọng đọc + 0.25 s.
- Format `long_16x9`:
  - caption dạng `clean_box`, card nhỏ màu tối;
  - mục tiêu 7 phút, kèm 4 bình luận hàng đầu nếu nguồn có.
- Option thường đổi khi tạo project, ví dụ `studio new ... --set rewrite=none --set target_sec=45`:
  `rewrite`, `target_sec`, `include_comments`, `card_theme` (light|dark), `card_width_ratio`, `scene_max_chars`.

Tìm bài:

```powershell
studio discover reddit AskReddit --period day --limit 15 --save picks.json   # cần REDDIT_CLIENT_ID/SECRET
studio discover threads "chuyện công sở"                                    # cần THREADS_ACCESS_TOKEN
```

Bạn tự duyệt bài, rồi tạo project bằng `--url`. Tool không tự render hàng loạt các bài chưa duyệt.

Với Threads, API chính thức không đọc được một bài theo URL. Vì vậy `discover threads` lưu bài tìm được vào `cache/threads/posts.json`, rồi `--url` lấy nội dung từ đó. Link Threads khác (chưa qua `discover`) thì phải dán text.

## L1 · ai_cinematic (ready)

`storyboard → media → validate → voice → render → qc → package`

- **storyboard**: viết ý tưởng vào `source/brief.md` (hoặc dùng `--brief-file`). AI CLI tạo `scene_count` cảnh, mỗi cảnh ≤ `clip_sec` giây, kèm `image_prompt` và `video_prompt`.
- **media**: manual gate. `TODO_MANUAL.md` liệt kê từng file `clips/scene_NN.mp4` còn thiếu, kèm prompt. Bạn tạo ảnh bằng ChatGPT, tạo clip bằng Flow, lưu đúng tên file, rồi `studio run` lại. Cách làm chi tiết: [WORKFLOW_MANUAL.md](WORKFLOW_MANUAL.md).
- Chưa có clip mà đã có `images/scene_NN.png` → tạm dùng ảnh tĩnh với Ken Burns (`allow_still_fallback`).
- Timing `fixed`: nếu giọng dài hơn cảnh quá 200 ms thì **fail**. Khi đó rút ngắn lời thoại hoặc tăng `duration_sec`.

## K · knowledge_explainer (ready)

`explainer → review → validate → voice → render → qc → package`

- **explainer**: brief lấy từ `--brief`, `source/brief.md` hoặc `source/source.md`. Chưa có brief thì dừng ở bước thủ công.
  AI CLI viết lời đọc theo chủ đề (`--topic`, xem `studio topics`). Mỗi cảnh có một template Manim, tham số JSON và nguồn của từng số liệu.
- **review**: manual gate. Đọc `TODO_MANUAL.md`, kiểm tra số liệu và nguồn, sửa `project.json` nếu cần, rồi chạy `studio approve <dir>`.
- **render**: mỗi cảnh `manim` được dựng thành `work/manim/<scene>.mp4` (có cache). Hình chạy theo mốc từ của giọng đọc.
- Mặc định: `audio_driven`, 6 cảnh khoảng 8 giây (bản 16:9 dài: 14 cảnh khoảng 20 giây), caption `clean_box`.
- Chi tiết template và cảnh tự viết: [MANIM.md](MANIM.md).

Loại visual `manim` dùng được trong mọi workflow, không riêng workflow này. Ví dụ: chèn một biểu đồ vào video `story_reader` bằng cách sửa
`visual` của cảnh trong `project.json`.

## Workflow planned

`text_quote`, `listicle_stock`, `ai_slideshow`, `longform_explainer`, `motion_3d` đã có `workflow.yaml` và README nhưng chưa có stage riêng. Bạn vẫn có thể tự điền `scenes` trong `project.json` (loại visual `clip` / `still` / `background` / `color` / `manim`), và các stage chung sẽ render bình thường.

## Thêm workflow mới

1. Tạo `workflows/<tên>/workflow.yaml` (chép từ `story_reader` rồi sửa) và `prompts/`.
2. Viết các stage riêng trong `src/studio/workflows/<tên>.py`, mỗi hàm có dạng `fn(ctx, opts) -> str`, export qua `STAGES = {...}`.
3. Đăng ký trong `get_stages()` ở `src/studio/workflows/__init__.py`.
4. Đặt `status: ready`, viết test trong `tests/test_workflows.py` với format `test_9x16` và giọng `mock-vi`.
5. Thêm asset riêng vào `assets/workflows/<tên>/`.

## Chuỗi LLM

- `llm_chain` trong recipe quy định **thứ tự** thử các CLI, ví dụ `[claude_cli, agy_cli, codex_cli, manual]`.
- `providers.llm` trong `config/local.yaml` quy định CLI nào **được phép** dùng trên từng máy.
- CLI không cài hoặc lỗi thì chuyển sang CLI kế tiếp. `manual` ghi prompt ra file và dừng với exit 3.
