# Chất lượng mặc định cho truyện kinh dị

Áp dụng cho dự án mới dùng renderer kể chuyện Reddit, kể cả truyện lấy từ Threads theo yêu cầu. Giữ tác giả/nền tảng nguồn thật. Đây là thay đổi pipeline cho video sau, không phải một đợt tạo lại video đã xuất.

## Kịch bản và thời lượng

Kể đủ ý; chín mươi giây là mục tiêu tham khảo. Truyện hoàn chỉnh dài hơn vẫn được giữ liền nếu nằm trong giới hạn từng Short đã chọn (mặc định một trăm tám mươi giây). Truyện dài được tách tại `suspense_breaks` do biên tập đánh dấu, có chừa thời gian cho câu mở đầu, câu hỏi kết và thẻ cuối. Không cắt ngang câu, không đọc số phần ở đầu, không tăng tốc sau khi duyệt giọng.

`vi.json` chứa toàn bộ lời đọc, `character_map`, `closing_question`, `suspense_breaks` và các câu mở phần. Câu hỏi cuối ngắn, gắn với tình huống/cách kể dân gian, có thể sửa hoặc bỏ bằng `closing_question: false` tại bước duyệt kịch bản. Các Short trước phần cuối lặp câu hỏi đã duyệt; bản đầy đủ chỉ đọc một lần. Không thêm sự kiện hay khẳng định tên loại ma khi nguồn chưa xác định.

Giọng truyện mặc định: Thái Sơn (`vieneu-gallery-thai-son`), tốc độ một phẩy hai lăm, áp dụng đúng một lần. Tin tức/kiến thức giữ cấu hình giọng riêng. Blacklist Edge/Mai Anh tiếp tục áp dụng trước cả chọn giọng lẫn dùng cache.

## Âm thanh

Giữ PCM từ TTS đến khâu trộn, không đi vòng qua MP3. Thêm khoảng đệm đầu trước khi đổi tempo; sau đó chỉ bù khoảng lặng còn thiếu, không xóa mẫu âm thanh. Mặc định khoảng một trăm mili giây đầu và một trăm hai mươi lăm mili giây cuối: tối thiểu hai trăm hai mươi lăm mili giây tại chỗ nối, vẫn giữ hơi thở/khoảng nghỉ tự nhiên sẵn có. Nhánh trim tổng quát dùng ngưỡng âm năm mươi đề xi ben và chừa đầu/cuối rộng hơn.

Nhạc ambient được đo âm lượng, đặt mặc định thấp hơn lời đọc hai mươi ba đề xi ben trước ducking nhẹ, có fade vào/ra. Hiệu ứng nhỏ theo đúng nội dung: stinger mở đầu, cười xa, bước chân, cửa kẽo kẹt, tiếng gió/thì thào. Mốc chèn lấy từ lời nói thật, không rải ngẫu nhiên theo tỷ lệ thời lượng. Tối đa bốn cue mỗi phần, không dùng tiếng cười khi nội dung nhạy cảm. Jump scare ngẫu nhiên mặc định tắt.

`sound_plan.json` ghim asset, mốc cue và SHA256; thay lời đọc/asset làm bản trộn cũ hết hiệu lực. Thiếu nhạc/SFX cần dùng hoặc asset chỉ có im lặng thì dừng, không âm thầm xuất dry voice. `*_mix_report.json` ghi mức trước ducking và gain; không coi số đo đó là chứng nhận đã nghe.

## Hình và phụ đề

Thẻ truyện bắt đầu tại mười bảy phần trăm chiều cao màn hình, tối đa ba dòng nội dung, bo mềm, viền mờ và bóng nhẹ. Icon tương tác chỉ để nhận diện giao diện, không có số đếm bịa. Nhãn `Kể lại từ nguồn` phân biệt lời kể biên tập với ảnh chụp bài gốc. Tô sáng theo cụm tối đa ba từ, vị trí/kích thước chữ ổn định, bám mốc ASR thật. Câu dài tự chuyển trang, không bị cắt mất chữ.

Nền random của truyện chỉ lấy từ catalog đã kiểm tra: độ phân giải gốc tối thiểu cạnh ngắn một nghìn không trăm tám mươi, ít nhất năm mươi chín phẩy chín khung hình mỗi giây. Kiểm tra bằng probe thực và hash, không chỉ tin tên file. Loại cảnh dung nham chói, đi tàu, rỗng map, kết đen. Darkening/vignette nhẹ cần được kiểm tra trên cả cảnh tối; không biến nền thành đen hoàn toàn.

Chuẩn bị lại kho local:

```powershell
.\.venv\Scripts\python.exe scripts/prepare_horror_assets.py
```

Metadata có phiên bản: [library.json](../assets/shared/horror/library.json). Kho hiện có ba đoạn dọc hai mươi giây, một nghìn không trăm tám mươi nhân một nghìn chín trăm hai mươi, sáu mươi khung hình mỗi giây. Lặp/chọn điểm đầu được ghim cùng bản duyệt. Không đưa nguồn chưa đạt kiểm tra vào nhóm horror.

Nguồn nền: [Governare, night/rain parkour](https://www.youtube.com/watch?v=d-WLU4tr4hs), metadata YouTube ghi Creative Commons Attribution và mô tả cho phép dùng làm nền Shorts/TikTok; ghi credit tác giả. SFX: [SFXmint horror game, CC0](https://sfxmint.com/sets/horror-game). Tiếng cười xa được lọc/echo từ [Mixkit Female cheerful laughter](https://mixkit.co/free-sound-effects/voices/), theo [Mixkit SFX Free License](https://mixkit.co/license/#sfxFree). Nhạc nền do module `horrormusic` tổng hợp. Media ở local; URL, giấy phép, hash và khoảng cắt nằm trong Git.

## Ba bước duyệt

Một: kịch bản, câu hỏi kết, giọng/tốc độ, thời lượng/chia phần, nền và hiệu ứng. Hai: toàn bộ tệp giọng thực, bản mix đầy đủ từng phần, mốc từ và preview bố cục; ASR lệch phải kiểm tra/sửa trước khi đi tiếp. Ba: video cuối sau QC hình/tiếng. Không dùng ASR hoặc agent review để giả lập việc người tạo đã nghe. Waiver chỉ áp dụng đúng dự án/lô được người dùng chỉ định.
