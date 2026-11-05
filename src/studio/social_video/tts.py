"""Vietnamese narration (Vivibe / revidapi -> edge-tts -> gTTS), with word timings for subtitles."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import threading
import time
import unicodedata
from pathlib import Path

from .util import ROOT, ffmpeg, log, media_duration, run

TTS_CACHE = ROOT / "cache" / "tts"
_pcm_cache_lock = threading.Lock()

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF️‍]+")
URL_RE = re.compile(r"https?://\S+")
EMOTICON_RE = re.compile(r"[:;=]-?[)(DPp]+|(?<!\w)[xX]D+(?!\w)|\^\^|<3")

# Common Vietnamese chat shorthand, so comments read aloud naturally.
TEENCODE = {
    "ko": "không", "k": "không", "kh": "không", "hok": "không", "khum": "không",
    "dc": "được", "đc": "được", "vs": "với", "j": "gì", "z": "vậy", "r": "rồi",
    "ng": "người", "mn": "mọi người", "mng": "mọi người", "bth": "bình thường",
    "ms": "mới", "trc": "trước", "cx": "cũng", "cg": "cũng", "bt": "biết",
    "ntn": "như thế nào", "nma": "nhưng mà", "mk": "mình", "mik": "mình", "e": "em",
    "a": "anh", "tr": "trời", "vl": "vãi", "vcl": "vãi", "ib": "nhắn tin", "sp": "sản phẩm",
    "lm": "làm", "đt": "điện thoại", "dt": "điện thoại", "ok": "ô kê", "oke": "ô kê",
}
# Lowercase only (plus "Ko"-style capitals for 2+ letters): a capital "A!" in prose is an
# interjection, not shorthand for "anh".
_CODES = sorted(set(TEENCODE) | {k.capitalize() for k in TEENCODE if len(k) > 1}, key=len, reverse=True)
TOKEN_RE = re.compile(r"(?<![\w@])(" + "|".join(map(re.escape, _CODES)) + r")(?!\w)")


def clean_for_speech(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = URL_RE.sub("", text)
    text = EMOJI_RE.sub("", text)
    text = EMOTICON_RE.sub("", text)
    text = TOKEN_RE.sub(lambda m: TEENCODE[m.group(1).lower()], text)
    text = re.sub(r"[@#](?=\w)", "", text)
    from ..core.speech_edit import normalize
    return normalize(re.sub(r"\s+", " ", text).strip())


async def _synth(text: str, voice: str, rate: str, out: Path,
                 pitch: str = "+0Hz") -> list[dict]:
    import edge_tts

    words = []
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    with out.open("wb") as fh:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"start": round(start, 3),
                              "end": round(start + chunk["duration"] / 1e7, 3),
                              "text": chunk["text"]})
    return words


def _spread(tokens: list[str], start: float, end: float) -> list[dict]:
    """Estimated word timings: share [start, end] between words by character count."""
    weights = [len(t) + 2 for t in tokens]
    t, words = start, []
    for tok, wgt in zip(tokens, weights):
        span = (end - start) * wgt / sum(weights)
        words.append({"start": round(t, 3), "end": round(t + span, 3), "text": tok})
        t += span
    return words


def _gtts(text: str, out: Path) -> list[dict]:
    """Last-resort voice (Google Translate TTS), sped up to a natural pace."""
    from gtts import gTTS

    raw = out.with_suffix(".raw.mp3")
    gTTS(text, lang="vi").save(str(raw))
    run([ffmpeg(), "-y", "-hide_banner", "-i", str(raw), "-af", "atempo=1.5", str(out)])
    raw.unlink(missing_ok=True)
    return _spread(text.split(), 0.1, media_duration(out) - 0.05)


def _edge(text: str, voice: str, rate: str, out: Path, attempts: int,
          pitch: str = "+0Hz") -> list[dict]:
    for i in range(attempts):
        try:
            # a dropped connection can leave edge-tts waiting forever; give up and retry instead
            words = asyncio.run(asyncio.wait_for(_synth(text, voice, rate, out, pitch), 120))
            if out.exists() and out.stat().st_size > 0:
                return words
            raise RuntimeError("empty audio")
        except Exception as exc:
            if i == attempts - 1:
                raise
            log(f"  edge-tts lỗi ({exc.__class__.__name__}), thử lại…")
            time.sleep(2 * (i + 1))
    return []


VIVIBE_RPC = "https://api.lucylab.io/json-rpc"
_vivibe_lock = threading.Lock()
SRT_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)\s*\n(.+?)(?:\n\n|\Z)", re.S)


def _srt_cues(srt: str) -> list[tuple[float, float, str]]:
    cues = []
    for m in SRT_RE.finditer(srt.replace("\r", "")):
        g = [int(x) for x in m.groups()[:8]]
        cues.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
                     g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, m.group(9).strip()))
    return cues


def _vivibe(text: str, out: Path, vcfg: dict) -> list[dict]:
    """Vivibe (LucyLab) API: submit a job, poll until done, download WAV + SRT.

    The SRT only has sentence-level cues, so word timings are spread inside each cue.
    """
    import requests

    key = os.environ.get("VIVIBE_API_KEY") or vcfg.get("api_key")
    if not key or not vcfg.get("voice_id"):
        raise RuntimeError("chưa cấu hình api_key/voice_id")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {key}"

    def call(method: str, payload: dict) -> dict:
        resp = session.post(VIVIBE_RPC, json={"method": method, "input": payload}, timeout=60)
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(data["error"].get("message") or data["error"])
        return data["result"]

    # Vivibe runs one export per account at a time: callers queue on a lock, and a
    # "still in progress" answer (e.g. from another program) is waited out, not a failure.
    with _vivibe_lock:
        deadline = time.time() + 120
        while True:
            try:
                job = call("ttsLongText", {"text": text, "userVoiceId": vcfg["voice_id"],
                                           "speed": vcfg.get("speed", 1.0)})
                break
            except RuntimeError as exc:
                if "in progress" not in str(exc) or time.time() > deadline:
                    raise
                time.sleep(2)
        deadline = time.time() + 180
        while True:
            status = call("getExportStatus", {"projectExportId": job["projectExportId"]})
            if status["state"] == "completed" and status.get("url"):
                break
            if status["state"] == "failed" or time.time() > deadline:
                raise RuntimeError(f"job {status['state']}")
            time.sleep(1.0)
    wav = out.with_suffix(".vivibe.wav")
    wav.write_bytes(session.get(status["url"], timeout=120).content)
    run([ffmpeg(), "-y", "-hide_banner", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "160k",
         str(out)])
    wav.unlink(missing_ok=True)

    tokens = text.split()
    cues = _srt_cues(session.get(status["srtUrl"], timeout=60).text) if status.get("srtUrl") else []
    if not cues:
        return _spread(tokens, 0.05, media_duration(out) - 0.1)
    words, i = [], 0
    for k, (start, end, cue) in enumerate(cues):
        n = len(cue.split()) if k < len(cues) - 1 else len(tokens) - i
        words += _spread(tokens[i:i + n], start, end)
        i += n
    return words


REVID_API = "https://revidapi.com/v1/text-to-speech"


def _revid(text: str, out: Path, rcfg: dict) -> list[dict]:
    """revidapi.com: POST a job, poll until completed, download the mp3.

    No word timings come back, so they are spread over the clip by character count.
    """
    import requests

    key = os.environ.get("REVID_API_KEY") or rcfg.get("api_key")
    if not key:
        raise RuntimeError("chưa cấu hình api_key")
    session = requests.Session()
    session.headers["X-API-Key"] = key

    def check(resp):
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        if not resp.ok or data.get("error"):
            err = data.get("error")
            raise RuntimeError((err.get("message") if isinstance(err, dict) else err)
                               or f"HTTP {resp.status_code}")
        return data

    job = check(session.post(REVID_API, json={"voice_id": int(rcfg["voice_id"]), "text": text,
                                              "speed": rcfg.get("speed", 1.0)}, timeout=60))
    job_id = job.get("job_id") or (job.get("data") or {}).get("job_id")
    if not job_id:
        raise RuntimeError(f"không nhận được job_id: {str(job)[:200]}")
    deadline = time.time() + 600
    while True:
        status = check(session.get(f"{REVID_API}/{job_id}", timeout=60))
        state = status.get("status")
        if state == "completed":
            break
        if state in ("failed", "error", "cancelled") or time.time() > deadline:
            raise RuntimeError(f"job {state}: {str(status.get('error') or '')[:200]}")
        time.sleep(2)
    url = (status.get("result") or {}).get("audio_url")
    if not url:
        raise RuntimeError("job xong nhưng không có audio_url")
    raw = out.with_suffix(".revid.mp3")
    raw.write_bytes(session.get(url, timeout=180).content)
    run([ffmpeg(), "-y", "-hide_banner", "-i", str(raw), "-c:a", "libmp3lame", "-b:a", "160k",
         str(out)])
    raw.unlink(missing_ok=True)
    return _spread(text.split(), 0.05, media_duration(out) - 0.1)


def _cached(key: str, text: str, out: Path, make) -> list[dict]:
    """Reuse audio already generated for the same text/voice: re-renders cost no credits."""
    digest = hashlib.sha1(f"{key}|{text}".encode("utf-8")).hexdigest()[:20]
    audio, meta = TTS_CACHE / f"{digest}.mp3", TTS_CACHE / f"{digest}.json"
    if audio.exists() and meta.exists():
        shutil.copy(audio, out)
        return json.loads(meta.read_text(encoding="utf-8"))
    words = make()
    TTS_CACHE.mkdir(parents=True, exist_ok=True)
    shutil.copy(out, audio)
    meta.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return words


# An engine that fails is skipped for 10 minutes instead of being retried per clip.
_down_until: dict[str, float] = {}
ENGINE_NAMES = {"vivibe": "Vivibe", "revid": "revidapi", "edge": "edge-tts", "gtts": "gTTS", "omnivoice": "OmniVoice", "vieneu": "VieNeu"}
# engines that are called once per ~4000 characters and cut per sentence afterwards
BATCH_ENGINES = ("vivibe", "revid")


def synth(text: str, out: Path, tcfg: dict, attempts: int = 3) -> list[dict]:
    """Write an mp3 and return word timings, trying engines in `tts.engines` order, e.g.
    Vivibe (economy voice) -> revidapi (paid credits) -> edge-tts (free) -> gTTS (free)."""
    from ..core.voice_policy import assert_social_config
    assert_social_config(tcfg)
    text = clean_for_speech(text)
    if not text:
        return []
    # all engines down at once (edge hiccup + gTTS rate limit) would fail the whole story:
    # wait for the free engine that comes back first instead, a few times
    for _ in range(4):
        try:
            return _synth_once(text, out, tcfg, attempts)
        except RuntimeError as exc:
            free = [_down_until.get(e, 0) for e in tcfg["engines"] if e in ("edge", "gtts")]
            if str(exc) != NO_VOICE or not free:
                raise
            time.sleep(min(max(5.0, min(free) - time.time()), 660))
    return _synth_once(text, out, tcfg, attempts)


NO_VOICE = "không có giọng đọc nào dùng được"


def _synth_once(text: str, out: Path, tcfg: dict, attempts: int) -> list[dict]:
    for engine in tcfg["engines"]:
        if not engine_ready(engine, tcfg):
            continue
        # a paid engine gets one more try: a single hiccup should not switch voices mid-story
        for attempt in range(2 if engine == "vivibe" else 1):
            try:
                if engine == "omnivoice":
                    from dataclasses import replace
                    from ..core.voice_policy import social_profile
                    from ..providers.tts import get_provider
                    from ..voices import VoiceRegistry
                    profile, root = social_profile(tcfg)
                    speed = float(tcfg["omnivoice"].get("speed",1.0))
                    profile = replace(profile,params={**profile.params,"speed":speed})
                    provider = get_provider("omnivoice",VoiceRegistry(root,{profile.id:profile},{},{}))
                    def omni():
                        wav = out.with_suffix(".omnivoice.wav")
                        try:
                            provider.synthesize(text,profile,wav)
                            run([ffmpeg(),"-y","-v","error","-i",str(wav),str(out)])
                        finally:
                            wav.unlink(missing_ok=True)
                        return _spread(text.split(),0.0,media_duration(out))
                    return _cached("omnivoice|"+json.dumps(profile.params,sort_keys=True),text,out,omni)
                if engine == "vieneu":
                    from .local_voice import generate
                    from ..core.voice_policy import signature, social_profile
                    v = tcfg['vieneu']
                    identity = signature(social_profile(tcfg)[0])
                    def local():
                        out.parent.mkdir(parents=True, exist_ok=True)
                        wav = out.with_suffix('.local.wav')
                        try:
                            generate(text, wav, v)
                            run([ffmpeg(), '-y', '-v', 'error', '-i', str(wav), str(out)])
                        finally:
                            wav.unlink(missing_ok=True)
                        return _spread(text.split(), 0.0, media_duration(out))
                    return _cached('vieneu|native-pause-v2|' + identity + json.dumps(v, sort_keys=True), text, out, local)
                if engine == "vivibe":
                    v = tcfg["vivibe"]
                    return _cached(f"vivibe|{v['voice_id']}|{v.get('speed', 1.0)}", text, out,
                                   lambda: _vivibe(text, out, v))
                if engine == "revid":
                    r = tcfg["revid"]
                    return _cached(f"revid|{r['voice_id']}|{r.get('speed', 1.0)}", text, out,
                                   lambda: _revid(text, out, r))
                if engine == "edge":
                    pitch = tcfg.get("pitch", "+0Hz")
                    return _cached(f"edge|{tcfg['voice']}|{tcfg['rate']}|{pitch}", text, out,
                                   lambda: _edge(text, tcfg["voice"], tcfg["rate"], out, attempts,
                                                 pitch))
                if engine == "gtts":
                    return _gtts(text, out)
            except Exception as exc:
                msg = str(exc)
                quota = re.search(r"đợi (\d+) phút", msg)   # hourly export quota reached
                if (attempt == 0 and engine == "vivibe" and not quota and "API key" not in msg
                        and "credit" not in msg):
                    time.sleep(2)
                    continue
                # edge-tts drops out for seconds at a time; a long pause would fail whole stories
                wait = int(quota.group(1)) * 60 + 30 if quota else 30 if engine == "edge" else 600
                if time.time() >= _down_until.get(engine, 0):
                    log(f"  {ENGINE_NAMES.get(engine, engine)} không dùng được "
                        f"({exc.__class__.__name__}: {msg[:120]}), dùng giọng dự phòng "
                        f"trong {wait // 60} phút")
                _down_until[engine] = time.time() + wait
                if quota:   # remembered across runs, see vivibe_quota_wait()
                    QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
                    QUOTA_FILE.write_text(str(time.time() + wait))
                break
    raise RuntimeError(NO_VOICE)


QUOTA_FILE = ROOT / "cache" / "vivibe_quota_until.txt"


def vivibe_quota_wait() -> float:
    """Seconds until Vivibe's hourly export quota frees up (0 if it is not exhausted)."""
    try:
        return max(0.0, float(QUOTA_FILE.read_text()) - time.time())
    except (OSError, ValueError):
        return 0.0


def engine_ready(engine: str, tcfg: dict) -> bool:
    if engine == "vivibe" and vivibe_quota_wait() > 0:
        return False
    if engine in BATCH_ENGINES and not (os.environ.get(f"{engine.upper()}_API_KEY")
                                        or tcfg.get(engine, {}).get("api_key")):
        return False   # paid engine without a key: skip quietly
    return engine in tcfg["engines"] and time.time() >= _down_until.get(engine, 0)


def _silences(audio: Path) -> list[tuple[float, float]]:
    """(midpoint, length) of each pause in an audio file."""
    err = run([ffmpeg(), "-hide_banner", "-i", str(audio), "-af",
               "silencedetect=noise=-38dB:d=0.12", "-f", "null", "-"]).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return [((a + b) / 2, b - a) for a, b in zip(starts, ends)]


def tidy(src: Path, dst: Path, gap: float) -> None:
    """Convert to PCM and add boundary protection; never remove quiet consonants."""
    from ..core.audio_boundaries import protect_pcm
    tmp = dst.with_suffix('.boundary.wav')
    run([ffmpeg(), "-y", "-v", "error", "-i", str(src), "-ac", "2", "-ar", "48000", str(tmp)])
    protect_pcm(tmp, dst)
    tmp.unlink()


def cut_sentences(whole: Path, texts: list[str], wavs: list[Path], workdir: Path,
                  words: list[dict] | None = None, gap: float | None = None) -> None:
    """Cut one narration of `texts` (read in order) into one wav per sentence.

    Boundaries come from word timings when the engine gives them, else from each
    sentence's share of the characters; each is then moved to the nearest real pause,
    and the drift found there is carried forward to the following estimates.
    """
    total = media_duration(whole)
    counts = [len(t.split()) for t in texts]
    if words and len(words) == sum(counts):
        idx, bounds = 0, []
        for c in counts[:-1]:
            idx += c
            bounds.append(words[idx]["start"])
        window = 0.9
    else:
        chars, acc, bounds = [len(t) + 8 for t in texts], 0, []
        for c in chars[:-1]:
            acc += c
            bounds.append(total * acc / sum(chars))
        window = 3.0
    pauses = _silences(whole)
    cuts, last, drift = [], 0.0, 0.0
    for b in bounds:
        est = b + drift
        near = [(m, d) for m, d in pauses if est - window <= m <= est + window and m > last + 0.3]
        if near:   # prefer close and long pauses (sentence ends) over short comma breaths
            t = min(near, key=lambda md: abs(md[0] - est) - 1.5 * md[1])[0]
            drift = t - b
        else:
            t = max(est, last + 0.3)
        cuts.append(round(t, 3))
        last = t
    pattern = workdir / f"cut_{wavs[0].stem}_%04d.wav"
    run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(whole), "-f", "segment",
         "-segment_times", ",".join(f"{c:.3f}" for c in cuts) or "99999",
         "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(pattern)])
    pieces = sorted(workdir.glob(f"cut_{wavs[0].stem}_*.wav"))
    if len(pieces) != len(wavs):
        for piece in pieces:
            piece.unlink()
        raise RuntimeError(f"cắt được {len(pieces)}/{len(wavs)} câu")
    for piece, wav in zip(pieces, wavs):
        if gap is None:
            piece.replace(wav)
        else:
            tidy(piece, wav, gap)
            piece.unlink()


def _engine_batch(engine: str, texts: list[str], wavs: list[Path], workdir: Path,
                  tcfg: dict, gap: float) -> None:
    """Voice several sentences in ONE paid request, then cut it per sentence."""
    whole = workdir / f"batch_{engine}_{wavs[0].stem}.mp3"
    if engine == "vivibe":
        words = synth(" ".join(texts), whole, {**tcfg, "engines": ["vivibe"]})
    else:
        # one sentence per line: revidapi pauses at line breaks, which makes clean cuts
        r = tcfg["revid"]
        text = "\n".join(texts)
        _cached(f"revid|{r['voice_id']}|{r.get('speed', 1.0)}", text, whole,
                lambda: _revid(text, whole, r))
        words = None
    cut_sentences(whole, texts, wavs, workdir, words, gap)


def role_cfg(tcfg: dict, role: str) -> dict:
    """tcfg with the voices of one cast role (tts.cast): edge voice/pitch/rate, revidapi
    voice id, Vivibe voice id. A role without a Vivibe voice skips Vivibe."""
    spec = tcfg.get("cast", {}).get(role)
    out = dict(tcfg)
    if not spec:   # unknown role (e.g. plain "narrator" outside reddit mode): default voices
        return out
    if "edge" in spec:
        out["voice"], out["pitch"] = spec["edge"][0], spec["edge"][1]
        if len(spec["edge"]) > 2:
            out["rate"] = spec["edge"][2]
    if spec.get("revid"):
        out["revid"] = {**tcfg.get("revid", {}), "voice_id": spec["revid"]}
    if spec.get("vivibe"):
        out["vivibe"] = {**tcfg.get("vivibe", {}), "voice_id": spec["vivibe"]}
    elif tcfg.get("cast"):
        out["engines"] = [e for e in tcfg["engines"] if e != "vivibe"]
    return out


def voice_sentences(texts: list[str], workdir: Path, tcfg: dict, gap: float = 0.10,
                    roles: list[str] | None = None) -> list[tuple[Path, float]]:
    """One wav (48 kHz stereo) per text -> [(wav, seconds)].

    `roles` gives each text a cast role (narrator, male, child…), see role_cfg.
    Paid engines (Vivibe: ~50 exports an hour; revidapi: per-character credits) get
    ~4000 characters of one role per request, tried in `tts.engines` order; edge-tts/gTTS
    (the free fallbacks) voice whatever is left, text by text, in parallel.
    """
    from concurrent.futures import ThreadPoolExecutor
    from ..core.voice_policy import assert_social_config
    assert_social_config(tcfg)

    from ..core.voice_policy import signature as voice_signature, social_profile
    identity = voice_signature(social_profile(tcfg)[0])
    signature = hashlib.sha256(json.dumps(
        [texts, roles, tcfg, gap, identity, "protected-pcm-v4-sequential"],
        sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()[:16]
    workdir = workdir / signature
    workdir.mkdir(parents=True, exist_ok=True)
    texts = [clean_for_speech(t) or "…" for t in texts]
    roles = roles or ["narrator"] * len(texts)
    wavs = [workdir / f"{i:04d}.wav" for i in range(len(texts))]
    for role in dict.fromkeys(roles):
        _voice_paid([i for i, r in enumerate(roles) if r == role], texts, wavs, workdir,
                    role_cfg(tcfg, role), gap)

    def one(i: int) -> None:
        rcfg = role_cfg(tcfg, roles[i])
        free = {**rcfg, "engines": [e for e in rcfg["engines"] if e not in BATCH_ENGINES]}
        if wavs[i].exists() and free["engines"] != ["vieneu"]:
            return
        if free["engines"] == ["vieneu"]:
            from .local_voice import generate
            from ..core.audio_boundaries import protect_pcm
            key = hashlib.sha256(json.dumps([texts[i], free, identity, "protected-pcm-v4-sequential"],
                                           sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            cached = TTS_CACHE / "pcm" / (key + ".wav")
            meta = cached.with_suffix(".json")
            from .quality import sha256
            with _pcm_cache_lock:
                valid = cached.is_file() and meta.is_file()
                if valid:
                    try:
                        valid = json.loads(meta.read_text(encoding="utf-8")).get("sha256") == sha256(cached)
                    except (ValueError, OSError):
                        valid = False
                if valid:
                    shutil.copy2(cached, wavs[i])
                    return
                pcm = workdir / f"{i:04d}.native.wav"
                stereo = workdir / f"{i:04d}.stereo.wav"
                generate(texts[i], pcm, free["vieneu"])
                run([ffmpeg(), "-y", "-v", "error", "-i", str(pcm), "-ar", "48000", "-ac", "2", str(stereo)])
                protect_pcm(stereo, wavs[i])
                pcm.unlink()
                stereo.unlink()
                cached.parent.mkdir(parents=True, exist_ok=True)
                partial = cached.with_suffix(".partial.wav")
                shutil.copy2(wavs[i], partial)
                partial.replace(cached)
                meta.write_text(json.dumps({"sha256": sha256(cached), "key": key}), encoding="utf-8")
            return
        mp3 = workdir / f"{i:04d}.mp3"
        synth(texts[i], mp3, free)
        tidy(mp3, wavs[i], gap)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(one, range(len(texts))))
    return [(w, media_duration(w)) for w in wavs]


def _voice_paid(items: list[int], texts: list[str], wavs: list[Path], workdir: Path,
                tcfg: dict, gap: float) -> None:
    """Voice `items` (all one role) with the paid engines, ~4000 characters per request.
    The items need not be adjacent: each request is cut back into its own sentences."""
    for engine in [e for e in tcfg["engines"] if e in BATCH_ENGINES]:
        todo = [i for i in items if not wavs[i].exists()]
        quota_wait = engine == "vivibe" and tcfg.get("wait_quota") and vivibe_quota_wait() > 0
        if not todo or not (engine_ready(engine, tcfg) or quota_wait):
            continue
        batch: list[int] = []
        batches = []
        for i in todo:
            if batch and sum(len(texts[j]) for j in batch) + len(texts[i]) > 4000:
                batches.append(batch)
                batch = []
            batch.append(i)
        if batch:
            batches.append(batch)
        failed = False
        for b in batches:
            for _ in range(3):
                # tcfg["wait_quota"]: wait out Vivibe's hourly quota instead of mixing voices
                wait = vivibe_quota_wait() if engine == "vivibe" else 0
                if wait and tcfg.get("wait_quota"):
                    log(f"  Vivibe hết lượt xuất trong giờ, chờ {wait / 60:.0f} phút…")
                    time.sleep(wait)
                    _down_until.pop("vivibe", None)
                if not engine_ready(engine, tcfg):
                    failed = True
                    break
                try:
                    _engine_batch(engine, [texts[i] for i in b], [wavs[i] for i in b], workdir,
                                  tcfg, gap)
                    break
                except Exception as exc:
                    if engine == "vivibe" and vivibe_quota_wait() and tcfg.get("wait_quota"):
                        continue
                    _down_until[engine] = max(_down_until.get(engine, 0), time.time() + 600)
                    log(f"  {ENGINE_NAMES[engine]} lỗi khi đọc cụm câu ({exc}), "
                        "phần còn lại chuyển sang giọng tiếp theo")
                    failed = True
                    break
            if failed:
                break
