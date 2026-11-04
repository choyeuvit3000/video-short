# Workflow — chọn loại video theo mục tiêu và chi phí

Mỗi workflow là một **recipe dữ liệu** đặt tại `workflows/<tên>/workflow.yaml`, gồm danh sách stage, giá trị mặc định cho `project.json`, phần ghi đè theo format và chuỗi LLM. Code của các stage nằm trong `src/studio/workflows/`.

## Bảng chọn nhanh

| Mục tiêu | Workflow | Vì sao |
|---|---|---|
| Kênh đọc truyện Reddit/Threads, ra nhiều video, chi phí ~0 | **S1 story_reader** | Card bài viết + nền lặp + giọng free, AI chỉ viết lại/dịch |
| Tin tức ngắn từ một bài báo | **N1 newspaper** | Ảnh bài báo + Ken Burns, thẻ tiêu đề / trích dẫn / con số, có ghi nguồn, chi phí ~0 |
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
- **Chuẩn hoá chữ trước khi đọc** (`speech_cleanup: true`, mặc định bật): bỏ URL, emoji, emoticon, dấu `@`/`#`, và với tiếng Việt thì đọc đúng viết tắt (`ko` → không, `dc` → được, `mn` → mọi người...). Chữ trên thẻ và phụ đề dùng cùng bản đã chuẩn hoá nên luôn khớp với lời đọc.

### Layout truyện audio (`layout: passage`)

```powershell
studio new story_reader "tieng-go-cua" --lang vi --text-file .\truyen.md --set layout=passage --set part_max_sec=170
```

- `s000_hook`: chỉ có khi script có `hook` khác tiêu đề (thường do AI viết). Chữ lớn trên nền tối, câu cuối màu đỏ.
- `s001_title`: card bài viết. Khi truyện được chia phần thì có nhãn `Phần k/N` và đọc thêm "Phần k.".
- `sNNN`: **mỗi câu là một cảnh**. Overlay là thẻ đoạn văn 1–3 câu (tối đa `passage_max_chars`, mặc định 240), câu đang đọc màu đậm, các câu còn lại màu mờ.
- `sNNN_end`: thẻ kết ghi "Còn tiếp ở phần k+1." nếu còn phần sau, còn phần cuối thì là CTA (hoặc "Hết truyện.").
- Vì chữ đã nằm trên thẻ, phụ đề chuyển sang `subtitle_mode: sidecar` (vẫn có `output/captions.srt`). Muốn burn thêm phụ đề thì đặt `passage_captions: true`.

### Chia truyện dài thành nhiều phần (`part_max_sec`)

- `part_max_sec: 0` (mặc định) là không chia. Đặt `> 0` (ví dụ `170` cho Shorts 3 phút) thì stage `scenes` ước lượng thời lượng theo số từ và tốc độ giọng, rồi chia **đều** tại ranh giới đoạn (layout passage) hoặc cảnh (layout post). Không có phần cuối quá ngắn.
- Project hiện tại là **Phần 1**. Các phần sau được tạo thành project anh em ngay cạnh: `<thư mục>_p2`, `<thư mục>_p3`... (đã có sẵn source, script và cảnh, cùng nền). Chạy từng phần bằng `studio run "<thư mục>_p2"`.
- Chạy lại thì project phần sau đã có sẽ được giữ nguyên; `--force` trên Phần 1 thì tạo lại tất cả. Project phần sau có `options.part_of`, nên `--force` trên nó chỉ dựng lại chính phần đó.
- Thời lượng là ước lượng: video thật có thể dài hơn hoặc ngắn hơn vài giây. Hãy đặt `part_max_sec` thấp hơn giới hạn nền tảng một chút.

Tìm bài:

```powershell
studio discover reddit AskReddit --period day --limit 15 --save picks.json   # cần REDDIT_CLIENT_ID/SECRET
studio discover threads "chuyện công sở"                                    # cần THREADS_ACCESS_TOKEN
```

Bạn tự duyệt bài, rồi tạo project bằng `--url`. Tool không tự render hàng loạt các bài chưa duyệt.

Với Threads, API chính thức không đọc được một bài theo URL. Vì vậy `discover threads` lưu bài tìm được vào `cache/threads/posts.json`, rồi `--url` lấy nội dung từ đó. Link Threads khác (chưa qua `discover`) thì phải dán text.

## N1 · newspaper (ready)

`article → news_script → news_media → news_scenes → validate → voice → render → qc → package`

```powershell
studio new newspaper "de-mau-dgnl" --url "https://..."                 # báo không chặn bot
studio new newspaper "de-mau-dgnl" --text-file ".\bai-bao.html"        # trang đã lưu (Ctrl+S)
studio new newspaper "de-mau-dgnl" --text-file ".\bai-bao.md"          # chữ dán tay
```

- **article**: đọc tiêu đề, sapo, nội dung, chuyên mục, ngày đăng, tác giả và ảnh kèm chú thích từ metadata của trang (Open Graph, JSON-LD `NewsArticle`) và thẻ `<article>`. Nguồn theo thứ tự:
  1. `source/article.html`, hoặc file `.html` đưa vào bằng `--text-file`;
  2. `source/source.md` (dán tay);
  3. `source.url` (một request duy nhất).

  Nhiều báo (ví dụ laodong.vn) trả về **trang kiểm tra bot** thay vì bài. Studio **không vượt** lớp này mà dừng ở manual gate và hướng dẫn: mở bài trong trình duyệt, nhấn **Ctrl+S**, chọn **Web page, HTML only**, lưu thành `source/article.html`.

  Định dạng `source.md` khi dán tay:

  ```
  # Tiêu đề bài
  url: https://...
  publisher: Lao Động
  section: Giáo dục
  published: 2021-01-27
  image: https://.../anh.jpg | Chú thích. Ảnh: Tên tác giả
  image: images/anh-cua-ban.jpg | Chú thích

  Sapo...

  Nội dung...
  ```
- **news_script**: lên lời thoại theo từng ý trước, mỗi beat có `role`: `hook`, `quote`, `fact`, `number`, `document`, `timeline`, `closing`. Nội dung quyết định thời lượng, mặc định không giới hạn thời gian/số từ/số cảnh. Giữ đủ ý, bối cảnh và điều kiện quan trọng; chỉ bỏ câu lặp và CTA thừa. Giọng đọc mặc định 1.25× (+25%), giữ cao độ với `atempo` khi dùng VieNeu, headline hiện ngay đầu video, giữ năm của tin cũ. Chế độ không dùng AI đọc hết nội dung thay vì cắt đuôi bài theo thời lượng. Kịch bản v1 với `type` vẫn đọc được. Có thể dán JSON vào `work/llm/news_script.response.json`.
- **news_media**: lấy toàn bộ ảnh có chú thích trong bài, ưu tiên bản gốc; thêm ảnh trong `images/`. Khi thiếu hình, AI điền `image_query` tiếng Anh cho từng ý: pipeline tìm tối đa 3 ảnh tự do qua API **Wikimedia Commons**, dùng cache và giữ tác giả, giấy phép, URL. Đây là ảnh **minh họa**, không thay thế chân dung nhân vật hay tài liệu của sự kiện. Không dùng thumbnail tin liên quan. Nếu API không có ảnh phù hợp, giữ ảnh nguồn hoặc dùng thẻ chữ.
- **news_scenes**: `news_planner.py` chọn layout từ vai trò câu thoại theo `assets/shared/layouts/news.yaml`:
  - `headline`: chữ đậm tối đa 2 dòng, gradient, cụm `highlight` màu nhận diện, hiện ngay khung đầu.
  - `portrait_quote`: ảnh người nói có viền sáng mảnh; tên trên nền tối, chức danh dòng phụ. Chỉ chọn chân dung khớp tên.
  - `editorial_photo`: ảnh tư liệu theo ý; ưu tiên ảnh mới khi chuyển ý.
  - `document`: giữ nguyên toàn ảnh tài liệu. Thiếu ảnh đúng nguồn thì `text_card` với `points` và nguồn; không mượn bìa kỳ thi khác.
  - `stat_card`: số lớn (`value`), đơn vị (`unit`), giải thích (`explain`); giữ tối thiểu 3 giây.
  - `timeline`: các mốc `dates` có ngày và ý nghĩa; `closing`: câu kết ngắn, nguồn, tên kênh.

  Planner đối chiếu số/ngày trong chữ trên hình với bài gốc, kiểm tra tên nhân vật và ghi lý do khi hạ về layout dự phòng. Kiểm tra này không thay thế duyệt ngữ nghĩa: vẫn cần đối chiếu số với đúng đơn vị, chức danh, thời điểm và nội dung bài.
  Sửa `kind` (`portrait|editorial|document`) và `focus: [x,y]` (0–1) trong `work/news/media.json` sau khi xem ảnh. Tài liệu cần `verified: true` sau khi xác minh đúng sự kiện/kỳ thi; chỉ nhãn "bìa" trong chú thích chưa đủ. Ảnh Commons chỉ dùng cho beat đã yêu cầu ảnh đó.
- Bố cục lấy font, màu nhấn, vùng an toàn và caption từ cấu hình chung; chữ bố cục nằm trên vùng caption. Caption `news_card`: tối đa 2 dòng theo cụm nghĩa, chữ sáng trên nền tối cục bộ. Chỉ highlight khi có timestamp theo từ từ provider hoặc faster-whisper; mốc ước lượng/SRT theo cụm hiển thị nguyên cụm. Pan/zoom nhẹ; thẻ số xuất hiện nhanh, các cảnh cắt theo lời thoại.
- **package** xuất thêm `output/scene_plan.json`: start/end thực theo giọng, lời thoại, role/layout, asset, nguồn, chữ trên hình, focus, lý do fallback.
- Thời gian giữ thẻ số, hướng dẫn và timeline tăng theo lượng chữ (`motion.reading_chars_per_sec`), tối thiểu bằng các ngưỡng trong cấu hình. Cảnh dài hơn nếu lời đọc cần thêm thời gian. Ưu tiên độ rõ của nội dung, chuyển động nhẹ và cắt theo ý; không tăng tốc vượt mức đã chọn để ép video ngắn. Sau tăng tốc, căn lại caption theo audio thực tế; nhạc nền không tăng tốc.
- Option: `target_sec` và `beats` mặc định `null`; nếu điền thì chỉ là gợi ý cho AI, không cắt nội dung để đạt số đó. Các option khác: `layout_config`, `brand`, `accent`, `images`, `extra_images` (`commons|none`), `max_extra_images` (3), `image_queries`, `rewrite`, `speech_cleanup`. Muốn chỉ dùng ảnh của bạn: `images: none` và `extra_images: none`.

  Áp dụng rule mới cho project cũ: đặt `audio.speed: 1.25`, `options.target_sec: null`, `options.beats: null` trong project.json, tạo lại kịch bản nếu bản cũ bị rút ngắn, rồi chạy từ `news_media --force`. Muốn giữ media.json đã chỉnh tay, chạy từ `news_scenes`. Profile nền tảng vẫn có cảnh báo độ dài; cảnh báo này không cắt video.
- **Bản quyền**: ảnh và bài thuộc về tòa soạn. Studio ghi nguồn trên từng cảnh và trong `metadata.md` (mục Images, Source/credit). Nên tóm tắt, bình luận thay vì đọc lại nguyên bài, và xin phép tòa soạn nếu đăng kênh kiếm tiền.

## L1 · ai_cinematic (ready)

`storyboard → media → validate → voice → render → qc → package`

- **storyboard**: viết ý tưởng vào `source/brief.md` (hoặc dùng `--brief-file`). AI CLI tạo `scene_count` cảnh, mỗi cảnh ≤ `clip_sec` giây, kèm `image_prompt` và `video_prompt`.
- **media**: manual gate. `TODO_MANUAL.md` liệt kê từng file `clips/scene_NN.mp4` còn thiếu, kèm prompt. Bạn tạo ảnh bằng ChatGPT, tạo clip bằng Flow, lưu đúng tên file, rồi `studio run` lại. Cách làm chi tiết: [WORKFLOW_MANUAL.md](WORKFLOW_MANUAL.md).
- Chưa có clip mà đã có `images/scene_NN.png` → tạm dùng ảnh tĩnh với Ken Burns (`allow_still_fallback`).
- Timing `fixed`: nếu giọng dài hơn cảnh quá 200 ms thì **fail**. Khi đó rút ngắn lời thoại hoặc tăng `duration_sec`.

## K · knowledge_explainer (ready)

`explainer → images → review → validate → voice → render → qc → package`

- **explainer**: brief lấy từ `--brief`, `source/brief.md` hoặc `source/source.md`. Chưa có brief thì dừng ở bước thủ công.
  AI CLI viết lời đọc theo chủ đề (`--topic`, xem `studio topics`). Mỗi cảnh có một template Manim, tham số JSON và nguồn của từng số liệu.
- **images**: cảnh dùng template `photo` được gắn một ảnh thật từ **Wikimedia Commons**, lấy qua API chính thức, không cần key.
  Chỉ lấy ảnh có giấy phép tự do: public domain, CC0, CC BY, CC BY-SA. Ảnh lưu ở `work/images/<scene>.jpg|png` (có cache trong `cache/images/`).
  Tác giả và giấy phép hiện ngay dưới ảnh, và được ghi vào `output/metadata.md` ở mục "Images".
  Không tìm được ảnh phù hợp, hoặc mất mạng, thì cảnh đó đổi thành thẻ tiêu đề và có cảnh báo trong log. Số cảnh ảnh đặt bằng `options.photos` (mặc định 2, đặt 0 để tắt).
- **review**: manual gate. Đọc `TODO_MANUAL.md`, kiểm tra số liệu và nguồn, sửa `project.json` nếu cần, rồi chạy `studio approve <dir>`.
- **render**: mỗi cảnh `manim` được dựng thành `work/manim/<scene>.mp4` (có cache). Hình chạy theo mốc từ của giọng đọc.
- Tốc độ giọng: `audio.speed` (mặc định của workflow là **1.25**; 1.0 là tốc độ gốc của giọng). Áp dụng cho edge, piper và mock, kể cả khi chuyển sang giọng dự phòng.
- Mặc định: `audio_driven`, 6 cảnh khoảng 8 giây (bản 16:9 dài: 14 cảnh khoảng 20 giây), caption `clean_box`.
- Kiểu video tin công nghệ (nền sao, icon phẳng, thẻ nguồn, phụ đề `news_pop`): `--topic tech_news`, xem
  [MANIM.md](MANIM.md#phong-cách-tin-công-nghệ-tech_news).
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
- Muốn một project dùng CLI khác: `studio new ... --set llm_chain=codex_cli` (hoặc `agy_cli,claude_cli`), hay sửa
  `options.llm_chain` trong `project.json`. Danh sách này chỉ đổi thứ tự, CLI phải có trong `providers.llm`.
- Thời gian chờ mỗi CLI: `llm.<tên>.timeout_sec` trong `config/studio.yaml` (agy để 600 s vì mất khoảng 3–5 phút
  cho kịch bản 6 cảnh), mặc định `llm.timeout_sec` = 300 s.
- CLI không cài hoặc lỗi thì chuyển sang CLI kế tiếp. `manual` ghi prompt ra file và dừng với exit 3.

### Tốc độ giọng cho newspaper

Mặc định `audio.speed: 1.25`: nhanh hơn 25%, phần lời đọc dài khoảng 80% bản 1.0×; video vẫn có thời gian giữ thẻ và khoảng ngắt. Đây là lựa chọn biên tập, không phải chuẩn cố định cho mọi giọng. Các mức nghe thử hữu ích: 1.0× để đối chiếu, 1.10–1.15× nếu bản tin nhiều thuật ngữ/số liệu, 1.25× cho nhịp tin nhanh. Chọn một mức cho toàn video, không tự đổi tốc độ từng cảnh.

VieNeu dùng FFmpeg `atempo=1.25`, không thay sample rate để tăng tốc; edge dùng rate `+25%` từ profile gốc và giữ pitch `+0Hz`. Không tăng tốc lần nữa ở bước mix/render.

Tham khảo kỹ thuật: [FFmpeg atempo](https://ffmpeg.org/ffmpeg-filters.html#atempo), [Microsoft SSML rate/pitch](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-synthesis-markup-voice#adjust-prosody), [Google AudioConfig speakingRate/pitch](https://docs.cloud.google.com/text-to-speech/docs/reference/rest/v1/AudioConfig). Chỉ tham khảo tài liệu, không tích hợp dịch vụ trả phí.
