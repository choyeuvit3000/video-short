"""Voice stage: narration -> per-scene audio + word timings -> work/timeline.json."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from ..core.cache import Cache, cache_key
from ..core.cost import CostLedger
from ..core.errors import ProviderUnavailable, StudioError, ValidationError
from ..core.ffmpeg import run_ffmpeg
from ..core.logging_utils import get_logger
from ..core.media_probe import probe
from ..core.project import ProjectContext
from ..core.subtitles import (
    Word,
    chunks_to_cues,
    estimate_words,
    group_words,
    load_words,
    read_srt,
    save_words,
    write_srt,
)
from ..providers import align
from ..providers.tts import get_provider
from ..voices import VoiceProfile, VoiceRegistry, load_registry, with_speed

log = get_logger()


def _text_hash(text: str, profile: VoiceProfile, trim: bool = False) -> str:
    return hashlib.sha256(json.dumps([text, profile.id, profile.params, *(["trim"] if trim else [])],
                                     sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


SILENCE_DB = -45


def trim_silence(path: Path, *, scene_id: str | None = None, keep_lead_ms: int = 60, keep_tail_ms: int = 150) -> int:
    """Cut the silence before the first and after the last sound of a generated clip, in place (edge-tts adds
    ~0.2 s / ~0.75 s). Returns the milliseconds removed at the start, to shift word timings."""
    err = run_ffmpeg(["-i", str(path), "-af", f"silencedetect=n={SILENCE_DB}dB:d=0.05", "-f", "null", "-"],
                     stage="voice", scene_id=scene_id, loglevel="info")
    dur = probe(path).duration
    starts = [float(x) for x in re.findall(r"silence_start: (-?[0-9.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", err)]
    lead = ends[0] if starts and starts[0] <= 0.01 and ends else 0.0
    open_tail = starts and (len(ends) < len(starts) or ends[-1] >= dur - 0.02)
    tail = starts[-1] if open_tail and starts[-1] > lead else dur
    a = max(0.0, lead - keep_lead_ms / 1000)
    b = min(dur, tail + keep_tail_ms / 1000)
    if b - a < 0.2 or (a < 0.02 and dur - b < 0.02):
        return 0
    tmp = path.with_name(f"{path.stem}.trim{path.suffix}")
    run_ffmpeg(["-i", str(path), "-af", f"atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS", str(tmp)],
               stage="voice", scene_id=scene_id)
    tmp.replace(path)
    return int(round(a * 1000))


def choose_profile(ctx: ProjectContext, reg: VoiceRegistry) -> VoiceProfile:
    p = ctx.project
    prof = reg.get(p.audio.voice_profile) if p.audio.voice_profile else reg.default_for(p.language)
    if not prof.usable:
        raise ValidationError(f"Voice '{prof.id}' has status '{prof.status}' - enable it in {prof.source_file} "
                              "or pick another (`studio voices list`)", code="voice_disabled")
    from ..core.voice_policy import assert_voice_allowed
    assert_voice_allowed(prof,reg.root)
    if prof.lang != p.language:
        log.warning("voice %s is %s but project language is %s", prof.id, prof.lang, p.language)
    return prof


def _words_for(ctx: ProjectContext, text: str, audio: Path, duration_ms: int, provider_words: list[Word] | None,
               warnings: list[str], scene_id: str) -> tuple[list[Word], str]:
    chain = ctx.settings.get("providers.align", ["provider_words", "faster_whisper", "estimate"])
    for step in chain:
        if step == "provider_words" and provider_words:
            return align.map_onto_text(text, provider_words, duration_ms), "provider"
        if step == "faster_whisper":
            try:
                rec = align.faster_whisper_words(
                    audio, ctx.project.language,
                    model=ctx.settings.get("align.faster_whisper_model", "small"),
                    device=ctx.settings.get("align.device", "auto"),
                    compute_type=ctx.settings.get("align.compute_type", "auto"),
                )
                return align.map_onto_text(text, rec, duration_ms), "faster_whisper"
            except ProviderUnavailable as e:
                log.info("[voice][%s] alignment skipped: %s", scene_id, e)
        if step == "estimate":
            warnings.append(f"{scene_id}: caption timing is ESTIMATED (no word timings) - review sync")
            return estimate_words(text, duration_ms), "estimate"
    return estimate_words(text, duration_ms), "estimate"


def _synthesize_all(ctx: ProjectContext, reg: VoiceRegistry, prof: VoiceProfile, ledger: CostLedger,
                    overwrite: bool) -> dict[str, tuple[Path, list[Word] | None]]:
    node = prof.location[len("node:"):] if prof.location.startswith("node:") else None
    if node and node != ctx.settings.get("worker.node_id"):
        raise ProviderUnavailable(f"voice {prof.id} runs only on node '{node}' - use `studio run --node {node}`",
                                  code="tts_wrong_node")
    prof = with_speed(prof, ctx.project.audio.speed)  # also for a fallback voice
    provider = get_provider(prof.provider, reg)
    reason = provider.check(prof)
    if reason:
        raise ProviderUnavailable(f"voice {prof.id}: {reason}", code="tts_unavailable")
    cache = Cache(ctx.settings.path("cache"), "tts")
    trim = ctx.project.audio.trim_silence
    results: dict[str, tuple[Path, list[Word] | None]] = {}
    audio_dir = ctx.dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    for s in ctx.project.scenes:
        text = s.narration.strip()
        if not text:
            continue
        out = audio_dir / f"{s.scene_id}{provider.extension}"
        meta = audio_dir / f"{s.scene_id}.tts.json"
        h = _text_hash(text, prof, trim)
        if s.audio_path and not overwrite:
            existing = ctx.resolve(s.audio_path)
            same = meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get("hash") == h
            if existing.is_file() and (same or not meta.exists()):
                # not generated by us (manual) or unchanged -> keep it
                cached_words = None
                wp = ctx.dir / "subtitles" / f"{s.scene_id}.provider_words.json"
                if same and wp.exists():
                    cached_words = load_words(wp)[0]
                results[s.scene_id] = (existing, cached_words)
                continue
        key = cache_key("tts", prof.provider, prof.params, text)
        hit = cache.get_files(key, ["audio" + provider.extension])
        words: list[Word] | None = None
        if hit:
            shutil.copy2(hit[0], out)
            wj = cache.get_json(key)
            words = [Word(**w) for w in wj["words"]] if wj and wj.get("words") else None
            log.info("[voice][%s] cache hit (%s)", s.scene_id, prof.id)
        else:
            cost = prof.estimate_cost(text)
            ledger.ensure(cost, f"TTS {prof.id} for {s.scene_id}")
            log.info("[voice][%s] synthesizing %d chars with %s", s.scene_id, len(text), prof.id)
            res = provider.synthesize(text, prof, out)
            words = res.words
            if res.cost_usd > 0:
                ledger.record(stage="voice", provider=prof.id, usd=res.cost_usd, detail=f"{len(text)} chars",
                              scene_id=s.scene_id)
            cache.put_files(key, {"audio" + provider.extension: out})
            cache.put_json(key, {"words": [w.__dict__ for w in words] if words else None})
        if trim:  # the cache keeps the untrimmed take; trim the project copy
            cut = trim_silence(out, scene_id=s.scene_id)
            if cut and words:
                words = [Word(w.text, max(0, w.start_ms - cut), max(0, w.end_ms - cut)) for w in words]
        meta.write_text(json.dumps({"hash": h, "voice": prof.id}, ensure_ascii=False), encoding="utf-8")
        if words:
            save_words(ctx.dir / "subtitles" / f"{s.scene_id}.provider_words.json", words, source="provider")
        s.audio_path = out.relative_to(ctx.dir).as_posix()
        results[s.scene_id] = (out, words)
    return results


def run_voice(ctx: ProjectContext, *, overwrite: bool = False) -> dict:
    p = ctx.project
    reg = load_registry(ctx.settings)
    ledger = CostLedger(ctx.dir, p.budget.max_cost_usd)
    warnings: list[str] = []

    if p.audio.source == "manual":
        prof_id = "manual"
        audio = {s.scene_id: (ctx.resolve(s.audio_path), None) for s in p.scenes if s.audio_path}
    else:
        prof = choose_profile(ctx, reg)
        tried: list[str] = []
        while True:
            try:
                audio = _synthesize_all(ctx, reg, prof, ledger, overwrite)
                break
            except ProviderUnavailable as e:
                tried.append(prof.id)
                fb = reg.fallback_for(prof)
                if not fb or fb.id in tried or not fb.usable:
                    raise StudioError(f"No usable voice. Tried {tried}. Last error: {e}", code="tts_failed") from e
                log.warning("voice %s unavailable (%s) -> switching WHOLE project to %s", prof.id, e, fb.id)
                warnings.append(f"voice fell back from {prof.id} to {fb.id}: {e}")
                prof = fb
                overwrite = True  # regenerate every scene with the fallback voice, never mix voices
        prof_id = prof.id

    tail = float(ctx.settings.get("timing.scene_tail_pad_sec", 0.25))
    min_scene = float(ctx.settings.get("timing.min_scene_sec", 1.5))
    tol_ms = int(ctx.settings.get("timing.voice_overflow_tolerance_ms", 200))
    fmt = ctx.fmt
    cap = fmt.caption
    scenes_tl = []
    all_words: list[Word] = []
    overflow: list[str] = []
    cursor = 0
    for s in p.scenes:
        text = s.narration.strip()
        voice_ms = 0
        words: list[Word] = []
        timing_src = None
        entry = audio.get(s.scene_id)
        if entry:
            apath, pwords = entry
            voice_ms = int(probe(apath).duration * 1000)
            if s.subtitle_path:  # manual SRT supplied: trust it, take word times from cues
                cues = read_srt(ctx.resolve(s.subtitle_path))
                for c in cues:
                    words += [Word(w.text, w.start_ms + c.start_ms, w.end_ms + c.start_ms)
                              for w in estimate_words(c.text, c.end_ms - c.start_ms)]
                timing_src = "manual_srt"
            elif text:
                words, timing_src = _words_for(ctx, text, apath, voice_ms, pwords, warnings, s.scene_id)
        elif text and p.audio.source == "manual":
            raise ValidationError("narration present but no audio file", code="missing_audio", scene_id=s.scene_id)

        if p.timing_mode == "fixed":
            dur_ms = int(round(s.duration_sec * 1000))
            if voice_ms > dur_ms + tol_ms:
                overflow.append(f"{s.scene_id}: voice {voice_ms / 1000:.2f}s > scene {dur_ms / 1000:.2f}s")
        else:
            dur_ms = max(voice_ms + int(tail * 1000), int(min_scene * 1000))
            if s.duration_sec:
                dur_ms = max(dur_ms, int(round(s.duration_sec * 1000)))
        # frame-align so video/audio durations agree exactly
        frame = 1000 / fmt.fps
        dur_ms = int(round(round(dur_ms / frame) * frame))

        if words:
            sw = s.scene_id
            save_words(ctx.dir / "subtitles" / f"{sw}.words.json", words, source=timing_src or "unknown")
            cues = chunks_to_cues(group_words(words, max_words=int(cap.get("max_words", 3)),
                                              max_chars=int(cap.get("max_chars", 18))))
            write_srt(ctx.dir / "subtitles" / f"{sw}.srt", cues)
            all_words += [Word(w.text, w.start_ms + cursor, min(w.end_ms, dur_ms) + cursor) for w in words]
        scenes_tl.append({
            "scene_id": s.scene_id,
            "start_ms": cursor,
            "duration_ms": dur_ms,
            "voice_ms": voice_ms,
            "audio": entry[0].relative_to(ctx.dir).as_posix() if entry else None,
            "timing_source": timing_src,
        })
        cursor += dur_ms

    if overflow:
        raise ValidationError(
            "Voice longer than scene (fixed timing) - shorten narration or raise duration_sec:\n  "
            + "\n  ".join(overflow), code="voice_too_long")
    if cursor / 1000 > fmt.max_duration_sec:
        warnings.append(f"total {cursor / 1000:.1f}s exceeds {fmt.max_duration_sec:.0f}s for {fmt.name}")

    save_words(ctx.work / "words.json", all_words, source="timeline")
    tl = {"format": fmt.name, "voice_profile": prof_id, "total_ms": cursor, "scenes": scenes_tl,
          "warnings": warnings}
    ctx.timeline_path().write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    ctx.save()
    for w in warnings:
        log.warning(w)
    log.info("[voice] timeline %.2fs, %d scenes, voice=%s", cursor / 1000, len(scenes_tl), prof_id)
    return tl
