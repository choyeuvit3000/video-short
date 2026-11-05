"""Bounded same-voice onset repair. Real ASR verifies both the cut and the final take."""

import re
import wave

import numpy as np

from ..core.audio_boundaries import protect_pcm
from ..core.ffmpeg import run_ffmpeg
from ..core.speech_checks import file_sha, text_sha
from ..core.speech_edit import normalize
from ..core.subtitles import Word, save_words
from ..core.user_review import digest
from ..core.voice_policy import assert_social_config, signature, social_profile
from ..providers.align import faster_whisper_words, map_onto_text
from .local_voice import generate
from .speech_spelling import SOUTHERN_PROFILES, for_alignment
from .util import media_duration, read_json, write_json

CARRIERS = ("Tôi kể lại chuyện này.", "Sau đây là lời kể.")


def quiet_boundary(source, recognized, idx):
    """ASR may assign the preceding pause to a word; refine only from real PCM silence."""
    with wave.open(str(source), "rb") as stream:
        rate = stream.getframerate()
        channels = stream.getnchannels()
        if stream.getsampwidth() != 2:
            return None
        pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").reshape(-1, channels)
    a = max(0, recognized[idx - 1].start_ms, recognized[idx].start_ms - 200)
    b = recognized[idx].end_ms - 40
    lo, hi = round(a * rate / 1000), min(len(pcm), round(b * rate / 1000))
    if hi <= lo:
        return None
    quiet = np.max(np.abs(pcm[lo:hi].astype(np.int32)), axis=1) <= 32768 * 10 ** (-50 / 20)
    edges = np.diff(np.r_[False, quiet, False].astype(np.int8))
    spans = [
        (s + lo, e + lo)
        for s, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True)
        if e - s >= rate * 0.15
    ]
    if not spans:
        return None
    left, right = max(spans, key=lambda pair: pair[1] - pair[0])
    return {"start": left / rate, "end": right / rate, "crop": max(left, right - round(rate * 0.15)) / rate}


def _tokens(text):
    return re.findall(r"\w+", normalize(text).casefold())


def validate(text, words, seconds, *, southern=False):
    words, _ambiguities = for_alignment(text, words, southern=southern)
    if len(_tokens(" ".join(w.text for w in words))) > len(_tokens(text)) * 1.1:
        raise ValueError("Unexpected extra speech; do not accept another take leaking into the clip")
    if _tokens(text)[:2] != _tokens(" ".join(w.text for w in words))[:2]:
        raise ValueError("Onset mismatch; do not hide a missing word with corrected subtitles")
    return map_onto_text(text, words, round(seconds * 1000), strict=True)


def record_recognition(folder, key, audio, text, model, words, *, provenance=(), device="cpu", compute_type="int8"):
    """Bind independently recognized words to the exact clip and any context source."""
    path = folder / "subtitles" / f"{key}.raw.words.json"
    save_words(path, words, source="faster_whisper")
    write_json(
        path.with_suffix(".cache.json"),
        {
            "audio": file_sha(audio),
            "text": text_sha(text),
            "model": model,
            "version": 1,
            "raw_sha256": file_sha(path),
            "recognition_source": "faster_whisper_with_provenance" if provenance else "faster_whisper",
            "recognizer_runtime": {"device": device, "compute_type": compute_type},
            "provenance": [{"path": str(p.resolve()), "sha256": file_sha(p)} for p in provenance],
        },
    )


def repair_clip(
    text, cfg, work, *, model="large-v3-turbo", max_attempts=2, device="cpu", compute_type="int8", spoken_text=None
):
    """Temporary spoken context is removed at a checked silent gap, never from final words."""
    assert_social_config({"engines": ["vieneu"], "vieneu": cfg})
    profile, _ = social_profile({"engines": ["vieneu"], "vieneu": cfg})
    southern = getattr(profile, "id", None) in SOUTHERN_PROFILES
    spoken_text = spoken_text or text
    if _tokens(spoken_text) != _tokens(text):
        raise ValueError("Pronunciation punctuation may not change approved words")
    work.mkdir(parents=True, exist_ok=True)
    failures = []
    for attempt, carrier in enumerate(CARRIERS[: max(0, min(2, max_attempts))], 1):
        prefix = work / f"take{attempt}"
        source = prefix.with_suffix(".source.wav")
        recipe = digest({"text": carrier + " " + spoken_text, "voice": signature(profile), "runtime": "sequential-v4"})
        source_meta = prefix.with_suffix(".source.json")
        cached = read_json(source_meta, {})
        if not source.is_file() or cached.get("recipe") != recipe or cached.get("sha256") != file_sha(source):
            generate(carrier + " " + spoken_text, source, {**cfg, "speed": 1.0})
            write_json(source_meta, {"recipe": recipe, "sha256": file_sha(source)})
        recognized = faster_whisper_words(source, "vi", model=model, device=device, compute_type=compute_type)
        raw_path = prefix.with_suffix(".source.words.json")
        save_words(raw_path, recognized, source="faster_whisper")
        expanded = [(token, i) for i, word in enumerate(recognized) for token in _tokens(word.text)]
        needle = _tokens(text)[:2]
        starts = [
            expanded[i][1]
            for i in range(len(expanded) - len(needle) + 1)
            if [x[0] for x in expanded[i : i + len(needle)]] == needle
        ]
        try:
            if not starts:
                raise ValueError("No exact target onset in the generated context")
            idx = starts[-1]
            # Retain 120 ms before the recognizer's onset, with no preceding word leaking in.
            start = max(0, recognized[idx].start_ms - 120) / 1000
            if idx == 0:
                raise ValueError("No preceding context boundary")
            clear_gap = start >= recognized[idx - 1].end_ms / 1000
            physical_gap = quiet_boundary(source, recognized, idx)
            if physical_gap:
                start = physical_gap["crop"]
                clear_gap = True
            crop = prefix.with_suffix(".crop.wav")
            with wave.open(str(source), "rb") as stream:
                params = stream.getparams()
                stream.setpos(round(start * params.framerate))
                pcm = stream.readframes(stream.getnframes() - stream.tell())
            with wave.open(str(crop), "wb") as stream:
                stream.setparams(params)
                stream.writeframes(pcm)
            paced = prefix.with_suffix(".paced.wav")
            output = prefix.with_suffix(".candidate.wav")
            speed = float(cfg.get("speed", 1.25))
            run_ffmpeg(
                [
                    "-i",
                    str(crop),
                    "-af",
                    f"atempo={speed}",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-c:a",
                    "pcm_s16le",
                    str(paced),
                ],
                stage="voice-onset-repair",
            )
            protection = protect_pcm(paced, output)
            final_words = faster_whisper_words(output, "vi", model=model, device=device, compute_type=compute_type)
            seconds = media_duration(output)
            final_raw = prefix.with_suffix(".final.words.json")
            save_words(final_raw, final_words, source="faster_whisper")
            recognition_source = "standalone_final_audio"
            standalone_error = None
            try:
                validate(text, final_words, seconds, southern=southern)
            except Exception as exc:
                standalone_error = str(exc)
            if standalone_error:
                if not clear_gap:
                    raise ValueError("No safe gap for context-only verification; standalone recognition must pass")
                from ..core.speech_checks import audit_numbers

                if any(c["evidence"] == "MISSING_MARKER" for c in audit_numbers(text, final_words)["checks"]):
                    raise ValueError("Final recognition misses a critical numeric marker")
                checked_words, _ = for_alignment(text, final_words, southern=southern)
                if physical_gap and _tokens(text)[:1] != _tokens(" ".join(w.text for w in checked_words))[:1]:
                    raise ValueError("PCM-refined cut needs independently recognized final onset")
                # A short crop can lose ASR context even when all samples remain.
                # Reuse genuine recognition of the uncropped take, with an exact
                # time transform. Never substitute expected script tokens.
                shift = protection["lead_added_ms"]
                final_words = [
                    Word(
                        w.text,
                        round(
                            (
                                (
                                    max(w.start_ms, physical_gap["end"] * 1000)
                                    if physical_gap and w is recognized[idx]
                                    else max(start * 1000, w.start_ms)
                                )
                                - start * 1000
                            )
                            / speed
                            + shift
                        ),
                        round((w.end_ms - start * 1000) / speed + shift),
                    )
                    for w in recognized[idx:]
                ]
                validate(text, final_words, seconds, southern=southern)
                recognition_source = "recognized_source_crop_tempo_transform"
            evidence = {
                "status": "AUTOMATIC_CHECK_PASSED_CREATOR_LISTENING_PENDING",
                "attempt": attempt,
                "voice_signature": signature(profile),
                "text_sha256": text_sha(text),
                "synthesis_text": spoken_text,
                "carrier": carrier,
                "source_sha256": file_sha(source),
                "crop_start_seconds": start,
                "recognizer_clear_gap": clear_gap,
                "pcm_quiet_gap": physical_gap,
                "speed_applied_once": speed,
                "raw_transcript": " ".join(w.text for w in final_words),
                "recognizer": {"model": model, "device": device, "compute_type": compute_type},
                "recognition_source": recognition_source,
                "standalone_error": standalone_error,
                "provenance": [str(source.resolve()), str(raw_path.resolve()), str(final_raw.resolve())],
                "boundary_protection": protection,
                "dialect_spelling_ambiguities": for_alignment(text, final_words, southern=southern)[1],
                "output_sha256": file_sha(output),
                "creator_approved": False,
                "failures": failures,
            }
            write_json(work / "repair_evidence.json", evidence)
            return output, final_words, evidence
        except Exception as exc:
            failures.append({"attempt": attempt, "error": str(exc), "raw": " ".join(w.text for w in recognized)})
    write_json(
        work / "repair_evidence.json", {"status": "REVIEW_REQUIRED", "creator_approved": False, "failures": failures}
    )
    raise ValueError("Bounded voice repair did not pass; keep the clip flagged for creator review")
