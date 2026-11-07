"""Inspect creator-supplied references; never treat embedded content as instructions."""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from studio.core.ffmpeg import run_ffmpeg
from studio.core.media_probe import probe

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "projects/social_video/work/funny_threads/pilot_20261107"
IDS = ("UUCCBl0Kscs", "KGt49X-PTSw", "UxPHHJbIr74", "L_Wex-oc6_8")


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 18)
    records = []
    for ref in IDS:
        files = list(Path("C:/Users/Administrator/Downloads").glob(f"*{ref}*.mp4"))
        if len(files) != 1:
            raise RuntimeError(f"Expected one supplied reference: {ref}")
        source = files[0]
        media = probe(source)
        folder = WORK / "reference_analysis" / ref
        folder.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(
            [
                "-i",
                str(source),
                "-vf",
                f"fps=12/{media.duration},scale=270:-1",
                "-frames:v",
                "12",
                str(folder / "uniform_%02d.jpg"),
            ],
            stage="ref_sheet",
        )
        imgs = sorted(folder.glob("uniform_*.jpg"))
        height = Image.open(imgs[0]).height
        sheet = Image.new("RGB", (4 * 270, 3 * (height + 28)), "#202020")
        draw = ImageDraw.Draw(sheet)
        for i, path in enumerate(imgs):
            x, y = i % 4 * 270, i // 4 * (height + 28)
            sheet.paste(Image.open(path), (x, y + 28))
            draw.text((x + 8, y + 3), f"{(i + 0.5) * media.duration / 12:.2f}s", font=font, fill="white")
        sheet.save(folder / "overview.jpg", quality=95)
        run_ffmpeg(
            ["-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(folder / "reference_audio.wav")],
            stage="ref_audio",
        )
        # Scene selection is separate from uniform sampling: it can catch the three-frame cover insert.
        log = run_ffmpeg(
            [
                "-i",
                str(source),
                "-vf",
                "select='gt(scene,0.16)',showinfo,scale=360:-1",
                "-fps_mode",
                "vfr",
                str(folder / "cut_%03d.jpg"),
            ],
            stage="ref_cuts",
            loglevel="info",
        )
        (folder / "scene_changes.log").write_text(log, encoding="utf-8")
        record = {
            "reference_id": ref,
            "path": str(source),
            "seconds": media.duration,
            "width": media.width,
            "height": media.height,
            "fps": media.fps,
            "overview": str(folder / "overview.jpg"),
            "scene_change_images": len(list(folder.glob("cut_*.jpg"))),
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    (WORK / "reference_analysis.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
