
## Social video: lasting user preference

The approved merged Threads video is the output standard, not the former Threadreel UI/digest.
Use `.venv/Scripts/python.exe -m studio threads-post URL_OR_CAPTURE_DIR`.
Keep authentic screenshots, blurred background, complete source clip/audio, giọng local đã duyệt QC (ưu tiên nam trầm miền Nam),
and persistent source credit. Do not turn a Threads post into a narrated fictional story.
Reddit storytelling is separate: `studio reddit-story render --id ID`.
Both modes must produce mastering, automatic QC, contact sheets, and SHA256-bound editorial review.
Inspect visual readability, transitions, source fidelity, and audio before calling a video final.
Do not equate successful FFmpeg exit or automatic QC PASS with completed editorial review.
Fix and re-render failed output. Keep the previous good version on failure.
See `.agents/skills/threadreel/SKILL.md` and `docs/SOCIAL_VIDEO.md`.
All data is under `projects/social_video`; the old Downloads folder is retired.


All modes share `D:/Video-maker/video-short/output/YYYY-MM-DD/MODE/`. Date uses Asia/Bangkok and stays fixed for resume/QC. QC, captions and metadata sit beside the video with the same basename; `_history` holds older revisions. Project work folders contain intermediates only.


## Voice admission and generation planning

Edge (all voices/providers), Mai Anh and aliases are permanently forbidden, including random selection, fallback and cached audio. Prefer a deep male Southern Vietnamese voice; reject voices that sound like Mai Anh. New voices/checkpoints stay quarantined until intelligibility, pronunciation, naturalness, artifacts and dissimilarity are reviewed against a SHA256-bound audition. Never claim training or listening occurred without evidence.

Before expensive generation, run `studio brief PROJECT --interactive --detailed`, then `studio preflight PROJECT`; resolve the creator’s requirements and review the concrete brief before `studio brief PROJECT --approve --reviewer NAME`. Static preflight is a text storyboard, not a rendered layout. Default budget is one full render per approved brief; inspect QC before explicitly granting another attempt. Source or plan changes invalidate approval. Target duration is advisory when preserving complete source clips.


OmniVoice test support: `studio voices audition omnivoice-vi-thaison` creates/reuses a quarantined audio sample. This machine currently selects OmniVoice via `config/local.yaml` and the social config; a saved brief retains its explicitly selected voice, so update and review that brief before switching an existing project. Generic and native Threads/Reddit use the same registry provider and SHA256 admission checks. The test reference is an existing synthetic Thái Sơn clip, not Mai Anh. Model revision and reference hash are pinned; changing either invalidates voice reviews and audio caches. Do not approve listening checks automatically.


Vietnamese knowledge videos use `omnivoice-vi-knowledge-under30` by default (`knowledge_explainer` and `longform_explainer`). This follows the newer user-provided Under30 audio reference and its brisk conversational cadence, rather than forcing the older generic voice preference. Reference is copied into local voices assets; no training was run. Target is 5.4 whitespace-separated speech units/second, measured source 5.44; the test generated 5.35. The knowledge workflow uses audio.speed=1.0 because its voice profile already controls cadence. Explicit project voices override workflow defaults; English keeps its own voice. SHA-bound generated-sample listening review still applies; do not mark naturalness or similarity approved from ASR alone.


The user approved the presented Under30 knowledge audition ("qúa oke"). `omnivoice-vi-knowledge-under30` is now ready and admitted locally for Vietnamese knowledge videos at the approved cadence. Keep its SHA-bound review; do not ask to approve that same unchanged sample again. New reference/model/profile or changed audition still requires a new review.
