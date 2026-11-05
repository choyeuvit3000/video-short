"""Compact source cards: three lines, stable geometry, real speech-anchored emphasis."""

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
X, Y, WIDTH, PAD = 76, 326, 928, 42
FONT = "C:/Windows/Fonts/segoeui.ttf"


def layout(words, font, width=WIDTH - 2 * PAD, max_lines=3):
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pages, lines, line = [], [], []
    for i, _word in enumerate(words):
        if line and draw.textlength(" ".join(words[k] for k in line + [i]), font=font) > width:
            lines.append(line)
            line = []
            if len(lines) == max_lines:
                pages.append(lines)
                lines = []
        line.append(i)
    if line:
        lines.append(line)
    if lines:
        pages.append(lines)
    return pages


def _icons(draw, y):
    ink = (164, 170, 177, 255)
    # Decorative interaction glyphs, deliberately no fabricated engagement counts.
    draw.line(
        [
            (X + PAD + 1, y + 8),
            (X + PAD + 1, y + 1),
            (X + PAD + 8, y - 4),
            (X + PAD + 15, y + 1),
            (X + PAD + 22, y - 4),
            (X + PAD + 29, y + 1),
            (X + PAD + 29, y + 8),
            (X + PAD + 15, y + 23),
            (X + PAD + 1, y + 8),
        ],
        fill=ink,
        width=3,
    )
    draw.rounded_rectangle((X + PAD + 66, y - 3, X + PAD + 95, y + 20), radius=9, outline=ink, width=3)
    draw.line((X + PAD + 70, y + 18, X + PAD + 66, y + 26, X + PAD + 79, y + 20), fill=ink, width=3)
    draw.line((X + PAD + 133, y + 3, X + PAD + 156, y + 3, X + PAD + 156, y + 17), fill=ink, width=3)
    draw.line((X + PAD + 133, y + 3, X + PAD + 140, y - 4), fill=ink, width=3)
    draw.line((X + PAD + 153, y + 23, X + PAD + 130, y + 23, X + PAD + 130, y + 10), fill=ink, width=3)


def draw_card(story, texts, lines, active):
    font = ImageFont.truetype(FONT, 56)
    meta = ImageFont.truetype(FONT, 27)
    bold = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 33)
    height = 145 + 76 * len(lines) + 76
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((X, Y + 12, X + WIDTH, Y + height + 12), radius=40, fill=(0, 0, 0, 145))
    image = shadow.filter(ImageFilter.GaussianBlur(20))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle(
        (X, Y, X + WIDTH, Y + height), radius=40, fill=(17, 20, 23, 246), outline=(255, 255, 255, 31), width=2
    )
    preview = story.get("development_preview", False)
    from .story_source import labels

    platform, author = labels(story)
    if preview:
        platform, author = "Mẫu kiểm tra", story.get("author", "")
    d.ellipse((X + PAD, Y + 31, X + PAD + 53, Y + 84), fill=(37, 42, 47, 255))
    d.text((X + PAD + 8, Y + 31), "@", font=bold, fill=(241, 242, 244, 255))
    d.text((X + PAD + 73, Y + 25), platform, font=bold, fill=(245, 245, 246, 255))
    d.text((X + PAD + 73, Y + 70), author, font=meta, fill=(180, 186, 192, 255))
    space = d.textlength(" ", font=font)
    for j, line in enumerate(lines):
        x = X + PAD
        y = Y + 132 + j * 76
        for i in line:
            length = d.textlength(texts[i], font=font)
            if i in active:
                d.rounded_rectangle((x - 5, y + 2, x + length + 5, y + 65), radius=8, fill=(255, 231, 187, 25))
            d.text((x, y), texts[i], font=font, fill=(255, 237, 209, 255) if i in active else (182, 188, 194, 255))
            x += length + space
    _icons(d, Y + height - 42)
    label = (
        "Kiểm tra kỹ thuật"
        if preview
        else "Truyện hư cấu"
        if story.get("platform") == "original_fiction"
        else "Kể lại từ nguồn"
    )
    tw = d.textlength(label, font=meta)
    d.text((X + WIDTH - PAD - tw, Y + height - 57), label, font=meta, fill=(151, 159, 169, 255))
    return image


def timed_cards(story, words, duration, outdir, name, phrase_words=3):
    """Return (PNG, duration share); zero estimated word timings are introduced."""
    if not words or any(w.end_ms <= w.start_ms for w in words):
        raise ValueError("Real positive speech anchors are required")
    texts = [w.text for w in words]
    font = ImageFont.truetype(FONT, 56)
    pages = layout(texts, font)
    phrases = []
    for lines in pages:
        indices = [i for line in lines for i in line]
        current = []
        for i in indices:
            current.append(i)
            if len(current) >= phrase_words or (len(current) >= 2 and texts[i][-1:] in ",.;?!…"):
                phrases.append((lines, current))
                current = []
        if current:
            phrases.append((lines, current))
    outdir.mkdir(parents=True, exist_ok=True)
    frames = []
    for j, (lines, active) in enumerate(phrases):
        start = 0 if j == 0 else words[active[0]].start_ms / 1000
        end = duration if j == len(phrases) - 1 else words[phrases[j + 1][1][0]].start_ms / 1000
        if end <= start:
            raise ValueError("Non-monotonic speech anchors")
        path = outdir / f"{name}_p{j:03d}.png"
        draw_card(story, texts, lines, set(active)).save(path)
        frames.append((path, (end - start) / duration))
    return frames
