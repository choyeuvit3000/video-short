# Studio hợp nhất: Threads merged và Reddit

Nghe toàn bộ giọng Việt VieNeu (loại Mai Anh, tên trùng/alias bị cấm):
`python scripts/voice_gallery.py` trong venv Studio. Bộ mẫu nằm tại
`output/YYYY-MM-DD/voice_samples/vieneu_all/`: trang nghe offline có lọc/lưu ứng viên,
video có tên từng giọng và ZIP. Cùng một đoạn có “năm phẩy hai”, cùng âm lượng nghe,
giữ tốc độ gốc; dùng lại audio đúng hash khi chạy lại. Đây là các ứng viên chờ người
dùng chọn, không tự duyệt giọng hoặc đổi giọng video. Khi chọn, lấy đúng profile/signature
và tệp nghe trong manifest; tên cũ được gộp vào giọng chuẩn, không tạo mẫu trùng.

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

Khi người dùng yêu cầu riêng truyện Threads theo phong cách Reddit, giữ `platform: threads`, tác giả và URL trong `source.json`; `vi.json` chứa bản kể đã biên tập để duyệt. Thẻ giữ nguồn Threads và output dùng `threads_story`/`threads_story_full`. Những trả lời không công khai không được tự điền nội dung. Chuẩn Threads merged thông thường vẫn giữ nguyên.

Trong brief, `speech_speed: 1.25` đặt đúng tổng tốc độ một phẩy hai mươi lăm lần, không nhân thêm hệ số Reddit. `background: random` chọn một đoạn nền đủ rõ rồi lưu clip/điểm bắt đầu/crop/SHA256 vào `background_plan.json`; gói duyệt giọng ràng buộc cả nền đã xem. Render dùng lại lựa chọn đó. Nền hoặc bố cục đổi cần chuẩn bị lại preview trước khi duyệt; không đổi âm thầm sau duyệt.

## QC bắt buộc

Mỗi video được mastering hai lượt về đích -14 LUFS/-1.5 dBTP, kiểm tra H.264/yuv420p/1080×1920/30fps, AAC stereo 48 kHz, thời lượng, âm lượng, true peak, silence/black/freeze và tạo contact sheet. Một số thẻ bài tĩnh/nền tối sẽ tạo cảnh báo; không tự cắt cảnh nguồn để làm detector hết báo. Kiểm tra trực quan và kiểm tra audio trong ngữ cảnh.

- `automatic: PASS`, `editorial: PENDING`, `status: REVIEW_REQUIRED`: đã qua kiểm tra máy, chưa duyệt nội dung.
- `status: FAIL`: không được thay thế bản tốt trước đó.
- `status: PASS`, `editorial: APPROVED`: đã có người dùng duyệt mốc cuối, ghi chú và SHA256 đúng file hiện tại.

```powershell
.\.venv\Scripts\python.exe -m studio social-qc VIDEO
.\.venv\Scripts\python.exe -m studio review PROJECT --stage final
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

Before expensive generation, clarify the concrete brief and run `studio preflight PROJECT`. Then follow the three user-owned checkpoints in `studio review`: script plus production choices, voice plus layout/timings, final video after QC. Only record an actual user acceptance with `--action approve --message` containing that response. Never invent it or use Codex/agent approval as a substitute. Edits before acceptance stay within that checkpoint; changed accepted content invalidates its hash. There are at most three accepted review events per video/bundle; do not silently reset or grant a fourth. Full render budget remains separate (default one per approved brief).

If the creator explicitly requests autonomous completion of a named batch, record that real message, project ID and waived stages in each `review_waiver.json`. Reports say `USER_REVIEW_WAIVED`, not a fabricated listening/final approval. The workflow still checks source/script, admitted voice, actual audio and final QC. Agent visual/ASR inspection is separate from user acceptance. Other batches retain the default three checkpoints.


Nghe thử giọng nam miền Nam (chưa train mới): `.venv/Scripts/python.exe scripts/voice_lab.py audition`. Mẫu ở `voices/candidates/`, không vào pool production. Chỉ người thực sự nghe và đánh giá được chạy `scripts/voice_lab.py review VOICE_ID --reviewer NAME --confirm-listened --confirm-dissimilar --confirm-pronunciation --confirm-natural --confirm-clean`. Không tự tick thay người nghe.


OmniVoice test support: `studio voices audition omnivoice-vi-thaison` creates/reuses a quarantined audio sample. OmniVoice remains available for explicit or long-format use; Vietnamese Shorts now select VieNeu via the format default; a saved brief retains its explicitly selected voice, so update and review that brief before switching an existing project. Generic and native Threads/Reddit use the same registry provider and SHA256 admission checks. The test reference is an existing synthetic Thái Sơn clip, not Mai Anh. Model revision and reference hash are pinned; changing either invalidates voice reviews and audio caches. Do not approve listening checks automatically.

Runtime: `scripts/install_omnivoice.ps1` creates `D:/studio-node/tts/omnivoice/.venv` independently of VieNeu. Official API: https://github.com/k2-fsa/OmniVoice ; model/license: https://huggingface.co/k2-fsa/OmniVoice . Code is Apache-2.0; the pretrained model is CC-BY-NC. This setup is for the requested private test. Reference audio stays local in `voices/local/references/`; on another machine, provide a permitted reference, its exact transcript and SHA256 in a new profile, then audition/review.


Vietnamese short_9x16 videos default to `vieneu-vi-short` (VieNeu v3 Turbo, Minh Triết, male Southern news preset). The model revision, installed SDK version and preset hash are pinned. Speed is 1.0; preserve native pauses and complete spoken ideas, do not force duration from token counts or insert uniform pauses. The model stays experimental until the creator hears and accepts its audition. The older Under30 OmniVoice profile remains an explicit/long-format choice; its previous approval does not admit the new VieNeu voice or this video. Explicit project choices remain visible in the brief. Never auto-approve pronunciation or naturalness from ASR.


## Three creator approvals (user instruction, 2026-11-04)

1. **Script and production choices:** simplify jargon/English; check factual fidelity and spoken Vietnamese numbers, ratios, dates, symbols and abbreviations. Show the complete editable script, Reddit character map and opening lines, duration/part target, captions and background/effects choices. Prepare `studio review PROJECT --stage script`; wait for the user before TTS. A known voice being globally admitted does not approve this video's audio.
2. **Narration and layout:** after script acceptance, generate/cache only required speech and timings; present all actual audio, pronunciation checks, part boundaries and layout/subtitle preview together. Use `studio voice PROJECT`, or `studio social-voice PROJECT` / `studio reddit-story voice --id ID`, then prepare `--stage voice`. User may request changes before accepting. Never silently switch voices or accelerate after this acceptance. News/knowledge/Threads word emphasis must use actual speech anchors, not evenly estimated timestamps; ASR mismatch stops the workflow. Keep phrase geometry stable (no per-word size pop), two lines, restrained contrast, no heavy black box; use dark ink on light canvases.
3. **Final video:** render only after user accepts narration; run technical QC and inspect visuals/audio, present video and material limitations, then wait for user acceptance via `--stage final`. Do not upload, schedule, comment or pin without explicit authorization. A technical PASS is not user approval.

`studio review PROJECT --stage STAGE --action approve --message "actual user reply"` is used only after that reply arrives. `user_reviews.json` hashes bind accepted versions. Old `options.reviewed`, old creative brief approval, `--force`, render caches and `social-review --reviewer Codex` cannot authorize new work. At most three accepted approvals total; edits proposed before acceptance do not consume an approval. If accepted content changes and the budget cannot cover all stages, stop and ask the user how to proceed, without resetting it. For Reddit multipart output, present all parts and the full version in the same three checkpoints.

Reddit: maintain a fixed `character_map` for the whole story (explicit `{}` when none), with Vietnamese names or a user-reviewed reading. Preserve original places/events; changes of setting require the user's script-stage acceptance. Default Shorts ceiling is 75 seconds including opening/effects/end card; Vietnamese native speech stays at speed 1.0 unless the creator explicitly chooses otherwise. This is an experimental editorial target, not a claim about YouTube's algorithm. Start with the dramatic situation; never narrate a part number at the opening. Longer stories also export a genuine 1920x1080 full recomposition from the approved complete narration; do not pad it to an arbitrary duration. `youtube_handoff.json` records local Short/full paths and Related Video instructions, not a completed upload.


## Spoken-number and pacing evidence

The user reported omitted “phẩy” and unnatural cadence in the Under30 video sample. Do not treat `map_onto_text`'s expansion of ASR `5,2` into “năm phẩy hai” as evidence that the word was spoken. `work/speech_checks/*.json` keeps the raw transcript, expected critical number phrases and exact audio/text hashes. Symbolic ASR numbers stay `ASR_NUMERIC_AMBIGUOUS`, requiring listening at checkpoint two; a missing critical marker in literal ASR cannot be silently interpolated in strict alignment. Review the actual speech, not only the subtitles. Numeric reports are part of the user-approved voice packet and become stale if the audio changes. Keep this inside the existing three checkpoints, not an extra approval stage.

Shorts use the format voice default even in the knowledge/news workflows; long_16x9 retains its workflow choice. The native social default also selects VieNeu. Renderers consume the exact approved speech assets, never synthesize new speech after voice acceptance. Video caches bind to the accepted audio fingerprint. If natural delivery would exceed the target, shorten the draft before script approval instead of squeezing the generated waveform. The audition-based speech-rate hint is an estimate for planning, not a forced TTS duration.
