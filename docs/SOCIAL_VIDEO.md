# Studio hợp nhất: Threads merged và Reddit

Nơi chạy chính: `D:\Video-maker\video-short`. Không còn cần Python/code/asset từ Downloads.

## Threads

```powershell
.\.venv\Scripts\python.exe -m studio threads-post "https://www.threads.com/@user/post/ID"
.\.venv\Scripts\python.exe -m studio threads-post "projects/social_video/work/compare_DfSLpwgiXeL" --narration-file "projects/social_video/inputs/merged_narration.json"
```

Chuẩn là video merged đã duyệt: ảnh chụp thật, nền mờ, clip/âm thanh nguồn đầy đủ, giọng local đã duyệt QC đọc chú thích, credit xuyên suốt. Không tự viết thành truyện hoặc mặc định xuất hai bản A/B. Media được giữ nguyên; bình luận/reaction cần plan biên tập rõ ràng, đúng id asset và URL nguồn. Có thể truyền `--plan-file` với `source` và `beats` gồm `kind/ref/narration/image_id/sound_id/caption_top/caption_bottom`. Narration file là mảng JSON các chú thích đã chuẩn hóa cách đọc, không thêm ý.

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


All modes share `D:/Video-maker/video-short/output/YYYY-MM-DD/MODE/`. Date uses Asia/Bangkok and stays fixed for resume/QC. QC, captions and metadata sit beside the video with the same basename; `_history` holds older revisions. Project work folders contain intermediates only.


## Thêm video nền của bạn

```powershell
.\.venv\Scripts\python.exe -m studio social-assets import-background --source "C:/path/to/minecraft.mp4" --seconds 60
```

Lệnh giữ nguyên file nguồn, chép vào kho asset bằng tên gắn SHA256 rồi chia thành các đoạn im tiếng khoảng một phút. Cắt theo keyframe, không tái mã hóa nên thời lượng có thể lệch vài giây. Chỉ index nguồn vừa nhập, không ghi mất manifest của các nền đã có; chạy lại không tạo clip trùng. Nền Minecraft được nhận diện từ tên file và tự nằm trong pool nền chung. Media giữ local theo .gitignore, không upload lên Git. Tên file ghi no-copyright không được coi là chứng cứ giấy phép.


## Voice admission and generation planning

Edge (all voices/providers), Mai Anh and aliases are permanently forbidden, including random selection, fallback and cached audio. Prefer a deep male Southern Vietnamese voice; reject voices that sound like Mai Anh. New voices/checkpoints stay quarantined until intelligibility, pronunciation, naturalness, artifacts and dissimilarity are reviewed against a SHA256-bound audition. Never claim training or listening occurred without evidence.

Before expensive generation, run `studio brief PROJECT --interactive --detailed`, then `studio preflight PROJECT`; resolve the creator’s requirements and review the concrete brief before `studio brief PROJECT --approve --reviewer NAME`. Static preflight is a text storyboard, not a rendered layout. Default budget is one full render per approved brief; inspect QC before explicitly granting another attempt. Source or plan changes invalidate approval. Target duration is advisory when preserving complete source clips.


Nghe thử giọng nam miền Nam (chưa train mới): `.venv/Scripts/python.exe scripts/voice_lab.py audition`. Mẫu ở `voices/candidates/`, không vào pool production. Chỉ người thực sự nghe và đánh giá được chạy `scripts/voice_lab.py review VOICE_ID --reviewer NAME --confirm-listened --confirm-dissimilar --confirm-pronunciation --confirm-natural --confirm-clean`. Không tự tick thay người nghe.


OmniVoice test support: `studio voices audition omnivoice-vi-thaison` creates/reuses a quarantined audio sample. This machine currently selects OmniVoice via `config/local.yaml` and the social config; a saved brief retains its explicitly selected voice, so update and review that brief before switching an existing project. Generic and native Threads/Reddit use the same registry provider and SHA256 admission checks. The test reference is an existing synthetic Thái Sơn clip, not Mai Anh. Model revision and reference hash are pinned; changing either invalidates voice reviews and audio caches. Do not approve listening checks automatically.

Runtime: `scripts/install_omnivoice.ps1` creates `D:/studio-node/tts/omnivoice/.venv` independently of VieNeu. Official API: https://github.com/k2-fsa/OmniVoice ; model/license: https://huggingface.co/k2-fsa/OmniVoice . Code is Apache-2.0; the pretrained model is CC-BY-NC. This setup is for the requested private test. Reference audio stays local in `voices/local/references/`; on another machine, provide a permitted reference, its exact transcript and SHA256 in a new profile, then audition/review.
