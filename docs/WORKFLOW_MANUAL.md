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
- Khi `options.allow_still_fallback: true`, ảnh chưa có clip được dùng tạm với Ken Burns.
  Đây là bản xem trước từ ảnh, không phải clip AI đã tạo xong.

## 3. Clip video (Google Flow)

- Dùng ảnh keyframe làm frame đầu, kèm `video prompt` của cảnh.
- Tải clip về và lưu **đúng tên** `clips/<scene_id>.mp4`. Tool không đổi tên hay ghi đè file của bạn.
- Clip ngắn hơn cảnh → frame cuối được giữ lại. Clip dài hơn → bị cắt. Clip sai tỉ lệ → crop, hoặc pad nếu `fit_mode: pad`.
- Watermark của nền tảng (nếu có) được giữ nguyên.

Khi thử nghiệm clip AI thật, đặt trong `options`:

```json
{
  "allow_still_fallback": false,
  "require_video_clips": true,
  "strict_clip_validation": true,
  "clip_min_short_side": 720
}
```

Stage `media` dừng nếu thiếu clip, còn scene kiểu `still` từ lần fallback trước,
file hỏng/không có video, video ngắn hơn cảnh, sai tỷ lệ hoặc độ phân giải gốc quá thấp.
Thời lượng lấy từ luồng hình; track âm thanh dài hơn không che được thiếu hình.
Chế độ này không tự giữ đứng frame cuối hoặc crop clip sai tỷ lệ để cho qua.
Kiểm tra kỹ thuật không chứng minh nguồn AI hay chất lượng chuyển động:
lưu prompt, ảnh đầu, nguồn tải, model, số tín dụng và hash của clip;
xem đầu/giữa/cuối để bắt rung máy, đổi nhân vật, đạo cụ và lỗi biến dạng.
Không xóa watermark hay tự thay giọng đã duyệt bằng âm thanh từ Flow.

Trước khi tốn lượt tạo clip, kiểm tra ảnh đầu ở kích thước lớn: thân người phải nối đủ
qua hông, đầu gối, cẳng chân tới bàn chân; người đứng phải đặt chân trên sàn và có khoảng
trống dưới bàn chân. Ống quần cụt ngang trên nền không phải là tư thế đứng hợp lệ.
Nếu lỗi đã có trong ảnh đầu, sửa ảnh trước; thêm câu cấm trong prompt video không đủ.
Kiểm tra lại phần thân dưới trong suốt cử động và tại các mốc chuyển động tay mạnh nhất.
Gắn hash ảnh sửa trong `options.keyframe_overrides` để lần chuẩn bị lại không lấy nhầm ảnh lỗi.
Nếu người tạo đã chỉ ra lỗi ở clip, ghi hash clip đó trong `options.rejected_clip_sha256`
theo scene ID; gate phải chặn dùng lại file bị từ chối dù codec và thời lượng vẫn hợp lệ.
Khi Flow yêu cầu xác minh hoặc báo hoạt động bất thường, chuyển bước gửi/tạo cho người dùng.
Ảnh sửa phải được chọn làm khung hình đầu; chỉ dán lại prompt không bảo đảm tham chiếu đúng ảnh.

Thử nghiệm Cồn Mù dùng lại ảnh đã có, ba cảnh tám giây, máy quay cố định.
Theo phản hồi của người tạo, mỗi cảnh có một động tác nhân vật rõ ràng
(ngẩng đầu, thu chân, chỉ di ảnh); chỉ thêm sương/khói là chưa đạt mục tiêu.
`scripts/prepare_con_mu_flow_trial.py` tạo project và gói ảnh/prompt trong `work/flow_handoff/`.
Script không gọi model, tạo TTS, ghi nhận phê duyệt hoặc thay video cũ.
Chạy `studio preflight PROJECT` trước khi gửi prompt tạo clip.
Tạo mỗi cảnh một lần, kiểm tra trước khi thử lại; không tự mua tín dụng hoặc đổi gói.

Sau khi tải clip thật, dùng `scripts/finish_con_mu_flow_trial.py --clip scene_01=ABSOLUTE_FILE`
(lặp `--clip` cho từng cảnh). Script kiểm tra giải mã toàn bộ luồng hình, giữ độ dài gốc,
lưu hash/nguồn tải và bản nhập cũ rồi chạy lại gate `media`.
Khi đủ ba cảnh, bản ghép kiểm tra không tiếng và contact sheet nằm trong
`output/YYYY-MM-DD/flow_trials/`, giữ nguyên độ phân giải/khung hình gốc và watermark.
Xem bản ghép để đánh giá diễn xuất, biến dạng và độ rung trước khi dùng clip cho bản chính.
Đây là mẫu kiểm tra hình ảnh, không phải lần duyệt giọng hay bản thay thế video đã được chấp nhận.

## 4. Giọng tự thu

Trong `project.json` đặt `"audio": {"source": "manual"}` và mỗi cảnh `"audio_path": "audio/<tên>.wav"`. Mốc thời gian caption sẽ được ước lượng, hoặc align bằng faster-whisper nếu đã cài extra `align`.

## 5. Sửa kịch bản / cảnh

- Sửa lời thoại trực tiếp trong `project.json` → `scenes[].narration`, rồi `studio run <dir> --from voice`. Audio chỉ tạo lại cho những cảnh có lời đổi (theo cache).
- Muốn tạo lại toàn bộ cảnh từ `work/script.json`: `studio run <dir> --from scenes --force`.
- Kiểm tra trước khi render: `studio validate <dir>`.

## 6. Đăng video

Tool **không tự đăng**. Lấy `output/final.mp4`, phần mô tả, hashtag và credit trong `output/metadata.md`. Bản 16:9 có `output/captions.srt` để upload phụ đề riêng lên YouTube. Khi nền tảng hỏi, đánh dấu nội dung có AI.
