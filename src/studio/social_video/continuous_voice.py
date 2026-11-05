"""Align complete utterances, then partition PCM without changing a single speech sample."""

import difflib
import re
import unicodedata
import wave
from pathlib import Path

import numpy as np

from ..core.errors import ManualGateRequired
from ..core.speech_checks import audit_numbers, file_sha, save_audit, text_sha
from ..core.speech_edit import normalize
from ..core.subtitles import Word, save_words
from ..core.user_review import digest
from ..core.voice_policy import signature, social_profile
from ..providers.align import map_onto_text
from .util import read_json, write_json


def _tokens(text):
    return re.findall(r"\w+", normalize(text).casefold())


def _without_tone(text):
    return "".join(c for c in unicodedata.normalize("NFD", text) if c not in "\u0300\u0301\u0303\u0309\u0323")


def split_source(folder, audio, raw_path, recognized, texts, first_index, model, output):
    """The ASR unit is the synthesized episode. Sentence files reconstruct its exact PCM."""
    text = " ".join(texts)
    with wave.open(str(audio), "rb") as stream:
        params = stream.getparams()
        if params.sampwidth != 2 or params.framerate != 48000 or params.nchannels not in (1, 2):
            raise ValueError("Continuous voice requires native 48 kHz PCM s16 mono/stereo")
        samples = np.frombuffer(stream.readframes(params.nframes), dtype="<i2").reshape(-1, params.nchannels)
    if params.nchannels == 1:
        samples = np.repeat(samples, 2, axis=1)
    duration = len(samples) * 1000 / params.framerate
    expected, actual = _tokens(text), _tokens(" ".join(w.text for w in recognized))
    expected_onset, actual_onset = expected[:2], actual[:2]
    tone_ambiguous = expected_onset != actual_onset
    if tone_ambiguous and (
        audit_numbers(text, recognized)["checks"]
        or [_without_tone(t) for t in expected_onset] != [_without_tone(t) for t in actual_onset]
    ):
        raise ManualGateRequired("continuous_onset", "Đầu bản thu thiếu/đổi từ; sửa trước khi dựng.")
    aligned = map_onto_text(text, recognized, round(duration), strict=True)
    matcher = difflib.SequenceMatcher(a=expected, b=actual, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks()) / max(1, len(expected))
    if len(actual) > len(expected) * 1.1:
        raise ManualGateRequired("continuous_speech", "Bản thu có lời thừa; không tự bỏ khỏi phụ đề.")
    count = [len(s.split()) for s in texts]
    if sum(count) != len(aligned):
        raise ValueError("Approved sentence coverage differs from the continuous narration")
    ends = np.cumsum(count).tolist()
    cuts = [0] + [round((aligned[n - 1].end_ms + aligned[n].start_ms) * params.framerate / 2000) for n in ends[:-1]]
    cuts.append(len(samples))
    if any(b <= a for a, b in zip(cuts, cuts[1:], strict=False)):
        raise ValueError("Invalid PCM partition; never cut away or duplicate a word")
    output.mkdir(parents=True, exist_ok=True)
    body, timing_files, raw_parts, footprints = [], [], [], []
    cursor = 0
    for local, sentence in enumerate(texts):
        index = first_index + local
        start, end = cuts[local : local + 2]
        clip = output / f"s{index:04d}.wav"
        with wave.open(str(clip), "wb") as stream:
            stream.setnchannels(2)
            stream.setsampwidth(2)
            stream.setframerate(params.framerate)
            stream.writeframes(samples[start:end].tobytes())
        offset_ms = start * 1000 / params.framerate
        seconds = (end - start) / params.framerate
        limit = round(seconds * 1000)
        words = [
            Word(w.text, max(0, round(w.start_ms - offset_ms)), min(limit, round(w.end_ms - offset_ms)))
            for w in aligned[cursor : cursor + count[local]]
        ]
        if any(w.end_ms <= w.start_ms for w in words):
            raise ValueError("Non-positive source speech anchor")
        raw = [
            Word(w.text, max(0, round(w.start_ms - offset_ms)), min(limit, round(w.end_ms - offset_ms)))
            for w in recognized
            if offset_ms <= (w.start_ms + w.end_ms) / 2 < end * 1000 / params.framerate
        ]
        timing = folder / "subtitles" / f"reddit_{index:04d}.words.json"
        save_words(timing, words, source="faster_whisper")
        report = save_audit(
            folder, f"reddit_{index:04d}", clip, sentence, raw, source="faster_whisper_continuous_episode"
        )
        report.update(
            alignment_unit="complete episode",
            asr_text_matches_are_not_listening_approval=True,
            expected_text=sentence,
            source_audio_sha256=file_sha(audio),
            source_raw_sha256=file_sha(raw_path),
            pcm_samples_removed=0,
            pcm_samples_inserted=0,
        )
        write_json(folder / "work/speech_checks" / f"reddit_{index:04d}.json", report)
        body.append({"path": str(clip.resolve()), "seconds": seconds, "sha256": file_sha(clip)})
        timing_files.append(str(timing.resolve()))
        raw_parts.append(raw)
        footprints.append(
            {"start_frame": start, "end_frame": end, "audio_sha256": file_sha(clip), "timing_sha256": file_sha(timing)}
        )
        cursor += count[local]
    report = {
        "source_audio": str(audio.resolve()),
        "source_sha256": file_sha(audio),
        "raw_words": str(raw_path.resolve()),
        "raw_sha256": file_sha(raw_path),
        "recognizer_model": model,
        "text_sha256": text_sha(text),
        "matched_fraction": round(matched, 4),
        "onset": {
            "expected": expected_onset,
            "raw": actual_onset,
            "literal_match": not tone_ambiguous,
            "tone_ambiguity_requires_final_listening": tone_ambiguous,
        },
        "word_disagreements": [
            {"expected": expected[a:b], "raw": actual[c:d]}
            for tag, a, b, c, d in matcher.get_opcodes()
            if tag != "equal"
        ],
        "samples_removed": 0,
        "samples_inserted": 0,
        "tempo_applied_here": False,
        "source_frames": len(samples),
        "partition_frames": sum(b - a for a, b in zip(cuts, cuts[1:], strict=False)),
        "parts": footprints,
        "human_listening": False,
    }
    return body, timing_files, raw_parts, report


def cached_timings(folder, texts, cfg):
    path = folder / "continuous_voice.json"
    if not path.is_file():
        return None
    data = read_json(path)
    profile, _ = social_profile(cfg["tts"])
    identity = digest({"tts": cfg["tts"], "speed": cfg["reddit"].get("narration_speed", 1.0)})
    if (
        data.get("texts") != digest(texts)
        or data.get("voice_signature") != signature(profile)
        or data.get("choices") != identity
    ):
        raise ManualGateRequired("continuous_voice", "Cấu hình lời đọc liền mạch đã đổi; không dùng cache giọng cũ.")
    for item in data["files"]:
        file = Path(item["path"])
        if not file.is_file() or file_sha(file) != item["sha256"]:
            raise ManualGateRequired("continuous_voice", "Bản tiếng/mốc nguồn đã đổi; chuẩn bị lại gói duyệt.")
    if len(data["timing_files"]) != len(texts):
        raise ValueError("Continuous timing coverage is incomplete")
    return data["timing_files"]
