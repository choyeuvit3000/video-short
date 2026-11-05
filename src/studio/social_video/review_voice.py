"""Prepare native voice for user checkpoint 2 without rendering any video."""

from pathlib import Path

from ..core.creative_brief import apply_social
from ..core.user_review import digest, prepare, require, write
from ..core.voice_policy import assert_social_config, signature, social_profile
from .util import load_config, read_json


def align_clip(folder, key, audio, seconds, text, cfg):
    """Reuse raw ASR only when audio, text and recognizer identities still match."""
    from ..core.speech_checks import file_sha, save_audit, text_sha
    from ..core.subtitles import load_words, save_words
    from ..providers.align import faster_whisper_words, map_onto_text

    model = cfg["reddit"].get("word_timing_model", "large-v3-turbo")
    identity = {"audio": file_sha(audio), "text": text_sha(text), "model": model, "version": 1}
    raw = folder / "subtitles" / f"{key}.raw.words.json"
    metadata = raw.with_suffix(".cache.json")
    if raw.is_file() and read_json(metadata, {}) == {**identity, "raw_sha256": file_sha(raw)}:
        recognized, _ = load_words(raw)
    else:
        recognized = faster_whisper_words(audio, "vi", model=model, device="cpu", compute_type="int8")
        save_words(raw, recognized, source="faster_whisper")
        write(metadata, {**identity, "raw_sha256": file_sha(raw)})
    audit = save_audit(folder, key, audio, text, recognized)
    import re

    from ..core.errors import ManualGateRequired
    from ..core.speech_edit import normalize

    expected = re.findall(r"\w+", text.casefold())[:2]
    actual = re.findall(r"\w+", normalize(" ".join(w.text for w in recognized)).casefold())[:2]
    audit["onset"] = {"expected": expected, "recognized": actual, "matched": expected == actual}
    write(folder / "work/speech_checks" / f"{key}.json", audit)
    if expected != actual:
        raise ManualGateRequired("speech_onset", "ASR chưa khớp cụm mở đầu; nghe và sửa/căn lại trước khi duyệt giọng.")
    words = map_onto_text(text, recognized, round(seconds * 1000), strict=True)
    path = folder / "subtitles" / f"{key}.words.json"
    save_words(path, words, source="faster_whisper")
    return str(path.resolve())


def prepare_voice(folder: Path):
    folder = folder.resolve()
    require(folder, "script")
    cfg = load_config()
    apply_social(folder, cfg)
    assert_social_config(cfg["tts"])
    if (folder / "vi.json").is_file():
        from .reddit import SEAM, H, W, chunks, voice_story
        from .reddit_edit import plan

        vi = read_json(folder / "vi.json")
        voiced = voice_story(vi["paragraphs"], cfg, vi.get("cast", {}), folder / "audio")
        timing_files = []
        for i, (sentence, (audio, seconds)) in enumerate(
            zip([s for g in chunks(vi["paragraphs"]) for s in g], voiced, strict=True)
        ):
            timing_files.append(align_clip(folder, f"reddit_{i:04d}", audio, seconds, sentence, cfg))
        from .reddit import voice_free
        from .reddit_edit import hook_texts, partition

        parts = partition(
            chunks(vi["paragraphs"]),
            voiced,
            float(cfg["reddit"].get("part_max_sec", 180)),
            vi=vi,
            target_seconds=float(cfg["reddit"].get("part_target_sec", 90)),
        )
        import random

        from . import bgclips

        for i, part in enumerate(parts, 1):
            seconds = sum(voiced[k + j][1] for group, k in part for j in range(len(group))) + 5.35
            bgclips.planned(
                folder,
                i,
                seconds,
                random.Random(folder.name + str(i)),
                aspect=W / (H - SEAM) if vi.get("scenes") else W / H,
                family=cfg["reddit"].get("background_family", "any"),
            )
        if len(parts) > 1 and cfg["reddit"].get("export_full", True):
            bgclips.planned(
                folder,
                0,
                sum(t for p, t in voiced),
                random.Random(folder.name + "full"),
                820 / 1080,
                family=cfg["reddit"].get("background_family", "horror"),
            )
        hooks = hook_texts(vi, parts)
        body = [{"path": str(p.resolve()), "seconds": t} for p, t in voiced]
        hook_assets = [
            voice_free(t, folder / "audio_hook", cfg, vi.get("cast", {}).get("narrator", "narrator_female"))
            if t
            else None
            for t in hooks
        ]
        extra = [asset for asset in hook_assets if asset]
        if any(t > 5 for p, t in extra):
            from ..core.errors import ManualGateRequired

            raise ManualGateRequired("reddit_hook", "Rút câu mở đầu còn tối đa năm giây trước khi duyệt giọng.")
        approved_hooks = [{"path": str(a[0].resolve()), "seconds": a[1]} if a else None for a in hook_assets]
        # Final body already contains the approved question; earlier Shorts repeat it once.
        question = vi.get("closing_question")
        closing = (
            voice_free(question, folder / "audio_ending", cfg, vi.get("cast", {}).get("narrator", "narrator_female"))
            if question and len(parts) > 1
            else None
        )
        endings = [
            {"path": str(closing[0].resolve()), "seconds": closing[1]} if closing and i < len(parts) - 1 else None
            for i in range(len(parts))
        ]
        ending_timings = (
            [align_clip(folder, "closing_question", closing[0], closing[1], question, cfg)] if closing else []
        )
        if closing:
            if closing[1] > 6:
                from ..core.errors import ManualGateRequired

                raise ManualGateRequired("reddit_ending", "Rút câu hỏi cuối còn tối đa sáu giây trước khi duyệt giọng.")
            extra.append(closing)
        write(
            folder / "part_plan.json",
            {
                "parts": plan(
                    chunks(vi["paragraphs"]),
                    voiced,
                    float(cfg["reddit"].get("part_max_sec", 180)),
                    vi=vi,
                    target_seconds=float(cfg["reddit"].get("part_target_sec", 90)),
                ),
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
            **(
                {
                    "body": body,
                    "hooks": approved_hooks,
                    "endings": endings,
                    "ending_timing_files": ending_timings,
                    "timing_files": timing_files,
                }
                if (folder / "vi.json").is_file()
                else {}
            ),
        },
    )
    if (folder / "vi.json").is_file():
        from .story_sound import prepare_plan

        prepare_plan(folder, cfg)
        from .story_scenes import prepare as prepare_scenes

        prepare_scenes(folder, vi)
        from .story_preview import prepare_previews

        prepare_previews(folder, cfg)
    return prepare(folder, "voice")
