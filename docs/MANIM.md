# Manim: animation kiến thức trong video

Workflow `knowledge_explainer` và loại visual `manim` dùng [ManimCE](https://github.com/ManimCommunity/manim)
(bản cộng đồng, giấy phép MIT) để vẽ biểu đồ, dòng thời gian, công thức... chạy khớp với lời đọc.
Mọi thứ chạy local trên CPU, chi phí 0.

```powershell
uv pip install -e ".[manim]"     # cài một lần (PC GPU: extra [gpu] đã gồm manim)
studio doctor                    # dòng "manim" phải OK; "LaTeX" là tùy chọn
studio topics                    # các chủ đề kiến thức
```

Không cần LaTeX: công thức viết bằng chữ Unicode (`A = P·(1 + r)ⁿ`, `I ∝ 1 / λ⁴`). Nếu máy có LaTeX
(MiKTeX) và scene có `tex`, template `formula` dùng `MathTex` thay cho chữ.

## Cách hoạt động

1. Stage `explainer`: AI CLI (claude → agy → codex → dán tay) viết lời đọc. Với mỗi cảnh, AI chọn một
   **template** và điền **tham số JSON**, kèm danh sách nguồn cho từng số liệu. AI không viết code.
2. Tham số được kiểm bằng schema (pydantic, không nhận trường lạ). Cảnh nào sai tham số thì đổi thành thẻ
   tiêu đề và có cảnh báo trong log.
3. Stage `review`: **bước duyệt thủ công** (exit 3). `TODO_MANUAL.md` liệt kê từng cảnh, nguồn và checklist.
   Bạn sửa `project.json` nếu cần rồi chạy `studio approve <dir>`. Khi kịch bản được viết lại, phải duyệt lại.
4. Stage `voice` đọc lời và lấy mốc thời gian từng từ. Stage `render` gọi
   `python -m manim render` cho từng cảnh, dùng argument list và không bao giờ `shell=True`.
   Nó truyền thông tin qua file `work/manim/<scene>.spec.json`: kích thước, thời lượng, bảng màu, vùng nội dung an toàn và mốc từ.
5. Video của cảnh nằm ở `work/manim/<scene>.mp4` và được cache theo tham số, template, bảng màu, font và phiên bản manim.
   Lần chạy sau chỉ dựng lại cảnh nào thay đổi.

Animation tự nằm **trong vùng an toàn của nền tảng và phía trên 2 dòng phụ đề**. Bố cục tự đổi giữa 9:16 và 16:9.

## Template

| Template | Dùng cho | Tham số chính |
|---|---|---|
| `title` | mở đầu, hook, mở chương | `title`, `kicker?`, `subtitle?` |
| `bullets` | tối đa 6 ý hiện lần lượt | `title?`, `items[{text, cue?}]` |
| `counter` | con số đếm lên (thống kê, tiền, khoảng cách) | `end`, `label`, `start?`, `decimals?`, `prefix?`, `suffix?`, `note?` |
| `bar_chart` | so sánh giá trị (≥ 0) | `title?`, `bars[{label, value}]`, `unit?`, `highlight?` |
| `line_chart` | số liệu theo thời gian, tối đa 3 đường | `title?`, `x_labels[]`, `series[{name, values[]}]`, `unit?` |
| `function_graph` | đồ thị công thức có sẵn: lãi kép, tăng trưởng, sóng, phân phối chuẩn | `curves[{kind, a, b, label}]`, `x_range?`, `x_label?`, `y_label?` |
| `timeline` | sự kiện theo năm (lịch sử, câu chuyện phát minh) | `title?`, `events[{year, label, cue?}]` |
| `compare` | hai cột A vs B | `left{title, points[]}`, `right{…}`, `title?`, `verdict?` |
| `formula` | công thức + chú giải ký hiệu | `text` (Unicode), `tex?`, `legend?[{symbol, meaning}]` |
| `process` | các bước nối bằng mũi tên, vòng lặp (`loop: true`) | `title?`, `steps[{text, cue?}]`, `loop?` |
| `quote` | trích dẫn thật, có tác giả | `text`, `author`, `context?` |
| `photo` | ảnh thật (địa điểm, hiện vật, nhân vật, hiện tượng) từ Wikimedia Commons, có ghi công | `query` (tiếng Anh, có tên riêng), `caption?`; `file` và `credit` do stage `images` điền |

Ví dụ đầy đủ của từng template: `EXAMPLES` trong `src/studio/renderers/manim_render.py`. AI cũng nhận đúng
danh sách này trong prompt.

**`cue`**: một từ trong lời đọc. Ý, bước hoặc sự kiện đó hiện ra đúng lúc giọng đọc tới từ này. Thời điểm lấy từ mốc từ của TTS hoặc
faster-whisper. Không tìm thấy từ thì các ý chia đều theo thời lượng giọng.

Sửa tay một cảnh trong `project.json`:

```json
{"scene_id": "scene_03", "narration": "...",
 "visual": {"type": "manim", "template": "counter",
            "params": {"label": "Khoảng cách tới Mặt Trời", "end": 149.6, "decimals": 1, "suffix": " triệu km"}}}
```

Rồi chạy `studio run <dir>`. Chỉ cảnh đó được dựng lại.

## Ảnh thật (`photo`)

- Stage `images` tìm ảnh trên Wikimedia Commons bằng `query`. Kết quả được chấm điểm theo số từ trùng với tên file và mô tả (bỏ dấu tiếng Việt),
  ảnh phải rộng ít nhất 800 px (SVG thì không giới hạn) và có giấy phép tự do.
- Tìm kiếm của Commons khá lỏng: ví dụ "Earth axial tilt seasons" có thể trả về ảnh về tuế sai trục Trái Đất (axial precession) chứ không phải ảnh bốn mùa. Vì vậy `TODO_MANUAL.md` của bước duyệt liệt kê từng ảnh kèm link trang gốc, và có checklist "ảnh đúng với lời đọc".
- Ảnh sai thì có 2 cách:
  - sửa `params.query` rồi chạy `studio run <dir> --from images --force`;
  - tự đặt file của bạn vào thư mục project rồi ghi `params.file` (cùng `params.credit` nếu ảnh cần ghi công).
- Với ảnh CC BY / CC BY-SA, phải giữ dòng ghi công khi đăng video. Mục "Images" trong `metadata.md` có đủ thông tin để dán vào mô tả.
- Bố cục: ảnh nằm giữa vùng nội dung, có khung màu, chú thích ở dưới, rồi tới dòng ghi công. Ảnh phóng chậm (push-in) cho tới hết cảnh.

## Căn giữa

- Vùng nội dung và phụ đề dùng **cùng một lề cho hai bên**, lấy theo bên lớn hơn của safe zone, nên luôn nằm giữa màn hình.
- Tiêu đề và nội dung của mỗi cảnh được căn giữa theo chiều dọc như một khối. Nội dung ngắn sẽ nằm ngay dưới tiêu đề, không bị kéo dãn ra hết vùng.
  Biểu đồ cột, dòng thời gian và bảng so sánh cũng được căn giữa.

## Chủ đề (topic packs)

`workflows/_shared/topics/<id>.yaml` có: giọng văn, hướng dẫn cho AI, các template phù hợp, bảng màu,
điều cấm, hashtag, câu miễn trừ trách nhiệm, và có bắt buộc nguồn hay không. Có sẵn các chủ đề `science`, `history`, `finance`,
`math`, `technology`, `geography`, `psychology`, `health`.

- `finance` và `health`: câu miễn trừ trách nhiệm được thêm vào mô tả và hiện ở cảnh đầu.
  Câu cho finance: "Nội dung chỉ nhằm mục đích giáo dục, không phải lời khuyên đầu tư."
- `psychology`: câu miễn trừ chỉ có trong mô tả.
- Mọi chủ đề đều bắt buộc bước duyệt. Muốn bỏ duyệt thì dùng `--set review=false`; chỉ nên làm vậy khi bạn đã tự viết kịch bản.
- Nguồn (`options.sources`) được ghi vào `output/metadata.md` ở mục "Sources".

Thêm một chủ đề: chép một file YAML, đổi `id` cho trùng với tên file, rồi chạy `studio topics` để kiểm tra.
Tùy chọn của project có thể ghi đè chủ đề:

- `options.palette`: bảng màu `bg`, `text`, `muted`, `accents`;
- `options.manim_font`;
- `options.on_screen_note`.

## Cảnh Manim tự viết

Khi cần một animation mà template không có, bạn tự viết file Manim:

```json
"visual": {"type": "manim", "file": "manim/orbit.py", "scene_class": "Orbit"}
```

- File nằm **trong thư mục project** (`validate` từ chối đường dẫn tuyệt đối hoặc `..`). Mỗi lần validate có
  cảnh báo `custom_code`, vì code này chạy trên máy bạn.
- Đọc `os.environ["STUDIO_MANIM_SPEC"]` (JSON) để lấy `width`, `height`, `duration`, `voice`, `box`
  (vùng nội dung theo px) và `palette`. Animation nên dài bằng `duration`. Thiếu thì renderer giữ khung cuối.
- **Chỉ dùng code do bạn viết hoặc đã đọc kỹ.** Studio không bao giờ chạy code do AI sinh ra một cách tự động.

## Bản quyền và nguồn tham khảo

- **ManimCE** (`ManimCommunity/manim`): MIT, là engine đang dùng.
- **ManimGL** (`3b1b/manim`): bản 3Blue1Brown dùng, API khác ManimCE nên không dùng ở đây.
- **`3b1b/videos`**: code video của 3Blue1Brown, giấy phép **CC BY-NC-SA**. Repo này chỉ học ý tưởng
  (nhịp hiện dần, chú giải bên cạnh công thức), **không chép code**. Nội dung 3b1b không được đưa vào video
  của bạn, nhất là video kiếm tiền (NC = phi thương mại).
- **`mexicat/pdoom-video`**: dùng three.js. Ý tưởng lấy từ đó là:
  - nội dung hiện theo mốc từ của lời đọc (`cue`);
  - khung hình tất định (cùng input cho ra cùng video, nên cache được);
  - "style bible" cho bảng màu và giọng văn theo chủ đề.

  Phần renderer three.js/3D để dành cho M7 `motion_3d`.

## Giới hạn hiện tại

- Mỗi cảnh render bằng CPU (Cairo), khoảng 10 giây cho mỗi cảnh 9:16 1080p trên laptop.
  Muốn render trên PC GPU thì worker phải cài extra `[gpu]`, vì extra này đã gồm manim.
- Font mặc định là Arial. Công thức tự dùng Cambria Math hoặc Segoe UI Symbol khi máy có, vì Arial thiếu ký hiệu
  như `∝`. Chỉ số dưới (CO₂) được đổi thành chữ thường (CO2), vì đa số font giao diện không có glyph này.
- Codex CLI với schema nghiêm ngặt có thể trả `params` dưới dạng chuỗi JSON. Trường hợp này đã được xử lý nhưng chưa thử với codex thật.
