"""Prepare native voice for user checkpoint 2 without rendering any video."""

from pathlib import Path

from ..core.creative_brief import apply_social
from ..core.user_review import digest, prepare, require, write
from ..core.voice_policy import assert_social_config, signature, social_profile
from .util import load_config, read_json


def prepare_voice(folder: Path):
    folder = folder.resolve()
    require(folder, "script")
    cfg = load_config()
    apply_social(folder, cfg)
    assert_social_config(cfg["tts"])
    if (folder / "vi.json").is_file():
        from .reddit import chunks, voice_story
        from .reddit_edit import plan

        vi = read_json(folder / "vi.json")
        voiced = voice_story(vi["paragraphs"], cfg, vi.get("cast", {}), folder / "audio")
        from ..core.speech_checks import critical_numbers, save_audit
        from ..providers.align import faster_whisper_words

        for i, (sentence, (audio, _seconds)) in enumerate(
            zip([s for g in chunks(vi["paragraphs"]) for s in g], voiced, strict=True)
        ):
            if critical_numbers(sentence):
                save_audit(folder, f"reddit_{i:04d}", audio, sentence, faster_whisper_words(audio, "vi"))
        from .reddit import voice_free
        from .reddit_edit import hook_texts, partition

        parts = partition(chunks(vi["paragraphs"]), voiced, float(cfg["reddit"].get("part_max_sec", 75)))
        hooks = hook_texts(vi, parts)
        body = [{"path": str(p.resolve()), "seconds": t} for p, t in voiced]
        hook_assets = [
            voice_free(t, folder / "audio_hook", cfg, vi.get("cast", {}).get("narrator", "narrator_female"))
            if t
            else None
            for t in hooks
        ]
        extra = [asset for asset in hook_assets if asset]
        approved_hooks = [{"path": str(a[0].resolve()), "seconds": a[1]} if a else None for a in hook_assets]
        if any(t > 5 for p, t in extra):
            from ..core.errors import ManualGateRequired

            raise ManualGateRequired("reddit_hook", "Rút câu mở đầu còn tối đa năm giây trước khi duyệt giọng.")
        write(
            folder / "part_plan.json",
            {
                "parts": plan(chunks(vi["paragraphs"]), voiced, float(cfg["reddit"].get("part_max_sec", 75))),
                "hooks": hooks,
            },
        )
        voiced = voiced + extra

    else:
        from ..core.speech_checks import save_audit
        from ..core.subtitles import save_words
        from ..providers.align import faster_whisper_words, map_onto_text
        from .tts import synth
        from .util import media_duration

        beats = read_json(folder / "merged_plan.json", {}).get("beats", [])
        voiced, timings, approved_beats = [], [], {}
        (folder / "subtitles").mkdir(exist_ok=True)
        for i, beat in enumerate(beats):
            if not beat.get("narration", "").strip():
                continue
            audio = folder / f"merged_b{i:02d}.mp3"
            synth(beat["narration"], audio, cfg["tts"])
            seconds = media_duration(audio)
            rec = faster_whisper_words(audio, "vi")
            save_audit(folder, f"merged_b{i:02d}", audio, beat["narration"], rec)
            words = map_onto_text(beat["narration"], rec, int(seconds * 1000), strict=True)
            wp = folder / "subtitles" / f"merged_b{i:02d}.words.json"
            save_words(wp, words, source="faster_whisper")
            timings.append(str(wp.resolve()))
            approved_beats[str(i)] = {"audio": str(audio.resolve()), "words": str(wp.resolve())}
            voiced.append((audio, seconds))
    profile, _ = social_profile(cfg["tts"])
    write(
        folder / "voice_manifest.json",
        {
            "files": [str(p.resolve()) for p, t in voiced],
            "seconds": [t for p, t in voiced],
            "voice_signature": signature(profile),
            "production_choices": digest(
                {"tts": cfg["tts"], "narration_speed": cfg["reddit"].get("narration_speed", 1.1)}
            ),
            **({"timing_files": timings, "beats": approved_beats} if not (folder / "vi.json").is_file() else {}),
            **({"body": body, "hooks": approved_hooks} if (folder / "vi.json").is_file() else {}),
        },
    )
    return prepare(folder, "voice")
