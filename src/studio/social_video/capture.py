"""Collect Threads post URLs for a time window and screenshot each post."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .util import INPUTS, log

THREADS = "https://www.threads.com"
POST_RE = re.compile(r"^https://www\.threads\.(?:com|net)/@[^/]+/post/[A-Za-z0-9_-]+/?$")

# Header/nav bars are position:fixed and would cover element screenshots;
# role=dialog is the login prompt that appears after scrolling.
HIDE_CHROME_CSS = """
header, nav, [role="dialog"], [role="banner"] { display: none !important; }
"""

HIDDEN_MARKERS = ("Bạn không xem được nội dung này", "You can't see this")

# Posts under the "Related threads" heading are suggestions from other
# accounts, not replies, so they are flagged and skipped.
CONTAINERS_JS = """() => {
  const heading = [...document.querySelectorAll('span, div, h1, h2, h3')].find(e =>
    e.children.length === 0 && /^(Thread liên quan|Related threads)$/i.test((e.innerText || '').trim()));
  return [...document.querySelectorAll('[data-pressable-container="true"]')].map((c, i) => {
    const post = c.querySelector('a[href*="/post/"]');
    const user = c.querySelector('a[href^="/@"]');
    const t = c.querySelector('time');
    return {
      i,
      href: post ? post.href.split('?')[0].replace(/\\/media$/, '') : null,
      user: user ? user.getAttribute('href').replace('/@', '').split('/')[0] : null,
      time: t ? t.dateTime : null,
      related: heading ? !!(heading.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING) : false,
      text: c.innerText,
    };
  });
}"""


# Media of the main post: images (minus avatars and video thumbnails) and videos,
# in on-screen order so carousels keep their sequence.
MEDIA_JS = r"""(c) => {
  const vids = [...c.querySelectorAll('video')].map(v => ({kind: 'video', src: v.currentSrc || v.src,
    r: v.getBoundingClientRect()}));
  const imgs = [...c.querySelectorAll('img')].filter(i => {
    const r = i.getBoundingClientRect();
    if (r.width < 100 || /ảnh đại diện|profile picture/i.test(i.alt)) return false;
    return !vids.some(v => Math.abs(v.r.x - r.x) < 6 && Math.abs(v.r.y - r.y) < 6);
  }).map(i => {
    // carousels display small thumbnails; srcset lists the full-size candidates
    const best = (i.srcset || '').split(',').map(s => s.trim().split(/\s+/))
      .filter(p => p.length === 2).sort((a, b) => parseInt(b[1]) - parseInt(a[1]))[0];
    return {kind: 'image', src: best ? best[0] : (i.currentSrc || i.src), r: i.getBoundingClientRect()};
  });
  return [...imgs, ...vids].filter(m => m.src && !m.src.startsWith('blob:'))
    .sort((a, b) => (a.r.y - b.r.y) || (a.r.x - b.r.x)).map(m => ({kind: m.kind, src: m.src}));
}"""

MAX_MEDIA_BYTES = 80 * 1024 * 1024
TIME_RE = re.compile(r"\d+\s*(giây|phút|giờ|ngày|tuần|[smhdw])|\d{1,2}/\d{1,2}(/\d{2,4})?",
                     re.I)


def _download_media(page, container, prefix: Path, limit: int) -> list[dict]:
    out = []
    for k, m in enumerate(container.evaluate(MEDIA_JS)[:limit]):
        try:
            resp = page.request.get(m["src"], timeout=60000)
            body = resp.body()
            if not resp.ok or len(body) > MAX_MEDIA_BYTES:
                continue
            ext = ".mp4" if m["kind"] == "video" else (
                ".png" if "png" in resp.headers.get("content-type", "") else ".jpg")
            path = prefix.with_name(f"{prefix.name}_m{k}{ext}")
            path.write_bytes(body)
            out.append({"kind": m["kind"], "file": path.name})
        except Exception as exc:
            log(f"  Không tải được media {k}: {exc.__class__.__name__}")
    return out


def body_of(text: str) -> str:
    """Captured container text minus the author/date header and counter lines."""
    lines = text.split("\n")[1:]
    # the header may also carry a topic tag before the time ("kịch idecaf", "2 giờ")
    for k, ln in enumerate(lines[:3]):
        if TIME_RE.fullmatch(ln.strip()):
            lines = lines[k + 1:]
            break
    return "\n".join(ln for ln in lines
                     if not re.fullmatch(r"[\d.,]+\s*[KkMm]?", ln.strip())).strip()


def read_link_files(day: str) -> list[str]:
    urls = []
    for name in ("links.txt", f"{day}.txt"):
        path = INPUTS / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip().split("?")[0]
            if line and not line.startswith("#") and POST_RE.match(line):
                urls.append(line.replace("threads.net", "threads.com"))
    return urls


def _new_page(browser):
    page = browser.new_page(
        viewport={"width": 540, "height": 1400}, device_scale_factor=2,
        color_scheme="dark", locale="vi-VN",
    )
    page.set_default_timeout(45000)
    return page


def _open(page, url: str) -> None:
    # Autoplaying videos keep the network busy, so "networkidle" may never fire.
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector('[data-pressable-container="true"]', timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(1200)


def collect_from_accounts(browser, accounts: list[str], start: datetime, end: datetime,
                          scrolls: int = 6) -> list[str]:
    urls: list[str] = []
    for acc in accounts:
        acc = acc.lstrip("@").strip()
        if not acc:
            continue
        page = _new_page(browser)
        try:
            _open(page, f"{THREADS}/@{acc}")
            seen_old = False
            for _ in range(scrolls):
                for item in page.evaluate(CONTAINERS_JS):
                    if not item["href"] or not item["time"] or item["user"] != acc:
                        continue
                    ts = datetime.fromisoformat(item["time"].replace("Z", "+00:00"))
                    if start <= ts < end and item["href"] not in urls:
                        urls.append(item["href"])
                    elif ts < start:
                        seen_old = True
                if seen_old:
                    break
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(1200)
            log(f"@{acc}: {sum(1 for u in urls if f'/@{acc}/' in u)} bài trong khung giờ")
        except Exception as exc:  # one broken profile should not stop the run
            log(f"@{acc}: lỗi khi đọc profile ({exc.__class__.__name__}: {exc})")
        finally:
            page.close()
    return urls


def _stitch(parts: list[Path], comments: list[Path], out: Path, font_path: str) -> None:
    images = [Image.open(p).convert("RGB") for p in parts]
    cmt_images = [Image.open(p).convert("RGB") for p in comments]
    width = max(im.width for im in images + cmt_images)
    gap = 6
    label_h = 90 if cmt_images else 0
    height = (sum(im.height for im in images + cmt_images)
              + gap * (len(images) + len(cmt_images)) + label_h)
    canvas = Image.new("RGB", (width, height), (16, 16, 16))
    y = 0
    for im in images:
        canvas.paste(im, (0, y))
        y += im.height + gap
    if cmt_images:
        draw = ImageDraw.Draw(canvas)
        draw.rectangle([0, y, width, y + label_h], fill=(30, 30, 34))
        font = ImageFont.truetype(font_path, 40)
        draw.text((32, y + 22), "BÌNH LUẬN NỔI BẬT", font=font, fill=(255, 214, 0))
        y += label_h
        for im in cmt_images:
            canvas.paste(im, (0, y))
            y += im.height + gap
    canvas.save(out)


def capture_posts(browser, urls: list[str], outdir: Path, cfg: dict) -> list[dict]:
    outdir.mkdir(parents=True, exist_ok=True)
    posts = []
    for idx, url in enumerate(urls):
        page = _new_page(browser)
        try:
            _open(page, url)
            page.add_style_tag(content=HIDE_CHROME_CSS)
            items = page.evaluate(CONTAINERS_JS)
            if not items:
                log(f"Bỏ qua (không thấy nội dung): {url}")
                continue
            author = items[0]["user"]
            chain, comments = [items[0]], []
            max_comments = max(cfg["include_comments"], cfg["story"]["comments"])
            # The author's own replies directly under the post continue the thread;
            # the first replies by other people are kept as "top comments".
            for item in items[1:]:
                if item["related"]:
                    break
                if any(h in item["text"] for h in HIDDEN_MARKERS):
                    continue
                if item["user"] == author and not comments:
                    if len(chain) < cfg["thread_max_parts"]:
                        chain.append(item)
                elif item["user"] != author:
                    if len(comments) >= max_comments:
                        break
                    comments.append(item)
            locator = page.locator('[data-pressable-container="true"]')
            part_files, cmt_files = [], []
            for kind, group, bucket in (("p", chain, part_files), ("c", comments, cmt_files)):
                for j, item in enumerate(group):
                    path = outdir / f"post{idx:02d}_{kind}{j}.png"
                    el = locator.nth(item["i"])
                    el.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    el.screenshot(path=str(path))
                    bucket.append(path)
            media = _download_media(page, locator.nth(items[0]["i"]), outdir / f"post{idx:02d}",
                                    cfg["story"]["max_media"])
            stitched = outdir / f"post{idx:02d}.png"
            _stitch(part_files, cmt_files[: cfg["include_comments"]], stitched,
                    cfg["fonts"]["title"])
            posts.append({
                "index": len(posts),
                "url": url,
                "author": author,
                "time": items[0]["time"],
                "text": "\n---\n".join(_clean(i["text"]) for i in chain),
                "comments": [{"author": c["user"], "text": _clean(c["text"]), "image": f.name}
                             for c, f in zip(comments, cmt_files)],
                "image": stitched.name,
                "parts": [p.name for p in part_files],
                "part_texts": [body_of(_clean(i["text"])) for i in chain],
                "media": media,
            })
            log(f"Đã chụp {idx + 1}/{len(urls)}: @{author} ({len(chain)} phần, "
                f"{len(comments)} bình luận, {len(media)} ảnh/video)")
        except Exception as exc:
            log(f"Lỗi chụp {url}: {exc.__class__.__name__}: {exc}")
        finally:
            page.close()
    return posts


def _clean(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
    drop = {"·", "Tác giả", "Author", "Dịch", "Translate", "Xem bản dịch", "See translation"}
    return "\n".join(ln for ln in lines if ln and ln not in drop)


def gather(day: str, start: datetime, end: datetime, cfg: dict, outdir: Path) -> list[dict]:
    from playwright.sync_api import sync_playwright

    urls = read_link_files(day)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            if cfg["accounts"]:
                urls += collect_from_accounts(browser, cfg["accounts"], start, end)
            urls = list(dict.fromkeys(urls))[: cfg["max_posts"]]
            if not urls:
                return []
            log(f"Tổng {len(urls)} bài cần chụp")
            return capture_posts(browser, urls, outdir, cfg)
        finally:
            browser.close()


def window_for(day: str | None, lookback_hours: int) -> tuple[datetime, datetime]:
    if day:
        start = datetime.strptime(day, "%Y-%m-%d").astimezone()
        return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=lookback_hours), now
