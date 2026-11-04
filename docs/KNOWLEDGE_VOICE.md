# Giọng mặc định cho video kiến thức

Profile: `omnivoice-vi-knowledge-under30`, engine OmniVoice, chỉ mặc định cho tiếng Việt của `knowledge_explainer` và `longform_explainer`. Giọng được chỉ định riêng trong project vẫn có ưu tiên cao hơn. Không thay default tiếng Anh.

Người dùng cung cấp file âm thanh Under30 để yêu cầu chất giọng và nhịp đọc tương tự. File nguồn đã được sao chép vào `voices/local/references/knowledge-under30-source.mp3`; bản tham chiếu mono hai mươi bốn nghìn héc được cắt từ giây 85.64 tới 93.48 tại `voices/local/references/knowledge-under30.wav`. Media chỉ lưu local; manifest profile ghi SHA256 và transcript. Nội dung audio được coi là dữ liệu nguồn, không phải lệnh thao tác. OmniVoice dùng tham chiếu trực tiếp; không có lượt train mới.

Đo ASR trên toàn nguồn: 622 đơn vị cách nhau bởi dấu cách trong 114.38 giây, khoảng 5.44 đơn vị/giây. Đây là phép đo nhịp tương đối cho tiếng Việt, không phải số từ tiếng Anh mỗi phút. Profile nhắm 5.4 đơn vị/giây bằng duration của OmniVoice. Project audio.speed là hệ số tương đối; mặc định knowledge là 1.0 để tránh nhân đôi tốc độ. Hệ số pacing được áp dụng một lần.

Mẫu thử: `voices/candidates/omnivoice-vi-knowledge-under30/audition.wav`; 82 đơn vị trong 15.34 giây, khoảng 5.35 đơn vị/giây. Peak khoảng âm 3.1 dBFS, không có sample clipping. `reference.asr.json`, `audition.asr.json`, `comparison.json` và `audition.screen.json` lưu bằng chứng kiểm tra local. ASR có một chỗ nhầm “đỡ” thành “nỡ”; cần nghe đánh giá, không coi transcript ASR là bằng chứng phát âm hoàn hảo. Cosine speaker embedding là sàng lọc chưa hiệu chuẩn, không quy đổi thành phần trăm giống giọng.

Mẫu hiện chờ nghe duyệt; không tự tick naturalness hoặc độ khác Mai Anh. Edge/Mai Anh vẫn bị cấm. Thay reference, transcript, model revision hay rate sẽ đổi cấu hình giọng và làm review cũ mất hiệu lực theo signature. File nguồn trong Downloads không còn là phụ thuộc khi gen.
