"""Timeline renderer: per-scene video segments + narration track + captions -> output/final.mp4.

Steps (all intermediates in work/, inputs are never modified):
  1. background track for the whole timeline (gradient / color / looped asset video or image)
  2. one video segment per scene (clip | still Ken Burns | background slice) + optional overlay PNG.
     The background and every segment carry a `.key` file (hash of everything they are made from): an
     unchanged scene is reused instead of encoded again.
  3. concat segments (stream copy)
  4. narration: per-scene audio padded to the scene length, concatenated; optional music with ducking
  5. captions: ASS (word highlight) burned in, SRT sidecar
  6. final encode (audio loudness-normalised) to a temp file, sanity probe; the previous final moves to
     output/history/, then atomic rename to output/final.mp4
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageFilter

from ..core.cache import build_cached as _build_cached
from ..core.cache import cache_key
from ..core.config import load_yaml
from ..core.errors import StudioError, ValidationError
from ..core.ffmpeg import escape_filter_path, has_filter, run_ffmpeg
from ..core.logging_utils import get_logger
from ..core.media_probe import probe
from ..core.outputs import archive_previous
from ..core.paths import atomic_replace
from ..core.project import ProjectContext
from ..core.subtitles import build_ass, load_words, write_srt

log = get_logger()

GRADIENT_COLORS = ["0x0f0c29", "0x302b63", "0x24243e", "0x16213e"]
SEGMENT_REV = 2  # bump when background/segment rendering changes, so cached segments are rebuilt


def _file_sha(ctx: ProjectContext, path: Path) -> str | None:
    return ctx.hashes.sha(path) if path.is_file() else None


def _vcodec_args(ctx: ProjectContext, *, intermediate: bool) -> list[str]:
    s = ctx.settings
    if intermediate:
        return ["-c:v", "libx264", "-preset", str(s.get("render.intermediate_preset", "veryfast")),
                "-crf", str(s.get("render.intermediate_crf", 16)), "-pix_fmt", "yuv420p"]
    enc = s.get("render.encoder", "libx264")
    crf = str(s.get("render.crf", 20))
    if enc == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", crf, "-b:v", "0", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", str(s.get("render.preset", "medium")), "-crf", crf, "-pix_fmt", "yuv420p"]


def _fit_filter(w: int, h: int, mode: str) -> str:
    if mode == "pad":
        return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black")
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def _frames(ms: int, fps: int) -> int:
    return max(1, int(round(ms * fps / 1000)))


# ------------------------------------------------------------------ background


def render_background(ctx: ProjectContext, total_ms: int) -> tuple[Path, str]:
    """Background track for the whole timeline; returns (path, cache key)."""
    fmt = ctx.fmt
    w, h, fps = fmt.width, fmt.height, fmt.fps
    out = ctx.work / "background.mp4"
    n = _frames(total_ms, fps)
    dur = f"{total_ms / 1000:.3f}"
    bg = ctx.project.video.background
    fit = ctx.settings.get("render.fit_mode", "crop")
    src_sha = None
    if bg == "gradient":
        cols = ":".join(f"c{i}={c}" for i, c in enumerate(GRADIENT_COLORS))
        src = ["-f", "lavfi", "-i",
               f"gradients=s={w}x{h}:r={fps}:{cols}:nb_colors={len(GRADIENT_COLORS)}:speed=0.008:seed=7"]
        vf = "format=yuv420p,setsar=1"
    elif bg.startswith("color:"):
        color = bg.split(":", 1)[1].replace("#", "0x")
        src = ["-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}"]
        vf = "format=yuv420p,setsar=1"
    else:
        path = ctx.resolve(bg, what="background")
        src_sha = _file_sha(ctx, path)
        info = probe(path)
        is_image = path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") or info.duration < 0.1
        if is_image:
            src = ["-loop", "1", "-framerate", str(fps), "-i", str(path)]
        else:
            src = ["-stream_loop", "-1", "-i", str(path)]
        vf = f"{_fit_filter(w, h, fit)},fps={fps},setsar=1,format=yuv420p"
    inter = _vcodec_args(ctx, intermediate=True)
    key = cache_key("background", SEGMENT_REV, bg, src_sha, total_ms, w, h, fps, fit, GRADIENT_COLORS, inter)
    _build_cached(out, key, lambda: run_ffmpeg([*src, "-vf", vf, "-frames:v", str(n), "-t", dur, "-an",
                                                *inter, str(out)], stage="background"))
    return out, key


# ------------------------------------------------------------------ stills (Ken Burns)


def _prepare_still(src: Path, out: Path, w: int, h: int, mode: str, scale: float = 1.6) -> Path:
    """Cover-crop (or blurred-pad) the image to the output aspect at `scale`x size for smooth zoompan."""
    tw, th = int(w * scale), int(h * scale)
    with Image.open(src) as im:
        im = im.convert("RGB")
        if mode == "pad":
            bgimg = im.copy()
            r = max(tw / bgimg.width, th / bgimg.height)
            bgimg = bgimg.resize((int(bgimg.width * r) + 1, int(bgimg.height * r) + 1), Image.LANCZOS)
            left, top = (bgimg.width - tw) // 2, (bgimg.height - th) // 2
            bgimg = bgimg.crop((left, top, left + tw, top + th)).filter(ImageFilter.GaussianBlur(40))
            r = min(tw / im.width, th / im.height)
            fg = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
            bgimg.paste(fg, ((tw - fg.width) // 2, (th - fg.height) // 2))
            im = bgimg
        else:
            r = max(tw / im.width, th / im.height)
            im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
            left, top = (im.width - tw) // 2, (im.height - th) // 2
            im = im.crop((left, top, left + tw, top + th))
        im.save(out, quality=95)
    return out


def _ken_burns(effect: str, n: int) -> str:
    z_max = 0.12
    if effect == "zoom_out":
        z = f"{1 + z_max}-{z_max}*on/{n}"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif effect == "pan_left":
        z = "1.15"
        x, y = f"(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"
    elif effect == "pan_right":
        z = "1.15"
        x, y = f"(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"
    elif effect == "none":
        z, x, y = "1", "0", "0"
    else:  # zoom_in
        z = f"1+{z_max}*on/{n}"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1"


# ------------------------------------------------------------------ scene segments


def render_scene(ctx: ProjectContext, scene, start_ms: int, dur_ms: int, background: Path | None,
                 background_key: str | None = None, voice_ms: int | None = None) -> tuple[Path, bool]:
    """One scene segment; returns (path, reused-from-cache)."""
    fmt = ctx.fmt
    w, h, fps = fmt.width, fmt.height, fmt.fps
    n = _frames(dur_ms, fps)
    dur = f"{dur_ms / 1000:.3f}"
    v = scene.visual
    fit = v.fit_mode or ctx.settings.get("render.fit_mode", "crop")
    out = ctx.work / f"seg_{scene.scene_id}.mp4"
    inputs: list[str]
    shas: list[str | None] = []
    if v.type == "clip":
        path = ctx.resolve(v.path, what="clip")
        shas.append(_file_sha(ctx, path))
        info = probe(path, scene_id=scene.scene_id)
        if info.duration + 0.04 < dur_ms / 1000:
            log.warning("[render][%s] clip %.2fs < scene %.2fs -> freezing last frame", scene.scene_id,
                        info.duration, dur_ms / 1000)
        inputs = ["-i", str(path)]
        chain = f"{_fit_filter(w, h, fit)},fps={fps},tpad=stop_mode=clone:stop_duration={dur},trim=duration={dur}"
    elif v.type == "still":
        path = ctx.resolve(v.path, what="image")
        shas.append(_file_sha(ctx, path))
        prepared = ctx.work / f"still_{scene.scene_id}.jpg"
        inputs = ["-loop", "1", "-framerate", str(fps), "-i", str(prepared)]
        chain = f"{_ken_burns(v.ken_burns, n)}:s={w}x{h}:fps={fps}"
    elif v.type == "manim":
        from .manim_render import render_manim

        path, mkey = render_manim(ctx, scene, dur_ms, dur_ms if voice_ms is None else voice_ms)
        shas.append(mkey)
        inputs = ["-i", str(path)]
        chain = f"{_fit_filter(w, h, 'crop')},fps={fps},tpad=stop_mode=clone:stop_duration={dur},trim=duration={dur}"
    elif v.type == "color":
        color = (v.color or "#000000").replace("#", "0x")
        inputs = ["-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}"]
        chain = "null"
    else:  # background slice
        if background is None:
            raise StudioError("background track missing", code="render_error", scene_id=scene.scene_id)
        inputs = ["-ss", f"{start_ms / 1000:.3f}", "-i", str(background)]
        chain = "null"
        shas += [background_key, str(start_ms)]
    # JPEG stills (and some phone clips) are full range: convert to TV range so every segment is plain yuv420p
    chain += ",scale=out_range=tv,setsar=1,format=yuv420p"
    if v.overlay:
        ov = ctx.resolve(v.overlay, what="overlay")
        shas.append(_file_sha(ctx, ov))
        inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(ov)]
        until = v.overlay_until_sec
        enable = f":enable='lte(t,{until:.3f})'" if until else ""
        graph = f"[0:v]{chain}[base];[base][1:v]overlay=(W-w)/2:(H-h)/2:shortest=0{enable},format=yuv420p[v]"
        maps = ["-filter_complex", graph, "-map", "[v]"]
    else:
        maps = ["-vf", chain]
    inter = _vcodec_args(ctx, intermediate=True)
    key = cache_key("segment", SEGMENT_REV, v.model_dump(mode="json"), dur_ms, w, h, fps, fit, inter, shas)

    def build() -> None:
        if v.type == "still":
            _prepare_still(path, prepared, w, h, fit)
        run_ffmpeg([*inputs, *maps, "-frames:v", str(n), "-r", str(fps), "-an", *inter, str(out)],
                   stage="render", scene_id=scene.scene_id)

    return out, _build_cached(out, key, build)


def _concat_list(path: Path, files: list[Path]) -> Path:
    lines = []
    for f in files:
        rel = os.path.relpath(f, path.parent).replace("\\", "/").replace("'", r"'\''")
        lines.append(f"file '{rel}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------------ audio


def render_audio(ctx: ProjectContext, tl: dict) -> Path:
    sr = int(ctx.settings.get("render.audio_sample_rate", 48000))
    vol = ctx.project.audio.volume
    parts = []
    for sc in tl["scenes"]:
        dur = f"{sc['duration_ms'] / 1000:.3f}"
        out = ctx.work / f"aud_{sc['scene_id']}.wav"
        if sc.get("audio"):
            src = ["-i", str(ctx.dir / sc["audio"])]
            af = (f"aresample={sr},aformat=sample_fmts=s16:channel_layouts=stereo,volume={vol},"
                  f"apad=whole_dur={dur},atrim=duration={dur}")
        else:
            src = ["-f", "lavfi", "-t", dur, "-i", f"anullsrc=r={sr}:cl=stereo"]
            af = f"aformat=sample_fmts=s16:channel_layouts=stereo,atrim=duration={dur}"
        run_ffmpeg([*src, "-af", af, "-ar", str(sr), "-ac", "2", "-c:a", "pcm_s16le", str(out)],
                   stage="audio", scene_id=sc["scene_id"])
        parts.append(out)
    narration = ctx.work / "narration.wav"
    lst = _concat_list(ctx.work / "audio_concat.txt", parts)
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(narration)], stage="audio")

    music_ref = ctx.project.audio.background_music
    if not music_ref:
        return narration
    music = ctx.resolve(music_ref, what="music")
    total = f"{tl['total_ms'] / 1000:.3f}"
    fade_st = max(0.0, tl["total_ms"] / 1000 - 1.5)
    mdb = ctx.project.audio.music_volume_db
    if ctx.project.audio.ducking:
        graph = (f"[1:a]aresample={sr},aformat=channel_layouts=stereo,volume={mdb}dB,atrim=duration={total}[m];"
                 f"[0:a]asplit=2[n][sc];[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[md];"
                 f"[n][md]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={fade_st:.3f}:d=1.5,"
                 f"alimiter=limit=0.95[a]")
    else:
        graph = (f"[1:a]aresample={sr},aformat=channel_layouts=stereo,volume={mdb}dB,atrim=duration={total}[m];"
                 f"[0:a][m]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={fade_st:.3f}:d=1.5,"
                 f"alimiter=limit=0.95[a]")
    mixed = ctx.work / "audio_mix.wav"
    run_ffmpeg(["-i", str(narration), "-stream_loop", "-1", "-i", str(music), "-filter_complex", graph,
                "-map", "[a]", "-t", total, "-ar", str(sr), "-ac", "2", "-c:a", "pcm_s16le", str(mixed)],
               stage="audio")
    return mixed


# ------------------------------------------------------------------ captions


def caption_style(ctx: ProjectContext) -> dict:
    name = ctx.project.video.caption_style
    path = ctx.resolve(f"asset:shared/caption_styles/{name}.yaml", what="caption style")
    if not path.is_file():
        raise ValidationError(f"caption style '{name}' not found in {path.parent}", code="missing_style")
    return load_yaml(path)


def caption_box(fmt) -> dict:
    """Caption settings with margins pushed inside the safe zone (platform buttons / title bars)."""
    cap = dict(fmt.caption)
    safe = fmt.safe_zone or {}
    # one margin for both sides: centred captions (the larger safe side wins)
    side = max(int(cap.get("margin_h", 60)), int(safe.get("left", 0)), int(safe.get("right", 0)))
    cap["margin_l"] = cap["margin_r"] = side
    cap["margin_v"] = max(int(cap.get("margin_v", 200)), int(safe.get("bottom", 0)))
    return cap


def build_captions(ctx: ProjectContext, tl: dict) -> tuple[Path | None, Path | None]:
    words_file = ctx.work / "words.json"
    if ctx.project.video.subtitle_mode == "none" or not words_file.exists():
        return None, None
    words, _ = load_words(words_file)
    if not words:
        return None, None
    fmt = ctx.fmt
    ass_text, cues = build_ass(words, width=fmt.width, height=fmt.height, style=caption_style(ctx),
                               caption=caption_box(fmt))
    # never let a caption run past the end
    total = tl["total_ms"]
    cues = [c for c in cues if c.start_ms < total]
    for c in cues:
        c.end_ms = min(c.end_ms, total)
    ass = ctx.work / "captions.ass"
    ass.write_text(ass_text, encoding="utf-8")
    srt_tmp = ctx.work / "captions.srt"
    write_srt(srt_tmp, cues)
    return ass, srt_tmp


# ------------------------------------------------------------------ main


def render_project(ctx: ProjectContext, *, burn_subs: bool | None = None, allow_sidecar: bool = False) -> Path:
    tl = ctx.load_timeline()
    p = ctx.project
    if len(tl["scenes"]) != len(p.scenes):
        raise ValidationError("timeline is out of date (scene count changed) - re-run the voice stage",
                              code="stale_timeline")
    fmt = ctx.fmt
    total_ms = tl["total_ms"]
    log.info("[render] %s %dx%d@%d, %.2fs, %d scenes, encoder %s", fmt.name, fmt.width, fmt.height, fmt.fps,
             total_ms / 1000, len(p.scenes), ctx.settings.get("render.encoder", "libx264"))
    needs_bg = any(s.visual.type == "background" for s in p.scenes)
    background, bg_key = render_background(ctx, total_ms) if needs_bg else (None, None)

    segs, reused = [], 0
    for s, sc in zip(p.scenes, tl["scenes"], strict=True):
        seg, hit = render_scene(ctx, s, sc["start_ms"], sc["duration_ms"], background, bg_key, sc.get("voice_ms"))
        segs.append(seg)
        reused += hit
    if reused:
        log.info("[render] reused %d/%d unchanged scene segment(s)", reused, len(segs))
    video = ctx.work / "video_concat.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(_concat_list(ctx.work / "video_concat.txt", segs)),
                "-c", "copy", str(video)], stage="concat")

    audio = render_audio(ctx, tl)
    ass, srt = build_captions(ctx, tl)
    burn = (p.video.subtitle_mode == "burn_in") if burn_subs is None else burn_subs
    vf = ["setsar=1", "format=yuv420p"]
    if ass and burn:
        if not has_filter("ass"):
            if not allow_sidecar:
                raise StudioError("ffmpeg has no libass ('ass' filter) - cannot burn captions. Install a full "
                                  "FFmpeg build or pass --allow-sidecar-subs", code="no_libass")
            log.warning("[render] libass missing -> captions only as sidecar SRT")
        else:
            rel = os.path.relpath(ass, ctx.dir).replace("\\", "/")
            fonts = ctx.asset_dir("shared/fonts")
            opt = f"ass={escape_filter_path(rel)}"
            if fonts.is_dir() and any(fonts.iterdir()):
                try:
                    frel = os.path.relpath(fonts, ctx.dir).replace("\\", "/")
                except ValueError:  # different drive on Windows
                    frel = str(fonts)
                opt += f":fontsdir={escape_filter_path(frel)}"
            vf.insert(0, opt)

    out_dir = ctx.output
    tmp = out_dir / "final.tmp.mp4"
    tmp.unlink(missing_ok=True)
    sr = str(ctx.settings.get("render.audio_sample_rate", 48000))
    af = [f"aresample={sr}"]
    silent = not any(sc.get("audio") for sc in tl["scenes"]) and not p.audio.background_music
    if ctx.settings.get("render.loudnorm", True) and not silent:  # loudnorm turns pure silence into NaN
        target = float(ctx.settings.get("render.loudness_lufs", -14))
        tp = float(ctx.settings.get("render.true_peak_db", -1.5))
        af.insert(0, f"loudnorm=I={target:g}:TP={tp:g}:LRA=11")
    run_ffmpeg(["-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-vf", ",".join(vf),
                "-af", ",".join(af), "-r", str(fmt.fps), *_vcodec_args(ctx, intermediate=False),
                "-c:a", "aac", "-b:a", str(ctx.settings.get("render.audio_bitrate", "192k")), "-ar", sr, "-ac", "2",
                "-t", f"{total_ms / 1000:.3f}", "-movflags", "+faststart", str(tmp)],
               stage="final", cwd=ctx.dir)
    info = probe(tmp)
    if not (info.has_video and info.has_audio) or abs(info.duration - total_ms / 1000) > 0.5:
        tmp.unlink(missing_ok=True)
        raise StudioError(f"final render looks broken (duration {info.duration:.2f}s, video={info.has_video}, "
                          f"audio={info.has_audio}) - not published", code="render_broken")
    final = out_dir / "final.mp4"
    archive_previous(out_dir, int(ctx.settings.get("output.keep_history", 3)))
    atomic_replace(tmp, final)
    if srt:
        atomic_replace(srt, out_dir / "captions.srt")
    log.info("[render] wrote %s (%.2fs)", final, info.duration)
    return final
