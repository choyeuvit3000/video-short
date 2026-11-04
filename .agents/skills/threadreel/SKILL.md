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
3. Agent sửa và kiểm tra lỗi trong phạm vi đã duyệt; gói cuối để người dùng xem và duyệt:
```powershell
.\.venv\Scripts\python.exe -m studio review PROJECT --stage final
```
Review gắn SHA256: sửa video sẽ làm review cũ hết hiệu lực. Không tự đánh dấu nội dung được duyệt chỉ vì FFmpeg chạy xong. Ghi rõ cách kiểm tra audio và giới hạn; nếu chưa đủ bằng chứng về nội dung hoặc hình/tiếng, để chờ review.

Asset: `studio social-assets scan|fetch`; ảnh/video meme, sound, sfx và các clip nền ở data root. Meme chỉ chèn khi phù hợp; tránh nội dung tang sự/tai nạn/bệnh tật/tranh chấp.


## Output chung

Video cuối dùng chung root `D:/Video-maker/video-short/output`, chia thư mục `YYYY-MM-DD/MODE/` theo ngày và mode; không rải trong project. Tên file có prefix mode và ID để không ghi đè; QC/phụ đề/metadata cùng basename. Dùng đường dẫn CLI trả về để review. Các bản cũ nằm trong `_history`; intermediates ở work.


Thêm nền riêng: `studio social-assets import-background --source VIDEO --seconds 60`. Lệnh giữ file nguồn, tạo các clip silent theo keyframe, giữ manifest cũ, đăng ký shared asset bằng hardlink khi có thể. Media chỉ local; code và asset metadata được commit.


## Voice admission and generation planning

Edge (all voices/providers), Mai Anh and aliases are permanently forbidden, including random selection, fallback and cached audio. Prefer a deep male Southern Vietnamese voice; reject voices that sound like Mai Anh. New voices/checkpoints stay quarantined until intelligibility, pronunciation, naturalness, artifacts and dissimilarity are reviewed against a SHA256-bound audition. Never claim training or listening occurred without evidence.

Before expensive generation, clarify the concrete brief and run `studio preflight PROJECT`. Then follow the three user-owned checkpoints in `studio review`: script plus production choices, voice plus layout/timings, final video after QC. Only record an actual user acceptance with `--action approve --message` containing that response. Never invent it or use Codex/agent approval as a substitute. Edits before acceptance stay within that checkpoint; changed accepted content invalidates its hash. There are at most three accepted review events per video/bundle; do not silently reset or grant a fourth. Full render budget remains separate (default one per approved brief).


OmniVoice test support: `studio voices audition omnivoice-vi-thaison` creates/reuses a quarantined audio sample. This machine currently selects OmniVoice via `config/local.yaml` and the social config; a saved brief retains its explicitly selected voice, so update and review that brief before switching an existing project. Generic and native Threads/Reddit use the same registry provider and SHA256 admission checks. The test reference is an existing synthetic Thái Sơn clip, not Mai Anh. Model revision and reference hash are pinned; changing either invalidates voice reviews and audio caches. Do not approve listening checks automatically.


Vietnamese knowledge videos use `omnivoice-vi-knowledge-under30` by default (`knowledge_explainer` and `longform_explainer`). This follows the newer user-provided Under30 audio reference and its brisk conversational cadence, rather than forcing the older generic voice preference. Reference is copied into local voices assets; no training was run. Target is 5.4 whitespace-separated speech units/second, measured source 5.44; the test generated 5.35. The knowledge workflow uses audio.speed=1.0 because its voice profile already controls cadence. Explicit project voices override workflow defaults; English keeps its own voice. SHA-bound generated-sample listening review still applies; do not mark naturalness or similarity approved from ASR alone.


The user approved the presented Under30 knowledge audition ("qúa oke"). `omnivoice-vi-knowledge-under30` is now ready and admitted locally for Vietnamese knowledge videos at the approved cadence. Keep its SHA-bound review; do not ask to approve that same unchanged sample again. New reference/model/profile or changed audition still requires a new review.


## Three creator approvals (user instruction, 2026-11-04)

1. **Script and production choices:** simplify jargon/English; check factual fidelity and spoken Vietnamese numbers, ratios, dates, symbols and abbreviations. Show the complete editable script, Reddit character map and opening lines, duration/part target, captions and background/effects choices. Prepare `studio review PROJECT --stage script`; wait for the user before TTS. A known voice being globally admitted does not approve this video's audio.
2. **Narration and layout:** after script acceptance, generate/cache only required speech and timings; present all actual audio, pronunciation checks, part boundaries and layout/subtitle preview together. Use `studio voice PROJECT`, or `studio social-voice PROJECT` / `studio reddit-story voice --id ID`, then prepare `--stage voice`. User may request changes before accepting. Never silently switch voices or accelerate after this acceptance. News/knowledge/Threads word emphasis must use actual speech anchors, not evenly estimated timestamps; ASR mismatch stops the workflow. Keep phrase geometry stable (no per-word size pop), two lines, restrained contrast, no heavy black box; use dark ink on light canvases.
3. **Final video:** render only after user accepts narration; run technical QC and inspect visuals/audio, present video and material limitations, then wait for user acceptance via `--stage final`. Do not upload, schedule, comment or pin without explicit authorization. A technical PASS is not user approval.

`studio review PROJECT --stage STAGE --action approve --message "actual user reply"` is used only after that reply arrives. `user_reviews.json` hashes bind accepted versions. Old `options.reviewed`, old creative brief approval, `--force`, render caches and `social-review --reviewer Codex` cannot authorize new work. At most three accepted approvals total; edits proposed before acceptance do not consume an approval. If accepted content changes and the budget cannot cover all stages, stop and ask the user how to proceed, without resetting it. For Reddit multipart output, present all parts and the full version in the same three checkpoints.

Reddit: maintain a fixed `character_map` for the whole story (explicit `{}` when none), with Vietnamese names or a user-reviewed reading. Preserve original places/events; changes of setting require the user's script-stage acceptance. Default Shorts ceiling is 75 seconds including opening/effects/end card, at about 1.1 speech speed. This is an experimental editorial target, not a claim about YouTube's algorithm. Start with the dramatic situation; never narrate a part number at the opening. Longer stories also export a genuine 1920x1080 full recomposition from the approved complete narration; do not pad it to an arbitrary duration. `youtube_handoff.json` records local Short/full paths and Related Video instructions, not a completed upload.
