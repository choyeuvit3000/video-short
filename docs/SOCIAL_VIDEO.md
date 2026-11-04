# Studio hợp nhất: Threads merged và Reddit

Nơi chạy chính: `D:\Video-maker\video-short`. Không còn cần Python/code/asset từ Downloads.

## Threads

```powershell
.\.venv\Scripts\python.exe -m studio threads-post "https://www.threads.com/@user/post/ID"
.\.venv\Scripts\python.exe -m studio threads-post "projects/social_video/work/compare_DfSLpwgiXeL" --narration-file "projects/social_video/inputs/merged_narration.json"
```

Chuẩn là video merged đã duyệt: ảnh chụp thật, nền mờ, clip/âm thanh nguồn đầy đủ, Mai Anh đọc chú thích, credit xuyên suốt. Không tự viết thành truyện hoặc mặc định xuất hai bản A/B. Media được giữ nguyên; bình luận/reaction cần plan biên tập rõ ràng, đúng id asset và URL nguồn. Có thể truyền `--plan-file` với `source` và `beats` gồm `kind/ref/narration/image_id/sound_id/caption_top/caption_bottom`. Narration file là mảng JSON các chú thích đã chuẩn hóa cách đọc, không thêm ý.

## Reddit

```powershell
.\.venv\Scripts\python.exe -m studio reddit-story list
.\.venv\Scripts\python.exe -m studio reddit-story prep --id ID
.\.venv\Scripts\python.exe -m studio reddit-story render --id ID
.\.venv\Scripts\python.exe -m studio reddit-story auto --count 1
.\.venv\Scripts\python.exe -m studio reddit-publish-plan
```

Giữ dữ liệu nguồn/bản dịch, chia phần, card đoạn văn/thoại, nền gameplay, nhạc ducking và sfx của mode cũ. `reddit-publish-plan` chỉ đọc kế hoạch, không tự đăng bài hoặc dời lịch. Mã hỗ trợ lịch cũ nằm ở `studio.social_video.schedule`. Cache audio mới dựa vào nội dung + giọng, tránh dùng lại tiếng từ engine cũ.

## QC bắt buộc

Mỗi video được mastering hai lượt về đích -14 LUFS/-1.5 dBTP, kiểm tra H.264/yuv420p/1080×1920/30fps, AAC stereo 48 kHz, thời lượng, âm lượng, true peak, silence/black/freeze và tạo contact sheet. Một số thẻ bài tĩnh/nền tối sẽ tạo cảnh báo; không tự cắt cảnh nguồn để làm detector hết báo. Kiểm tra trực quan và kiểm tra audio trong ngữ cảnh.

- `automatic: PASS`, `editorial: PENDING`, `status: REVIEW_REQUIRED`: đã qua kiểm tra máy, chưa duyệt nội dung.
- `status: FAIL`: không được thay thế bản tốt trước đó.
- `status: PASS`, `editorial: APPROVED`: đã có review với người duyệt, ghi chú và SHA256 đúng file hiện tại.

```powershell
.\.venv\Scripts\python.exe -m studio social-qc VIDEO
.\.venv\Scripts\python.exe -m studio social-review VIDEO --reviewer Codex --note "Kiểm tra cụ thể đã thực hiện và giới hạn"
```

Không tự duyệt chỉ vì encode thành công. Sau khi sửa video phải chạy QC/review lại; review cũ không áp dụng cho hash mới. File `.candidate.mp4` bị lỗi được giữ để điều tra, không thay thế file cuối.

## Dữ liệu và migration

`projects/social_video/`: assets, memes, inputs, work (gồm kho Reddit), cache và output. FFmpeg dùng chung ở `tools/ffmpeg/bin`; môi trường Python dùng chung `.venv`. Model VieNeu dùng nguyên bộ đã cài ở `D:\studio-node`.

Biên bản đối chiếu toàn bộ dữ liệu, bản mã/cấu hình cũ và installer không liên quan tới media được lưu ở `D:\Video-maker\migration-archive\threadreel-20261104`. Thư mục này ngoài Git và không phải bộ tool đang chạy. Cấu hình key không nằm trong code; engine đọc mặc định chỉ local.

Phần giữ: asset Việt Nam, nền đã cắt, capture bài/media, renderer thẻ bài và Reddit, cache giọng, mã kế hoạch lịch đăng, QC/mastering Studio. Phần bỏ khỏi giao diện chạy: digest/UI cũ, so sánh A/B mặc định, script hỗ trợ tự điền upload và môi trường Python trùng lặp.


All modes publish final videos directly into `D:/Video-maker/video-short/output` (flat, mode/project-prefixed filenames). QC, captions and metadata share the video basename. Project work folders contain intermediates only; `_history` holds previous revisions. Threads and Reddit use this same output folder.


## Thêm video nền của bạn

```powershell
.\.venv\Scripts\python.exe -m studio social-assets import-background --source "C:/path/to/minecraft.mp4" --seconds 60
```

Lệnh giữ nguyên file nguồn, chép vào kho asset bằng tên gắn SHA256 rồi chia thành các đoạn im tiếng khoảng một phút. Cắt theo keyframe, không tái mã hóa nên thời lượng có thể lệch vài giây. Chỉ index nguồn vừa nhập, không ghi mất manifest của các nền đã có; chạy lại không tạo clip trùng. Nền Minecraft được nhận diện từ tên file và tự nằm trong pool nền chung. Media giữ local theo .gitignore, không upload lên Git. Tên file ghi no-copyright không được coi là chứng cứ giấy phép.
