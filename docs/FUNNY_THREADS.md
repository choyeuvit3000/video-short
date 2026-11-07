# Funny Threads

The creator's November seven preference adds a separate `funny_threads` mode. Use authentic post/comment screenshots,
own local gameplay, source credit, performed Vietnamese voices and restrained comedy music/SFX. The existing merged
Threads and horror modes retain their choices. Do not turn this mode into a narrated fictional story.

## Before speech

Make the editable beat plan first. Keep full source provenance, post text, selected comments, images and voice casting
visible in `merged_plan.json` and the script packet. A screenshot extracted from a creator-supplied reference is labeled
as such; it is not a newly captured Threads page. Never manufacture a missing URL or a comment under a real username.
Maintain a stable reading voice for the same author. Change voices between commenters, using a reviewed pool of male
and female Northern, Central and Southern voices across videos. Casting does not identify the real author's gender/accent.
Preserve original screenshot text. Light normalization for speech belongs in the plan, including all number/slang changes.

Choose comments for their contribution to the source joke. Long posts need fewer comments; short posts can carry more.
Estimate time with every spoken beat, then use actual audio to settle length. Do not fill a timer, rush a sentence, or
add a comment only to demonstrate another voice. A brief apparent contradiction is not proof that an author lied.
The creator's fourth reference is useful for a setup/reveal and reaction-cover composition, not for an accusation.

Script acceptance precedes TTS. New cast members are quarantined project auditions, never a random/fallback pool.
Edge/Mai Anh remain blocked. Preserve the three creator checkpoints. Only the creator can waive a checkpoint for
a named pilot; keep the exact response. Never label agent/ASR inspection as a human listening approval.

Selected pronunciation repairs live in `voice_repairs.json`, bound to the script words, profile, speed and waveform hash.
Resume must reuse the checked take rather than restoring an earlier rejected take. A brief conditioning lead-in may be
removed only inside measured silence; preserve the full source, exact PCM crop coordinates and ASR provenance. Context
recognition may provide the target window only after proving that the selected PCM is the exact corresponding source
slice. Keep alternative raw decodes and unresolved regional spelling visible; this does not certify human pronunciation.

## Prepare and review

```powershell
.venv/Scripts/python.exe scripts/prepare_funny_threads_assets.py
.venv/Scripts/python.exe -m studio funny-threads PROJECT --action layouts
.venv/Scripts/python.exe -m studio preflight PROJECT
.venv/Scripts/python.exe -m studio review PROJECT --stage script
# After the creator actually accepts the script/cast:
.venv/Scripts/python.exe -m studio funny-threads PROJECT --action voice
.venv/Scripts/python.exe -m studio funny-threads PROJECT --action check-speech
.venv/Scripts/python.exe -m studio review PROJECT --stage voice
# After actual voice acceptance, or an exact project-scoped waiver:
.venv/Scripts/python.exe -m studio funny-threads PROJECT --action render
.venv/Scripts/python.exe -m studio review PROJECT --stage final
```

Speech uses the pinned local VieNeu worker. Preserve unpaced PCM and onset protection. Speed is applied once before
review. The first pilot proposes 1.15, separately from horror's 1.25. Keep about 0.6 seconds between spoken comments,
plus any source-related image/reaction hold; final timings use actual waveform length. Do not run silence removal.
The whole mixed audition, the exact layout PNGs and input hashes belong to the voice checkpoint. Raw ASR stays visible;
similarity is a screening signal and cannot certify natural delivery, accent, or dissimilarity to Mai Anh.

The pipeline checks complete cast coverage, unchanged screenshot/music/effect hashes and distinct adjacent comment voices.
It reuses cached scenes for technical repairs. All outputs share `output/YYYY-MM-DD/funny_threads/`, date pinned on resume.
Master twice to minus fourteen LUFS with a minus one point five dB true-peak target; run Studio QC and inspect the encoded
sheet plus first/last/reveal frames. The final result remains pending creator review and is never uploaded automatically.

## Assets and covers

`assets/shared/music/library.json` contains Monkeys Spinning Monkeys plus Fluffing a Duck and Sneaky Snitch.
The new tracks were downloaded from the composer's official site. They require attribution under CC BY 4.0; copy the
render's `.credits.txt` into the publication description. Official terms:
[Incompetech music FAQ](https://incompetech.com/music/royalty-free/faq.html).

`assets/shared/overlays/funny_originals/library.json` indexes eight original procedural effects and two original vector
mascot reactions, each as an image and a short animated clip. These are original project assets, not recordings of the
trending named effects. Keep their hashes. The Kenney CC0 pack is documented but its download returned HTTP 403;
do not count it as installed. Plants vs. Zombies is a mood reference, not verified free production music.

Make a cover from an actual in-video image/comment and a short relevant title. Preserve context, faces and readable
source credit. Do not use an unrelated woman as bait. The creator requested a one-tenth-second insert: at thirty fps,
replace exactly three mid-video frames without moving the audio/timeline. Decode the three frames and both neighbors
to verify the window. Also deliver a standalone `.cover.png` for upload. A flash frame does not force platform selection.
Encode scene and cover parts with consistent BT.709 matrix/range/transfer/primaries. Inconsistent H.264 VUI in a reaction
clip can make FFmpeg reset frame-based filters during concatenation. Normalize legacy scene tags without re-encoding,
replace explicit pre/three-frame-cover/post ranges, and verify both decoded cover neighbors and the full frame count.
As checked on November seven, YouTube's official help describes custom Shorts thumbnail uploads in desktop Studio:
[YouTube thumbnail help](https://support.google.com/youtube/answer/72431?hl=en). Account availability still determines the UI.

## Reference analysis

The supplied samples demonstrate authentic card crops, image reveals, short reactions, music and pauses between voices.
The latest example contrasts a boastful post with a room-search post and uses a cat reaction above the screenshot in its
cover. Learn the composition and beat structure; use own gameplay/mix/branding. Do not copy another creator's whole
finished video or pretend an extracted screenshot was independently verified. The hidden-camera safety sample is useful
for formatting but is unsuitable for a comedy/meme pilot.
