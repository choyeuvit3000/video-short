---
name: threadreel
description: Dựng bài Threads kiểu merged đã duyệt và video kể chuyện Reddit bằng Studio ở ổ D, với QC và xem lại bắt buộc.
---

# Social video — Studio hợp nhất

Nơi chạy duy nhất: `D:/Video-maker/video-short`. Python: `D:/Video-maker/video-short/.venv/Scripts/python.exe`. Dữ liệu/asset cũ đã chuyển sang `projects/social_video`; không chạy bộ Threadreel trong Downloads.

## Threads

Chuẩn đầu ra là video merged người dùng duyệt: thẻ bài chụp thật, nền mờ, toàn bộ clip và tiếng nguồn, chú thích đọc bằng giọng local đã duyệt QC (ưu tiên nam trầm miền Nam), credit tác giả xuyên suốt. Không biến bài thành truyện. Không mặc định xuất A/B, không dùng giao diện/pipeline digest cũ.

```powershell
.\.venv\Scripts\python.exe -m studio threads-post "https://www.threads.com/@user/post/ID"
# Hoặc dữ liệu đã capture, không cần truy cập lại nguồn:
.\.venv\Scripts\python.exe -m studio threads-post "projects/social_video/work/threads/ID"
```

`--narration-file` nhận JSON danh sách lời đọc tương ứng các phần bài, dùng để chuẩn hóa số/viết tắt, không bịa ý. `--plan-file` nhận JSON có `source` đúng URL và `beats`, cho phép biên tập media/comment/reaction; các id meme phải thuộc thư viện. Mặc định không tự đọc bình luận hoặc tự gắn meme khi chưa đánh giá ngữ cảnh.

## Reddit kể chuyện

```powershell
.\.venv\Scripts\python.exe -m studio reddit-story list
.\.venv\Scripts\python.exe -m studio reddit-story prep --id ID
.\.venv\Scripts\python.exe -m studio reddit-story render --id ID
```

Bản dịch ở `projects/social_video/work/reddit/ID/vi.json`; giữ cấu trúc đoạn, thoại, chia phần, nền và lịch sử đăng cũ. Giọng local đã duyệt QC, ưu tiên nam trầm miền Nam; không âm thầm dùng lại cache giọng khác.

## QC mọi video trước khi giao

Lệnh dựng tự mastering hai lượt, kiểm tra 1080×1920/30fps/H.264/AAC stereo, âm lượng/peak, thời lượng, khoảng lặng, khung đen/đứng và tạo `*.sheet.jpg`, `*.qc.json`. Lỗi kỹ thuật không thay thế file tốt trước. `automatic: PASS` chưa đồng nghĩa đã duyệt nội dung.

1. Xem contact sheet và các frame đầu/cuối/chuyển cảnh; kiểm tra chữ, credit, vùng an toàn, meme đúng ngữ cảnh. Detector đứng hình có thể bắt thẻ tĩnh; kiểm tra vùng clip thật nếu có cảnh báo.
2. Kiểm tra audio bằng nghe mẫu hoặc đối chiếu ASR local với nguồn/plan kèm đo loudness/peak. Không khẳng định đã nghe nếu chỉ dùng ASR hay probe. Lời đọc phải khớp nguồn/plan, không chồng clip gốc không chủ ý.
3. Sửa, dựng và kiểm tra lại khi có lỗi. Sau khi thực sự xem/kiểm tra, ghi nhận bằng:
```powershell
.\.venv\Scripts\python.exe -m studio social-review VIDEO --reviewer Codex --note "Các kiểm tra thực tế đã thực hiện và giới hạn còn lại"
```
Review gắn SHA256: sửa video sẽ làm review cũ hết hiệu lực. Không tự đánh dấu nội dung được duyệt chỉ vì FFmpeg chạy xong. Ghi rõ cách kiểm tra audio và giới hạn; nếu chưa đủ bằng chứng về nội dung hoặc hình/tiếng, để chờ review.

Asset: `studio social-assets scan|fetch`; ảnh/video meme, sound, sfx và các clip nền ở data root. Meme chỉ chèn khi phù hợp; tránh nội dung tang sự/tai nạn/bệnh tật/tranh chấp.


## Output chung

Video cuối dùng chung root `D:/Video-maker/video-short/output`, chia thư mục `YYYY-MM-DD/MODE/` theo ngày và mode; không rải trong project. Tên file có prefix mode và ID để không ghi đè; QC/phụ đề/metadata cùng basename. Dùng đường dẫn CLI trả về để review. Các bản cũ nằm trong `_history`; intermediates ở work.


Thêm nền riêng: `studio social-assets import-background --source VIDEO --seconds 60`. Lệnh giữ file nguồn, tạo các clip silent theo keyframe, giữ manifest cũ, đăng ký shared asset bằng hardlink khi có thể. Media chỉ local; code và asset metadata được commit.


## Voice admission and generation planning

Edge (all voices/providers), Mai Anh and aliases are permanently forbidden, including random selection, fallback and cached audio. Prefer a deep male Southern Vietnamese voice; reject voices that sound like Mai Anh. New voices/checkpoints stay quarantined until intelligibility, pronunciation, naturalness, artifacts and dissimilarity are reviewed against a SHA256-bound audition. Never claim training or listening occurred without evidence.

Before expensive generation, run `studio brief PROJECT --interactive --detailed`, then `studio preflight PROJECT`; resolve the creator’s requirements and review the concrete brief before `studio brief PROJECT --approve --reviewer NAME`. Static preflight is a text storyboard, not a rendered layout. Default budget is one full render per approved brief; inspect QC before explicitly granting another attempt. Source or plan changes invalidate approval. Target duration is advisory when preserving complete source clips.


OmniVoice test support: `studio voices audition omnivoice-vi-thaison` creates/reuses a quarantined audio sample. This machine currently selects OmniVoice via `config/local.yaml` and the social config; a saved brief retains its explicitly selected voice, so update and review that brief before switching an existing project. Generic and native Threads/Reddit use the same registry provider and SHA256 admission checks. The test reference is an existing synthetic Thái Sơn clip, not Mai Anh. Model revision and reference hash are pinned; changing either invalidates voice reviews and audio caches. Do not approve listening checks automatically.


Vietnamese knowledge videos use `omnivoice-vi-knowledge-under30` by default (`knowledge_explainer` and `longform_explainer`). This follows the newer user-provided Under30 audio reference and its brisk conversational cadence, rather than forcing the older generic voice preference. Reference is copied into local voices assets; no training was run. Target is 5.4 whitespace-separated speech units/second, measured source 5.44; the test generated 5.35. The knowledge workflow uses audio.speed=1.0 because its voice profile already controls cadence. Explicit project voices override workflow defaults; English keeps its own voice. SHA-bound generated-sample listening review still applies; do not mark naturalness or similarity approved from ASR alone.
