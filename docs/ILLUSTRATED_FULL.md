# Bản dài với minh họa theo cảnh

`studio.social_video.illustrated_full.render_revision` dựng lại phần hình ngang từ một video có lời đọc đã duyệt. Mọi ảnh được ghim hash, các điểm cắt bám mốc câu thật; phụ đề hai dòng giữ hình học ổn định và nhấn cụm ba đơn vị ở mốc nói thật. Ảnh có thể cần khung cắt đã kiểm tra để loại chi tiết sinh sai.

Người tạo chọn hướng hình cụ thể trước khi tạo cả bộ. Đây là chỉnh sửa phần hình trong lượt duyệt cuối đang mở, không phải một lần duyệt lời đọc mới. Kịch bản và fingerprint giọng phải giữ nguyên; bản dựng dùng lại nguyên luồng AAC của nguồn, đối chiếu cả hash luồng nén và PCM giải mã. Không gọi TTS và không đổi tốc độ hay mastering lần nữa.

`storyboard.v1.json` lưu lựa chọn thực tế, hash nguồn/kịch bản/gói giọng và mốc cảnh. `image_manifest.json` lưu ảnh, prompt, hash và ghi chú khung cắt. `render_budget.json` giữ lịch sử lượt dựng cho đúng yêu cầu sửa phần hình, không reset lịch sử dự án. Cache từng cảnh giúp tiếp tục sau gián đoạn.

Video chỉ thay bản cũ sau khi hash tiếng khớp và QC hình/tiếng đạt; bản trước nằm trong `_history`. Sau khi xem các frame đầu/cuối, chuyển cảnh và contact sheet, chuẩn bị lại gói `review --stage final` cho toàn bộ bộ video. Không tự ghi người tạo đã duyệt video, nghe giọng hay cho phép đăng.

Kho minh họa Cồn Mù nằm ở `assets/shared/story_illustrations/con_mu_stick_v1/library.json`. PNG giữ local; metadata và prompt có thể đưa vào Git. Hướng A do người tạo chọn là người que vẽ tay trên giấy cũ, không phải mặc định mới cho mọi truyện.
