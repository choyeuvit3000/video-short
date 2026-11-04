"""Package completed voice auditions as an offline comparison page, reel and ZIP."""

import argparse
import hashlib
import json
import math
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from studio.core.ffmpeg import run_ffmpeg
from studio.core.media_probe import probe


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def font(size, bold=False):
    return ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf", size)


def wrap(text, draw, face, width):
    lines, current = [], ""
    for word in text.split():
        candidate = (current + " " + word).strip()
        if current and draw.textlength(candidate, font=face) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + ([current] if current else [])


def card(out, item, text, count):
    image = Image.new("RGB", (1080, 1920), "#EDF3F4")
    draw = ImageDraw.Draw(image)
    ink, muted, accent = "#153039", "#52686F", "#086A77"
    draw.text((80, 88), "Phòng nghe", font=font(44, True), fill=ink)
    draw.line((80, 185, 1000, 185), fill="#B7CCCF", width=2)
    draw.text((80, 270), f"Mẫu {item['index']:02d} / {count}", font=font(36), fill=muted)
    size = 120
    while draw.textlength(item["name"], font=font(size, True)) > 920:
        size -= 2
    draw.text((76, 345), item["name"], font=font(size, True), fill=ink)
    gender = "Nam" if item["gender"] == "male" else "Nữ"
    draw.text((80, 528), gender + ", miền " + item["region"], font=font(42), fill=muted)
    style = item["description"].split("·")[-1].strip()
    draw.text((80, 596), style, font=font(36), fill=muted)
    wave = out / "cards" / f"{item['index']:02d}_wave.png"
    run_ffmpeg(
        [
            "-i",
            str(out / item["file"]),
            "-filter_complex",
            "showwavespic=s=920x130:colors=0x086A77",
            "-frames:v",
            "1",
            str(wave),
        ],
        stage="audition",
    )
    waveform = Image.open(wave).convert("RGBA")
    image.paste(waveform, (80, 728), waveform)
    draw.text((80, 937), "Cùng một đoạn đọc", font=font(32, True), fill=accent)
    face = font(37)
    for i, line in enumerate(wrap(text, draw, face, 920)):
        draw.text((80, 1007 + i * 57), line, font=face, fill=ink)
    draw.line((80, 1740, 1000, 1740), fill="#B7CCCF", width=2)
    draw.text((80, 1792), "Nghe chữ “phẩy” và nhịp nghỉ giữa câu.", font=font(31), fill=muted)
    path = out / "cards" / f"{item['index']:02d}.png"
    image.save(path)
    return path


def build(out):
    out = out.resolve()
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["status"] == "SAMPLES_READY" and not data["failures"]
    assert len(data["voices"]) == 24
    for item in data["voices"]:
        item["profile"].pop("source_file", None)
    (out / "manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    template = Path(__file__).with_name("voice_gallery.html").read_text(encoding="utf-8")
    public = {
        "text": data["text"],
        "voices": [
            {k: v[k] for k in ("index", "name", "gender", "region", "description", "aliases", "file")}
            for v in data["voices"]
        ],
    }
    (out / "index.html").write_text(
        template.replace("__VOICE_DATA__", json.dumps(public, ensure_ascii=False).replace("</", "<\\/")),
        encoding="utf-8",
    )
    key = hashlib.sha256(
        json.dumps([[v["name"], v["sha256"], v["description"]] for v in data["voices"]], ensure_ascii=False).encode()
        + b"gallery-layout-v1"
    ).hexdigest()
    movie = out / "all_voices.mp4"
    cache = out / "movie.json"
    old = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    if not (movie.is_file() and old.get("input") == key and old.get("sha256") == sha(movie)):
        clips, chapters, elapsed = [], [], 0.0
        for item in data["voices"]:
            poster = card(out, item, data["text"], len(data["voices"]))
            clip = out / "cards" / f"{item['index']:02d}.mp4"
            duration = math.ceil((item["duration"] + 0.28) * 30) / 30
            args = [
                "-loop",
                "1",
                "-framerate",
                "30",
                "-i",
                str(poster),
                "-i",
                str(out / item["file"]),
                "-af",
                "apad",
                "-t",
                str(duration),
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                "-c:v",
                "h264_nvenc",
                "-cq",
                "24",
                "-preset",
                "p4",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(clip),
            ]
            run_ffmpeg(args, stage="audition")
            clips.append(clip)
            chapters.append({"seconds": round(elapsed, 3), "name": item["name"], "index": item["index"]})
            elapsed += probe(clip).duration
            print("PACKAGED", item["index"], item["name"], flush=True)
        listing = out / "cards/concat.txt"
        listing.write_text("".join(f"file '{p.name}'\n" for p in clips), encoding="utf-8")
        run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(movie)],
            stage="audition",
        )
        cache.write_text(
            json.dumps({"input": key, "sha256": sha(movie), "chapters": chapters}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        chapters = old["chapters"]
    lines = [
        "# Các mẫu giọng",
        "",
        "Nghe từng mẫu trong index.html; hoặc xem all_voices.mp4. Chỉ áp dụng giọng sau khi người dùng chọn.",
        "",
    ]
    for item, chapter in zip(data["voices"], chapters, strict=True):
        seconds = int(chapter["seconds"])
        lines.append(
            f"- {seconds // 60:02d}:{seconds % 60:02d} — {item['index']:02d}. "
            f"{item['name']}: {item['description']} — {item['duration']:.1f} giây"
        )
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    archive = out.parent / "vieneu_24_samples.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("index.html", "manifest.json", "script.txt", "README.md", "all_voices.mp4"):
            if name == "index.html":
                standalone = (
                    (out / name)
                    .read_text(encoding="utf-8")
                    .replace('<a href="../vieneu_24_samples.zip" download>Tải toàn bộ mẫu</a>', "")
                )
                z.writestr(name, standalone)
            else:
                z.write(out / name, name)
        for path in (out / "samples").glob("*"):
            z.write(path, path.relative_to(out).as_posix())
    sheet = Image.new("RGB", (648, 1728), "#EDF3F4")
    for i, item in enumerate(data["voices"]):
        pic = Image.open(out / "cards" / f"{item['index']:02d}.png").resize((162, 288))
        sheet.paste(pic, ((i % 4) * 162, (i // 4) * 288))
    sheet.save(out / "contact_sheet.jpg")
    print(
        json.dumps(
            {
                "page": str(out / "index.html"),
                "movie": str(movie),
                "zip": str(archive),
                "seconds": probe(movie).duration,
                "count": len(data["voices"]),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    build(parser.parse_args().folder)
