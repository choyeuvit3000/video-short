# Làm các bước thủ công (manual gate)

Một số việc tool **cố ý không tự động hóa**: tạo ảnh trên web ChatGPT, tạo clip trên Google Flow, hoặc dán kết quả AI khi không có CLI. Đến những bước này, pipeline sẽ:

1. ghi hướng dẫn vào `TODO_MANUAL.md` trong thư mục project,
2. đánh dấu stage là `waiting_manual` trong `state.json`,
3. dừng với **exit code 3** (không phải lỗi).

Làm xong các mục trong `TODO_MANUAL.md` thì chạy lại `studio run "<thư mục project>"`. Pipeline chạy tiếp từ chỗ đã dừng, và `TODO_MANUAL.md` tự xóa khi chạy hết.

## 1. Dán kết quả AI bằng tay (không có CLI / hết quota)

Thư mục `work/llm/` có ba file:

| File | Nội dung |
|---|---|
| `<task>.prompt.md` | prompt đầy đủ |
| `<task>.schema.json` | cấu trúc JSON cần trả về |
| `<task>.response.json` | **bạn tạo file này** |

1. Mở `work/llm/script.prompt.md` (hoặc `storyboard.prompt.md`), dán vào Claude / ChatGPT / Gemini trên web.
2. Yêu cầu AI trả về **chỉ JSON** đúng schema.
3. Lưu câu trả lời thành `work/llm/<task>.response.json` (UTF-8).
4. `studio run` lại.

Khi đã có file `response.json`, tool **luôn dùng file đó** và không gọi CLI nữa. Muốn AI viết lại: xóa file này rồi chạy `studio run <dir> --from script --force`.

## 2. Ảnh keyframe (ChatGPT web)

`TODO_MANUAL.md` của stage `media` liệt kê từng cảnh kèm `image prompt` và tên file đích.

- Tạo ảnh theo đúng tỉ lệ format: 9:16 cho short, 16:9 cho long.
- Lưu thành `images/<scene_id>.png` (hoặc `.jpg` / `.webp`).
- Khi chỉ có ảnh mà chưa có clip, ảnh được dùng tạm với hiệu ứng Ken Burns, nên đã render được bản xem trước.

## 3. Clip video (Google Flow)

- Dùng ảnh keyframe làm frame đầu, kèm `video prompt` của cảnh.
- Tải clip về và lưu **đúng tên** `clips/<scene_id>.mp4`. Tool không đổi tên hay ghi đè file của bạn.
- Clip ngắn hơn cảnh → frame cuối được giữ lại. Clip dài hơn → bị cắt. Clip sai tỉ lệ → crop, hoặc pad nếu `fit_mode: pad`.
- Watermark của nền tảng (nếu có) được giữ nguyên.

## 4. Giọng tự thu

Trong `project.json` đặt `"audio": {"source": "manual"}` và mỗi cảnh `"audio_path": "audio/<tên>.wav"`. Mốc thời gian caption sẽ được ước lượng, hoặc align bằng faster-whisper nếu đã cài extra `align`.

## 5. Sửa kịch bản / cảnh

- Sửa lời thoại trực tiếp trong `project.json` → `scenes[].narration`, rồi `studio run <dir> --from voice`. Audio chỉ tạo lại cho những cảnh có lời đổi (theo cache).
- Muốn tạo lại toàn bộ cảnh từ `work/script.json`: `studio run <dir> --from scenes --force`.
- Kiểm tra trước khi render: `studio validate <dir>`.

## 6. Đăng video

Tool **không tự đăng**. Lấy `output/final.mp4`, phần mô tả, hashtag và credit trong `output/metadata.md`. Bản 16:9 có `output/captions.srt` để upload phụ đề riêng lên YouTube. Khi nền tảng hỏi, đánh dấu nội dung có AI.
