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

### Truyện từ Threads theo yêu cầu riêng

Khi người dùng yêu cầu rõ lấy truyện Threads và kể theo phong cách Reddit, dùng renderer kể chuyện chung; đây là ngoại lệ theo yêu cầu, không thay chuẩn Threads merged. Giữ `platform: threads`, tác giả và URL thật trong `source.json`; thẻ ghi Threads/@tác giả, output thuộc `threads_story` (bản ngang: `threads_story_full`). Nếu có đoạn không công khai, chỉ tóm lược phần truy cập được trong phạm vi người dùng chọn; không bịa đoạn nối hoặc kết cục.

`video_brief.json.answers.speech_speed` là hệ số tốc độ chính xác người dùng chọn (ví dụ `1.25`), được áp dụng một lần; không nhân thêm hệ số Reddit cũ. `background: random` chọn từ kho nền, bỏ đoạn quá tối; `background_plan.json` giữ nguyên clip/điểm bắt đầu/crop cho preview và render, gắn hash vào gói duyệt giọng. Bố cục hoặc nguồn nền thay đổi phải chuẩn bị lại preview. Vẫn giữ đủ ba mốc duyệt trước TTS, trước render và sau QC.

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


OmniVoice test support: `studio voices audition omnivoice-vi-thaison` creates/reuses a quarantined audio sample. OmniVoice remains available for explicit or long-format use; Vietnamese Shorts now select VieNeu via the format default; a saved brief retains its explicitly selected voice, so update and review that brief before switching an existing project. Generic and native Threads/Reddit use the same registry provider and SHA256 admission checks. The test reference is an existing synthetic Thái Sơn clip, not Mai Anh. Model revision and reference hash are pinned; changing either invalidates voice reviews and audio caches. Do not approve listening checks automatically.


Vietnamese news/knowledge short_9x16 videos default to `vieneu-vi-short` (VieNeu v3 Turbo, Minh Triết, male Southern news preset). The model revision, installed SDK version and preset hash are pinned. Speed is 1.0; preserve native pauses and complete spoken ideas, do not force duration from token counts or insert uniform pauses. The model stays experimental until the creator hears and accepts its audition. The older Under30 OmniVoice profile remains an explicit/long-format choice; its previous approval does not admit the new VieNeu voice or this video. Explicit project choices remain visible in the brief. Never auto-approve pronunciation or naturalness from ASR.


Historical voice approval: the user accepted the Under30 audition ("qúa oke"), then reported pronunciation/cadence failures in the short video and requested a native Vietnamese default. Keep the historical SHA-bound Under30 review for unchanged explicit/long-format use. It does not override the newer native Vietnamese Shorts default or approve new per-video narration. The news/knowledge Minh Triết audition still needs the creator’s listening acceptance; never mark it passed from ASR alone.


## Three creator approvals (user instruction, 2026-11-04)

1. **Script and production choices:** simplify jargon/English; check factual fidelity and spoken Vietnamese numbers, ratios, dates, symbols and abbreviations. Show the complete editable script, Reddit character map and opening lines, duration/part target, captions and background/effects choices. Prepare `studio review PROJECT --stage script`; wait for the user before TTS. A known voice being globally admitted does not approve this video's audio.
2. **Narration and layout:** after script acceptance, generate/cache only required speech and timings; present all actual audio, pronunciation checks, part boundaries and layout/subtitle preview together. Use `studio voice PROJECT`, or `studio social-voice PROJECT` / `studio reddit-story voice --id ID`, then prepare `--stage voice`. User may request changes before accepting. Never silently switch voices or accelerate after this acceptance. News/knowledge/Threads word emphasis must use actual speech anchors, not evenly estimated timestamps; ASR mismatch stops the workflow. Keep phrase geometry stable (no per-word size pop), two lines, restrained contrast, no heavy black box; use dark ink on light canvases.
3. **Final video:** render only after user accepts narration; run technical QC and inspect visuals/audio, present video and material limitations, then wait for user acceptance via `--stage final`. Do not upload, schedule, comment or pin without explicit authorization. A technical PASS is not user approval.

`studio review PROJECT --stage STAGE --action approve --message "actual user reply"` is used only after that reply arrives. `user_reviews.json` hashes bind accepted versions. Old `options.reviewed`, old creative brief approval, `--force`, render caches and `social-review --reviewer Codex` cannot authorize new work. At most three accepted approvals total; edits proposed before acceptance do not consume an approval. If accepted content changes and the budget cannot cover all stages, stop and ask the user how to proceed, without resetting it. For Reddit multipart output, present all parts and the full version in the same three checkpoints.

An explicit later user instruction can waive checkpoints for a named project/batch. Record the exact message, project ID and stages in `review_waiver.json`; `USER_REVIEW_WAIVED` authorizes autonomous completion without inventing a listening/final-content acceptance or adding approval events. Keep source/script checks, admitted voices, actual speech assets, technical QC and render budgets. Record agent inspection separately; never label it a human listening review. A batch waiver does not change the default for later videos.

Reddit: maintain a fixed `character_map` for the whole story (explicit `{}` when none), with Vietnamese names or a user-reviewed reading. Preserve original places/events; changes of setting require the user's script-stage acceptance. For horror stories, content comes first: aim around 90 seconds, allow a complete story to run longer (default per-Short technical ceiling 180 seconds including hook/question/end card), and split longer material at reviewed suspense beats. Do not squeeze a complete idea into 35 seconds. The admitted horror default is `vieneu-gallery-thai-son`, speed 1.25 applied once in TTS. News/knowledge retain their own voice defaults. This is an experimental editorial target, not a claim about YouTube's algorithm. Start with the dramatic situation; never narrate a part number at the opening. Longer stories also export a genuine 1920x1080 full recomposition from the approved complete narration; do not pad it to an arbitrary duration. `youtube_handoff.json` records local Short/full paths and Related Video instructions, not a completed upload.


## Spoken-number and pacing evidence

The user reported omitted “phẩy” and unnatural cadence in the Under30 video sample. Do not treat `map_onto_text`'s expansion of ASR `5,2` into “năm phẩy hai” as evidence that the word was spoken. `work/speech_checks/*.json` keeps the raw transcript, expected critical number phrases and exact audio/text hashes. Symbolic ASR numbers stay `ASR_NUMERIC_AMBIGUOUS`, requiring listening at checkpoint two; a missing critical marker in literal ASR cannot be silently interpolated in strict alignment. Review the actual speech, not only the subtitles. Numeric reports are part of the user-approved voice packet and become stale if the audio changes. Keep this inside the existing three checkpoints, not an extra approval stage.

Shorts use the format voice default even in the knowledge/news workflows; long_16x9 retains its workflow choice. The native social default also selects VieNeu. Renderers consume the exact approved speech assets, never synthesize new speech after voice acceptance. Video caches bind to the accepted audio fingerprint. If natural delivery would exceed the target, offer a longer video or a suspense-based split before script approval; shorten only when it preserves the complete idea and the creator chooses that option. Never squeeze the generated waveform to a timer. The audition-based speech-rate hint is an estimate for planning, not a forced TTS duration.


## Future horror quality defaults (creator feedback, 2026-11-05)

- Native narration uses protected PCM throughout, no MP3 round trip or aggressive silence removal. Protect about 100 ms before and 125 ms after detected speech (at least 225 ms between adjacent sentences), without deleting quiet consonants or natural breaths. Add onset protection before the chosen tempo transform, then verify final boundaries. Generic trimming is conservative at minus fifty decibels with 120/125 ms retained. Audio cache identity includes this processing version; native PCM and raw ASR caches verify hashes before reuse.
- Default horror bed is measured at minus twenty-three decibels relative to narration before gentle ducking, with fades. Add restrained hook and source-matched laughter/footstep/door/whisper cues at actual speech anchors. No arbitrary comic laughter, loud random jump scares or silent fallback on missing/changed assets. Include full mixed audio, cue plan and a layout preview in checkpoint two. Bind music/SFX/background files by hash before approval.
- Story cards sit at seventeen percent of screen height, with soft radius, subtle border/shadow, at most three body lines, and stable emphasis in two-to-three-word phrases from real speech anchors. Use decorative heart/comment/repost icons without invented counts. Credit the real source and label narrated adaptation as `Kể lại từ nguồn`; do not imply the rewritten card is a verbatim screenshot. News/knowledge keep their distinct two-line subtitle design.
- Horror background randomization is restricted to reviewed native 1080p/60fps night/rain/cool-shader footage. Exclude lava/minecart glare, empty-map/black sections and low-quality footage. Never upscale or interpolate to pretend an asset qualifies. Use mild darkening/vignette and check that already-dark footage remains visible. A missing curated pool stops preparation; never fall back to the old mixed gameplay pool. Rebuild with `.venv/Scripts/python.exe scripts/prepare_horror_assets.py`; source/license/ranges live in `assets/shared/horror/library.json`, media remains local.
- Add one short, editable local-culture/source-related closing question before script approval. Earlier Shorts in a multipart story repeat that approved question; the full version contains it once. Do not invent story facts, identify an unspecified supernatural entity as fact, promise engagement gains, or narrate part numbers at the opening. A creator may explicitly remove/change the question at the script checkpoint.
- Raw ASR disagreement is a review signal, not proof of correct pronunciation. Preserve the raw transcript and actual audio; strict alignment blocks mismatched clips instead of hiding a voice error with corrected subtitles. Keep the existing maximum of three creator checkpoints; the previous batch waiver is not a global waiver.


## East Asian original horror writing (creator revision, 2026-11-05)

For requested original fiction/adaptation, follow `docs/EAST_ASIAN_HORROR_WRITING.md` before drafting. Keep all ten craft rules with the creator's supplements to rules five, seven and nine: one meaningful sound/smell/touch cue in the first fifteen seconds of each episode; a self-contained opening event for every episode, with context in sentence two; prefer sentences shorter than fifteen whitespace-separated units in the marked climax, using full stops for dramatic beats while preserving varied natural prose elsewhere. Keep the whole season's ending and clue/object ledger planned before splitting. Early hooks must not disclose the later explanation; a missing child is not established dead, an object cannot occupy two places without a planned explanation, and weather/timeline must agree across parts.

Source-faithful Threads/Reddit remains faithful: do not invent sensory events, dates, causes or folklore to meet a fiction rule. New fiction has an honest fiction/inspiration label; do not invent a source URL/author or present a rewritten story as a real post/case. Use `studio.social_video.story_policy.original_story_prompt()` for original writing, not the translation prompt. Run `studio story-draft-review DRAFT_JSON` before presenting the script; its count is whitespace-separated units, not lexical Vietnamese words or guaranteed seconds. Its semantic and three/fifteen-second checks remain pending creator review and actual speech anchors; the report cannot approve a script or narration. Preserve the creator's supplied revision and save editorial changes separately. Keep three user checkpoints; feedback/rewrite is not approval of audio/video and does not waive them.

Treat sixty-to-seventy-five seconds as an editorial experiment, not a claim that YouTube guarantees preference. Verify platform monetization requirements separately; duration alone does not establish eligibility. Use actual voice at speed 1.25 once to measure final timing; don't pad silence or force tempo to reach a threshold. New writing policy does not authorize TTS before the script checkpoint.
