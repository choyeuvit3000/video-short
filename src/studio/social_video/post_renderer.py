"""Post/media/comment rendering primitives for the approved merged layout."""
import random
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from .render import SegmentRenderer, concat, meme_image
from . import subs
from .util import ASSETS, MEMES, ffmpeg, has_audio, media_duration, run
CARD_W = 940
LEAD, TAIL = .25, .5
SCROLL_PX_PER_SEC = 240
REACTION_W = 900
def comments_of(post):
    return post.get('comments', [])
def _backgrounds() -> list[Path]:
    clips = sorted(p for p in (ASSETS / 'bgclips' / 'prepared').glob('*.mp4')
                   if not p.name.endswith('.partial.mp4'))
    if clips:
        return clips
    return sorted(p for p in (ASSETS / "backgrounds").glob("*")
                  if p.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"})


class StoryRenderer:
    def __init__(self, cfg: dict, workdir: Path, lib: dict, post: dict, tag: str):
        self.cfg, self.dir, self.post, self.tag = cfg, workdir, post, tag
        self.seg = SegmentRenderer(cfg, workdir, lib)  # TTS + font copy
        self.items = self.seg.items
        self.W, self.H, self.fps = self.seg.W, self.seg.H, self.seg.fps
        self.subs = cfg["story"]["subtitles"]
        self.top = 250
        self.bottom = 380 if self.subs else 200
        self.bg_video = None
        bgs = sorted((ASSETS / "backgrounds").glob("minecraft*.mp4")) if cfg["story"]["background"] == "minecraft" else _backgrounds()
        if cfg["story"]["background"] == "minecraft" and not bgs:
            raise ValueError("No imported Minecraft background is available")
        if cfg["story"]["background"] != "blur" and bgs:
            self.bg_video = random.choice(bgs)
            self.bg_len = max(media_duration(self.bg_video), 1.0)
            self.bg_t = random.uniform(0, max(0.0, self.bg_len - 90))
        else:
            self.bg_still = self._blur_background()

    def _blur_background(self) -> str:
        images = [m["file"] for m in self.post.get("media", []) if m["kind"] == "image"]
        src = self.dir / (images[0] if images else self.post["parts"][0])
        with Image.open(src) as im:
            im = im.convert("RGB")
            scale = max(self.W / im.width, self.H / im.height)
            im = im.resize((round(im.width * scale) + 1, round(im.height * scale) + 1))
            left, top = (im.width - self.W) // 2, (im.height - self.H) // 2
            im = im.crop((left, top, left + self.W, top + self.H))
            im = im.filter(ImageFilter.GaussianBlur(40))
            im = Image.eval(im, lambda v: int(v * 0.55))
        out = f"{self.tag}_bg.png"
        im.save(self.dir / out)
        return out

    # -- graph helpers
    def _background(self, inputs: list, dur: float, dim: bool = False) -> str:
        n = len([a for a in inputs if a == "-i"])
        if self.bg_video:
            start = self.bg_t % max(self.bg_len - dur, 0.01)
            inputs += ["-ss", f"{start:.2f}", "-stream_loop", "-1", "-i", str(self.bg_video)]
            chain = (f"[{n}:v]scale={self.W}:{self.H}:force_original_aspect_ratio=increase,"
                     f"crop={self.W}:{self.H},setsar=1,fps={self.fps},trim=duration={dur},"
                     "setpts=PTS-STARTPTS")
            self.bg_t += dur
        else:
            inputs += ["-loop", "1", "-framerate", str(self.fps), "-t", str(dur),
                       "-i", self.bg_still]
            chain = f"[{n}:v]setsar=1"
        return chain + (",eq=brightness=-0.3" if dim else "") + "[bg]"

    @staticmethod
    def _n(inputs: list) -> int:
        return len([a for a in inputs if a == "-i"])

    def _card(self, image: str, trim: bool) -> tuple[str, int, int]:
        """Rounded-corner copy of a screenshot card -> (file, width, height) in the frame.

        Short comments leave the right of the card empty, so it is cropped away and
        the card enlarged (up to 1.8x) to make the text readable on a phone.
        """
        with Image.open(self.dir / image) as im:
            im = im.convert("RGB")
            if trim:
                bg = im.getpixel((im.width - 6, im.height - 6))
                mask = ImageChops.difference(im, Image.new("RGB", im.size, bg)).convert("L")
                mask = mask.point(lambda v: 255 if v > 28 else 0)
                # ignore the "..." menu in the top-right corner and the separator lines
                draw = ImageDraw.Draw(mask)
                draw.rectangle([im.width - 160, 0, im.width, 130], fill=0)
                draw.rectangle([0, 0, im.width, 5], fill=0)
                draw.rectangle([0, im.height - 6, im.width, im.height], fill=0)
                box = mask.getbbox()
                if box:
                    im = im.crop((0, 4, min(im.width, box[2] + 48), im.height))
            width = min(CARD_W, round(im.width * 1.8)) if trim else CARD_W
            rounded = Image.new("L", im.size, 0)
            ImageDraw.Draw(rounded).rounded_rectangle([0, 0, im.width - 1, im.height - 1],
                                                      radius=36, fill=255)
            im.putalpha(rounded)
            out = f"{Path(image).stem}_card.png"
            im.save(self.dir / out)
            return out, width, round(im.height * width / im.width)

    def _card_height(self, image: str, width: int) -> int:
        with Image.open(self.dir / image) as im:
            return round(im.height * width / im.width)

    def render_beat(self,k,beat,hook):
        import json,hashlib
        from ..core.creative_brief import _sha
        from ..core.voice_policy import assert_social_config
        if beat.get("narration"):assert_social_config(self.cfg["tts"])
        refs=[]
        kind=beat["kind"];ref=beat["ref"]
        if kind=="post":refs.append(self.dir/self.post["parts"][ref])
        elif kind=="media":refs.append(self.dir/self.post["media"][ref]["file"])
        elif kind=="comment":refs.append(self.dir/self.post["comments"][ref]["image"])
        for name in ("image_id","sound_id"):
            if beat.get(name):refs.append(MEMES/self.items[beat[name]]["file"])
        if self.bg_video:refs.append(self.bg_video)
        else:refs.append(self.dir/self.bg_still)
        hashes=[(str(p),_sha(p)) for p in refs]
        fingerprint=hashlib.sha256(json.dumps([beat,hook,self.cfg,hashes],sort_keys=True).encode()).hexdigest()
        output=self.dir/f"{self.tag}_b{k:02d}.mp4";key_file=output.with_suffix(".cache.json")
        if output.is_file() and key_file.is_file():
            cached=json.loads(key_file.read_text())
            if cached.get("key")==fingerprint and cached.get("sha256")==_sha(output):return output
        result=self._render_beat(k,beat,hook)
        key_file.write_text(json.dumps({"key":fingerprint,"sha256":_sha(result)}),encoding="utf-8")
        return result

    def _render_beat(self, k: int, beat: dict, hook: str) -> Path:
        name = f"{self.tag}_b{k:02d}"
        kind = beat["kind"]
        voice, words, voice_dur = self.seg.narrate(beat["narration"], name)
        inputs: list = []
        filters: list[str] = []
        audio: list[tuple[int, float, float, float]] = []  # (input, delay, max len, volume)
        area = self.H - self.top - self.bottom
        media = self.post["media"][beat["ref"]] if kind == "media" else None
        dur = max(voice_dur + LEAD + TAIL, 1.8)

        if kind == "reaction":
            snd = self.items.get(beat["sound_id"])
            meme = self.items[beat["image_id"]]
            src = MEMES / meme["file"]
            if meme["kind"] == "video":
                snd_len = min(media_duration(src), 4.5)
            else:
                snd_len = media_duration(MEMES / snd["file"]) if snd else 0.0
            dur = round(min(max(snd_len + 0.2, 1.6), 4.7 if meme["kind"] == "video" else 3.2), 2)
            filters.append(self._background(inputs, dur, dim=True))
            n = self._n(inputs)
            if meme["kind"] == "video":
                inputs += ["-t", f"{snd_len:.2f}", "-i", str(src)]
                if has_audio(src):
                    audio.append((n, 0.0, snd_len, 1.0))
            elif src.suffix.lower() == ".gif":
                inputs += ["-ignore_loop", "0", "-t", str(dur), "-i", str(src)]
            else:
                img = meme_image(src, beat["caption_top"], beat["caption_bottom"],
                                 self.dir / f"{name}_meme.png", self.cfg["fonts"]["title"],
                                 width=REACTION_W)
                inputs += ["-loop", "1", "-framerate", str(self.fps), "-t", str(dur),
                           "-i", img.name]
            # punch-in: starts 25% larger and settles within 0.15s
            filters += [
                f"[{n}:v]scale=w='min({REACTION_W},iw*{self.H - 500}/ih)':h=-2,setsar=1,"
                f"scale=w='2*trunc(iw*(1+0.25*max(0,1-t/0.15))/2)':h=-2:eval=frame,"
                f"fps={self.fps}[fg]",
                "[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2:eval=frame:eof_action=pass[v0]",
            ]
            if snd:
                n = self._n(inputs)
                inputs += ["-i", str(MEMES / snd["file"])]
                audio.append((n, 0.0, dur, 0.85))
        elif kind == "media" and media["kind"] == "video":
            src = self.dir / media["file"]
            clip = min(media_duration(src), self.cfg["story"]["video_clip_sec"])
            dur = round(max(clip, dur), 2)
            filters.append(self._background(inputs, dur))
            n = self._n(inputs)
            inputs += ["-t", f"{clip:.2f}", "-i", media["file"]]
            filters += [
                f"[{n}:v]scale=w={self.W}:h={self.H - 2 * self.top}:"
                f"force_original_aspect_ratio=decrease,setsar=1,fps={self.fps}[fg]",
                "[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2:eof_action=pass[v0]",
            ]
            if has_audio(src):
                audio.append((n, 0.0, clip, 0.35 if voice else 1.0))
        elif kind == "media":
            dur = max(dur, 2.6)
            h = self._card_height(media["file"], CARD_W)
            if h > area * 1.15:   # tall screenshot: reveal top-down, then scroll
                dur = max(dur, (h - area) / SCROLL_PX_PER_SEC + 3.0)
                filters.append(self._background(inputs, dur))
                filters[-1] = filters[-1].replace("[bg]", ",split=2[bg][bgm]")
                n = self._n(inputs)
                inputs += ["-loop", "1", "-framerate", str(self.fps), "-t", str(dur),
                           "-i", media["file"]]
                shown = min(h, area * 0.35)
                p = f"({shown}+{h - shown}*clip((t-0.3)/{max(dur - 1.3, 0.5)},0,1))"
                line = f"({self.top}+min({p},{area}))"
                filters += [
                    f"[{n}:v]scale={CARD_W}:-2,setsar=1[fg]",
                    f"[bg][fg]overlay=x=(W-w)/2:y='{self.top}-max(0,{p}-{area})':eval=frame[vr]",
                    # hide everything below the reveal line with the background itself
                    f"[bgm]pad={self.W}:{2 * self.H}:0:0,crop={self.W}:{self.H}:0:'{line}'[mask]",
                    f"[vr][mask]overlay=x=0:y='{line}':eval=frame[v0]",
                ]
            else:
                filters.append(self._background(inputs, dur))
                n = self._n(inputs)
                inputs += ["-loop", "1", "-framerate", str(self.fps), "-t", str(dur),
                           "-i", media["file"]]
                with Image.open(self.dir / media["file"]) as im:
                    fit = min(self.W / im.width, (self.H - 2 * self.top) / im.height)
                    fw = 2 * round(im.width * fit / 2)
                filters += [
                    f"[{n}:v]scale={fw}:-2,setsar=1,"
                    f"scale=w='2*trunc({fw}*(1+0.06*t/{dur})/2)':h=-2:eval=frame[fg]",
                    "[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2:eval=frame[v0]",
                ]
        else:   # post / comment card
            dur = max(dur, 3.5 if kind == "post" else 2.2)
            src = (self.post["parts"][beat["ref"]] if kind == "post"
                   else comments_of(self.post)[beat["ref"]]["image"])
            image, cw, h = self._card(src, trim=kind == "comment")
            overflow = max(0, h - area)
            if overflow:
                dur = max(dur, overflow / SCROLL_PX_PER_SEC + 2.5)
            filters.append(self._background(inputs, dur))
            n = self._n(inputs)
            inputs += ["-loop", "1", "-framerate", str(self.fps), "-t", str(dur), "-i", image]
            y = (f"{self.top}-{overflow}*clip((t-1)/{max(dur - 2.5, 0.1)},0,1)" if overflow
                 else str(self.top + (area - h) // 2))
            if kind == "post":   # slide in from the right
                x = "(W-w)/2+W*pow(max(0,1-t/0.35),2)"
                filters.append(f"[{n}:v]scale={cw}:-2,setsar=1[fg]")
            else:                # fade + rise
                x = "(W-w)/2"
                y = f"{y}+50*max(0,1-t/0.2)"
                filters.append(f"[{n}:v]scale={cw}:-2,setsar=1,format=rgba,"
                               "fade=in:st=0:d=0.2:alpha=1[fg]")
            filters.append(f"[bg][fg]overlay=x='{x}':y='{y}':eval=frame[v0]")

        dur = round(min(dur, self.cfg["video"]["max_segment_sec"]), 2)
        last = "v0"
        if hook:
            (self.dir / f"{name}_hook.txt").write_text(hook, encoding="utf-8")
            filters.append(
                f"[{last}]drawtext=fontfile=title.ttf:textfile={name}_hook.txt:fontsize=58:"
                "fontcolor=black:box=1:boxcolor=white@0.95:boxborderw=22:"
                f"x=(w-text_w)/2:y=120:enable='lt(t,3.5)'[vh]")
            last = "vh"
        mark = self.cfg["story"]["watermark"]
        if mark:
            (self.dir / "watermark.txt").write_text(mark, encoding="utf-8")
            filters.append(f"[{last}]drawtext=fontfile=title.ttf:textfile=watermark.txt:"
                           "fontsize=34:fontcolor=white@0.8:borderw=3:bordercolor=black@0.6:"
                           f"x=40:y=40[vw]")
            last = "vw"
        if self.subs and words:
            subs.write_ass(words, LEAD, self.dir / f"{name}.ass", self.W, self.H,
                           self.cfg["fonts"]["subtitle_name"], margin_v=150)
            filters.append(f"[{last}]subtitles={name}.ass[vs]")
            last = "vs"
        filters.append(f"[{last}]fps={self.fps},format=yuv420p[vout]")

        if beat["sound_id"] and kind != "reaction":
            n = self._n(inputs)
            inputs += ["-i", str(MEMES / self.items[beat["sound_id"]]["file"])]
            audio.append((n, 0.05, min(2.5, dur), 0.75))
        mix = [f"anullsrc=r=48000:cl=stereo,atrim=0:{dur}[sil]"]
        labels = ["[sil]"]
        if voice:
            n = self._n(inputs)
            inputs += ["-i", voice.name]
            audio.append((n, LEAD, dur, 1.0))
        for j, (idx, delay, max_len, vol) in enumerate(audio):
            mix.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
                       f"atrim=0:{max_len:.2f},afade=out:st={max(0, max_len - 0.3):.2f}:d=0.3,"
                       f"volume={vol},adelay={int(delay * 1000)}:all=1[a{j}]")
            labels.append(f"[a{j}]")
        mix.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first[aout]")

        script = self.dir / f"{name}_filter.txt"
        script.write_text(";\n".join(filters + mix), encoding="utf-8")
        out = self.dir / f"{name}.mp4"
        run([ffmpeg(), "-y", "-hide_banner", *inputs, "-/filter_complex", script.name,
             "-map", "[vout]", "-map", "[aout]", "-t", str(dur),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", out.name],
            cwd=self.dir)
        return out
