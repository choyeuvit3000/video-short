# Bản dài với minh họa theo cảnh

`studio.social_video.illustrated_full.render_revision` dựng lại phần hình ngang từ một video có lời đọc đã duyệt. Mọi ảnh được ghim hash, các điểm cắt bám mốc câu thật; phụ đề hai dòng giữ hình học ổn định và nhấn cụm ba đơn vị ở mốc nói thật. Ảnh có thể cần khung cắt đã kiểm tra để loại chi tiết sinh sai.

Người tạo chọn hướng hình cụ thể trước khi tạo cả bộ. Đây là chỉnh sửa phần hình trong lượt duyệt cuối đang mở, không phải một lần duyệt lời đọc mới. Kịch bản và fingerprint giọng phải giữ nguyên; bản dựng dùng lại nguyên luồng AAC của nguồn, đối chiếu cả hash luồng nén và PCM giải mã. Không gọi TTS và không đổi tốc độ hay mastering lần nữa.

`storyboard.v1.json` lưu lựa chọn thực tế, hash nguồn/kịch bản/gói giọng và mốc cảnh. `image_manifest.json` lưu ảnh, prompt, hash và ghi chú khung cắt. `render_budget.json` giữ lịch sử lượt dựng cho đúng yêu cầu sửa phần hình, không reset lịch sử dự án. Cache từng cảnh giúp tiếp tục sau gián đoạn.

Video chỉ thay bản cũ sau khi hash tiếng khớp và QC hình/tiếng đạt; bản trước nằm trong `_history`. Sau khi xem các frame đầu/cuối, chuyển cảnh và contact sheet, chuẩn bị lại gói `review --stage final` cho toàn bộ bộ video. Không tự ghi người tạo đã duyệt video, nghe giọng hay cho phép đăng.

Kho minh họa Cồn Mù nằm ở `assets/shared/story_illustrations/con_mu_stick_v1/library.json`. PNG giữ local; metadata và prompt có thể đưa vào Git. Hướng A do người tạo chọn là người que vẽ tay trên giấy cũ, không phải mặc định mới cho mọi truyện.

Zoom dùng `camera_motion`: từng khung lấy mẫu trực tiếp từ ảnh nguồn theo tọa độ lẻ, tâm cố định và đường cong smootherstep, thay cho vùng cắt chuyển động bị làm tròn. Phụ đề được ghép sau chuyển động nên đứng yên. Giữ biên độ bốn phẩy năm phần trăm và cùng các điểm cắt; không nội suy lại từ khung trước. `MOTION_VERSION` nằm trong khóa cache. Tham khảo hành vi vùng cắt nguyên trong [mã nguồn zoompan của FFmpeg](https://github.com/FFmpeg/FFmpeg/blob/master/libavfilter/vf_zoompan.c) và phép biến đổi trong [Pillow](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.transform).

Khi người tạo yêu cầu sửa rung sau khi đã duyệt, lưu đúng chỉ dẫn trong `technical_repair_authorization.json`, chỉ cho phép `camera_motion`, ghim bản đã duyệt và kế hoạch gốc. Bản sửa dùng đường dẫn riêng, không thay video có chữ ký duyệt trước đó, không reset hoặc thêm checkpoint thứ tư, và không tự tuyên bố bản sửa mới được người tạo duyệt. Giọng, nhạc, phụ đề, ảnh, khung cắt và mốc cảnh phải khớp; âm thanh tiếp tục đối chiếu cả AAC lẫn PCM. Kiểm tra rung bằng dấu chuẩn trong video đã mã hóa, rồi đối chiếu thêm cảnh thật và QC toàn bản.

## Bản đầy đủ kết hợp clip AI và minh họa

Khi người tạo chọn rõ hướng kết hợp sau bản thử Flow, dùng `studio.social_video.hybrid_full`.
`scripts/render_con_mu_flow_full.py` ghi yêu cầu, lựa chọn thực tế, hash kịch bản, fingerprint
giọng và bản cuối đã duyệt trước khi dựng. Lựa chọn này chỉ cho phép sửa phần hình;
không tạo lại TTS, đổi nhạc, đổi tốc độ giọng hoặc ghi thêm một sự kiện duyệt.
Đường dẫn bản mới khác bản đã duyệt, và hash toàn bộ sổ duyệt phải không đổi sau khi dựng.

Kế hoạch ghim từng clip, ảnh sửa và khoảng khung hình thay thế. Các cảnh không đổi dùng
cache minh họa đã xác thực. Khung cắt theo cảnh gốc và tổng số frame phải giữ nguyên;
ảnh đầu đã sửa có thể chuyển sang clip cùng bố cục để tránh lỗi cụt chân quay lại.
Phụ đề được ghép sau chuyển động với mốc tiếng gốc. Clip quá ngắn không được âm thầm
giữ đứng: chỉ cho phép làm chậm phần hình tối đa sáu phần trăm khi kế hoạch ghi rõ,
cộng tối đa hai frame cho làm tròn lúc đổi từ hai mươi bốn sang ba mươi fps.

Bản Cồn Mù kết hợp dùng ba clip Flow sẵn có ở cảnh một, ba và tám, còn lại là minh họa
chuyển động. Không gọi thêm model. Ghi đúng nguồn Flow là 1280 × 720, 24 fps, dù được
đưa vào khung xuất 1920 × 1080, 30 fps; không mô tả đó là clip gốc 1080p.
Trước khi giao, đối chiếu AAC và PCM với bản đã duyệt, kiểm tra toàn video và xem
các đoạn AI, mép nối ảnh/clip, phụ đề cùng các điểm lộ manh mối và kết truyện.
