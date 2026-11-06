# Kho nhạc nền chung

- Hài hước: **Monkeys Spinning Monkeys — Kevin MacLeod**, bản gốc MP3 và bản WAV bốn mươi tám ki lô héc, stereo. Giấy phép CC BY bốn chấm không, cần ghi công theo `comedy/monkeys_spinning_monkeys/CREDIT.txt`.
- Kinh dị: **Horror-#2 — takaya**, đúng bản người tạo chọn. Hiện lưu **bản nghe thử chính thức** của Audiostock, thời lượng khoảng ba phút chín giây; chưa có bản gốc kèm giấy phép sản xuất. Tách tại `_previews/horror/takaya_horror_2/` và không đưa vào nhóm chọn tự động. Khi có file được cấp phép, lưu bản gốc và bằng chứng giấy phép rồi cập nhật catalog.

Danh mục, nguồn, hash và trạng thái nằm trong `library.json`; chi tiết ở `source.json` cạnh từng bài. Media giữ local, metadata có thể đưa vào Git.

Dự án dùng renderer chung có thể chọn bản sẵn sàng bằng `audio.background_music`:

```json
{
  "background_music": "asset:shared/music/comedy/monkeys_spinning_monkeys/monkeys_spinning_monkeys_kevin_macleod.wav"
}
```

Đây là bổ sung kho asset. Việc chọn nhạc và cân âm cho video cụ thể vẫn nằm trong gói nghe trước khi dựng. Không trộn nhạc hài vào truyện kinh dị hoặc tự thay nhạc của bản đã duyệt.
