# Meme thật cho Threads vui

Người tạo đã phản hồi bản thử không giống tham chiếu: có các khung không phải meme. Mèo tự vẽ, thẻ chữ bình luận và
thẻ kết không được tiếp tục chọn làm meme. Không dựng lại video trong đợt cập nhật nguồn này.

Kho chọn riêng: `assets/shared/memes/funny_threads/library.json`. Nguồn cập nhật:
`assets/shared/memes/funny_threads/sources.json`. Media thật nằm trong `projects/social_video/memes` và chỉ lưu local.

```powershell
.venv/Scripts/python.exe -m studio social-assets refresh-funny
```

Đợt ngày bảy tháng mười một bổ sung chín bộ phản ứng: Mr. Fresh, Huh Cat, Banana Cat khóc, Happy Cat, mèo trắng cười,
The Rock nhướng mày, Monkey Puppet, El Risitas và Pop Cat. Mỗi bộ có GIF nguồn, ảnh lấy từ khung thật và video chuyển
định dạng từ GIF. Các video này không có âm thanh gốc; những gợi ý ghép sound là lựa chọn biên tập, không phải xác nhận
âm thanh gốc của clip. Không kéo một GIF nhỏ thành cảnh nền toàn màn hình rồi gọi là chất lượng cao.

Mười hai ảnh template từ API Imgflip cũng được rà nguồn. Hai mươi lăm sound được đối chiếu trang chi tiết, URL audio
riêng của sound, checksum, thời lượng và khả năng giải mã; có năm file mới so với kho trước. Đọc `og:audio` của chính
trang chi tiết, không lấy file đầu tiên trong mục gợi ý. Transcript ASR là tín hiệu kiểm tra, không phải đã nghe; các
bản thu rất ngắn có thể gây nhận dạng sai. Giữ nguyên audio và đánh dấu cần nghe thử thay vì sửa nội dung theo ASR.

Trang xem/nghe: `projects/social_video/work/funny_threads/asset_refresh_20261107/asset_review.html`.
Ảnh tổng hợp chuyển động ở cùng thư mục. Đây là catalogue asset để chọn, không phải giao diện hay các khung sẽ chèn
vào video. Mỗi mục có nguồn, tình huống dùng và phân biệt ảnh, video, sound.

Nguồn chính là [Tenor](https://tenor.com/), [Imgflip](https://api.imgflip.com/get_memes) và
[Myinstants Việt Nam](https://www.myinstants.com/en/index/vn/). URL cụ thể được lưu cho từng file. Huh Cat có nguồn
đối chiếu ở [Know Your Meme](https://knowyourmeme.com/photos/2681863-huh-cat). Tải công khai không tự tạo giấy phép
sử dụng tự do; trạng thái quyền của từng meme được giữ trong metadata, tách biệt nhạc nền đã có điều khoản rõ ràng.

Quy tắc chọn:

- Ảnh bài và ảnh bình luận là nội dung nguồn. Chúng không được tính là meme.
- Meme là ảnh/clip phản ứng có thật, nhận ra được biểu cảm và phù hợp đúng câu chốt. Có thể không chèn nếu không hợp.
- Không chèn theo lịch cố định, không thêm chữ ngẫu nhiên thành một khung mới rồi gọi là meme.
- Không tự thêm thẻ kết toàn màn hình; nếu cần câu kết, giữ hình bài/bình luận liên quan.
- Sound nói phải dùng trọn một ý ngắn; không cắt lẹm âm đầu hay phủ lên lời đọc. Sound dài phải chọn đoạn rõ ràng.
- Lưu GIF/audio gốc; bản chuyển định dạng có `derived_from`, checksum và thông tin tiếng thật. Không giả âm gốc.
- Các thẻ tự tạo cũ được giữ để truy vết, có `is_meme: false`, `funny_threads_allowed: false` và không nằm trong kho chọn.
- `memes.load(funny_threads=True)` chỉ trả asset có nguồn, checksum và kiểm tra hình phù hợp. Chưa có meme thật thì
  báo thiếu, không rơi về thẻ mèo hay hiệu ứng tự tạo mang tên một sound nổi tiếng.
- Không dùng meme để chọc vào tang sự, tai nạn, bệnh tật hoặc tranh chấp; không cười nhạo ngoại hình người thật.

Những sửa đổi này không đánh dấu video cũ được duyệt và không bỏ các mốc duyệt cho video sau.

## Bổ sung meme Việt theo yêu cầu người tạo

Kho đã thêm bốn bộ ảnh/clip phản ứng của Độ Mixi và PewPew, cùng mười tám sound từ TiếngĐộng.
Các câu của Độ Mixi gồm “Ui sợ quá”, “Ui kinh thế”, “Đúng này”, “Bạn thì kinh rồi”, “Tao lạy mày”
và “Đẹp này, mười điểm”. Có thêm PewPew, Rambo, Linda và “Khoái khoái, chảy nước miếng”.
Từng mục có tình huống dùng, nguồn tải và nhãn lời/chữ tục. Trang xem ưu tiên nhóm meme Việt này.

Video được kiểm tra qua các khung chuyển động thật. Một GIF gắn nhãn Độ Mixi nhưng chứa cảnh hồ bơi
đã bị loại sau kiểm tra hình. Clip có chữ tục được ghi đúng sắc thái gắt đùa. GIF chuyển định dạng
giữ watermark nguồn và lưu tiếng phản ứng riêng trong kho sound.

TiếngĐộng dùng URL trong chính audio player của bài. Bộ nhập từ chối trang có nhiều file audio khác nhau
hoặc URL ngoài nguồn được hỗ trợ. Kiểm tra ASR lưu transcript thô cùng hash của bản thu. Tiếng cười và
các câu quá ngắn có thể bị nhận dạng sai, nên cờ cần nghe thử phải được giữ khi chưa đủ bằng chứng.

Đợt tiếp theo thêm ảnh/clip Thầy Giáo Ba bật cười và Double2T “À lôi”, cùng sáu sound có nguồn.
“Tát Ahh” và “Tát vỡ mồm giờ” giữ tên riêng của nguồn. Tên “tát chết” vẫn chưa xác định được bản cụ thể.
