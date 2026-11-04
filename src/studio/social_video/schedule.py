"""Publishing plan for the Reddit story videos: three videos a day (morning, noon, evening),
filled part after part in publish order so a series runs in consecutive slots."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from .reddit import DONE, STORE
from .util import OUTPUT, read_json, write_json

SLOTS = {
    1: ["20:00"],
    2: ["12:00", "20:00"],
    3: ["11:30", "17:30", "21:00"],
    4: ["07:30", "11:30", "17:30", "21:00"],
    5: ["07:30", "11:30", "14:30", "17:30", "21:00"],
    6: ["07:30", "10:00", "12:30", "15:30", "18:30", "21:30"],
}
DAILY = ["07:30", "12:00", "20:00"]   # sáng, trưa, tối
HASHTAGS = "#truyenkinhdi #reddit #nosleep #truyenreddit #kinhdi #shorts"
PLAN = OUTPUT / "reddit" / "schedule.json"


def build(start: date, order: list[str] | None = None, skip: tuple[str, ...] = ()) -> list[dict]:
    """One entry per video part: file, title, description and publish time (local)."""
    done = read_json(DONE, {})
    ids = [i for i in (order or list(done)) if i not in skip]
    plan, day = [], start
    for sid in ids:
        if sid not in done:   # not rendered yet: keep its day reserved
            day += timedelta(days=1)
            continue
        story, vi = read_json(STORE / sid / "source.json"), read_json(STORE / sid / "vi.json")
        files = [OUTPUT / f for f in done[sid]["files"]]
        n = len(files)
        slots = SLOTS[min(n, max(SLOTS))]
        short = (vi.get("shock_title") or vi.get("yt_title") or vi["title"]).strip()
        for k, f in enumerate(files):
            # more parts than slots: the extras go to the next day's morning
            when_day = day + timedelta(days=k // len(slots))
            hh, mm = map(int, slots[k % len(slots)].split(":"))
            suffix = f" | Phần {k + 1}/{n}" if n > 1 else ""
            title = (short[:100 - len(suffix) - 2].rstrip() + ("…" if len(short) > 100 - len(suffix) - 2 else "")
                     + suffix)
            desc = (f"{vi['title']}\n\n"
                    + (f"Phần {k + 1}/{n}. " if n > 1 else "")
                    + "Truyện kinh dị từ Reddit, dịch và lồng tiếng Việt.\n\n"
                    # no link: channels that are not verified may not add external links
                    f"Truyện gốc: u/{story['author']} trên r/{story['sub']}\n\n"
                    f"{HASHTAGS}")
            plan.append({"story": sid, "part": k + 1, "parts": n, "file": str(Path(f).resolve()),
                         "title": title, "description": desc,
                         "publish_at": datetime(when_day.year, when_day.month, when_day.day,
                                                hh, mm).isoformat(timespec="minutes"),
                         "status": "pending"})
        day += timedelta(days=max(1, -(-n // len(slots))))
    return plan


def _bucket(when: datetime) -> tuple[date, int]:
    """Which daily slot a time falls in (uploads made under the old timetable used 11:30 etc.)."""
    return when.date(), 0 if when.hour < 10 else 1 if when.hour < 16 else 2


def _grid(after: datetime):
    """DAILY slot times strictly after `after`, forever."""
    day = after.date()
    while True:
        for t in DAILY:
            w = datetime.combine(day, datetime.strptime(t, "%H:%M").time())
            if w > after:
                yield w
        day += timedelta(days=1)


def _fixed(e: dict) -> bool:
    """Already booked somewhere (YouTube or TikTok): its time can no longer move."""
    return e["status"] != "pending" or bool(e.get("tiktok"))


def reslot(plan: list[dict], start: datetime) -> list[dict]:
    """Give pending parts DAILY slots after `start`, story by story in plan order. A story with
    nothing uploaded yet takes the earliest run of back-to-back free slots, so its parts air in a
    row; the rest of a partly uploaded story follows its last uploaded part. Uploaded parts keep
    their time and occupy their slot."""
    taken = {_bucket(datetime.fromisoformat(e["publish_at"])) for e in plan if _fixed(e)}
    stories: dict[str, list[dict]] = {}
    for e in plan:
        stories.setdefault(e["story"], []).append(e)
    for parts in stories.values():
        pending = [e for e in parts if not _fixed(e)]
        if not pending:
            continue
        done = [datetime.fromisoformat(e["publish_at"]) for e in parts if _fixed(e)]
        if done:   # continue right after what is already on YouTube
            slots = (w for w in _grid(max(done + [start])) if _bucket(w) not in taken)
            chosen = [next(slots) for _ in pending]
        else:      # first run of len(pending) consecutive grid slots that are all free
            run: list[datetime] = []
            for w in _grid(start):
                run = run + [w] if _bucket(w) not in taken else []
                if len(run) == len(pending):
                    break
            chosen = run
        for e, w in zip(pending, chosen):
            e["publish_at"] = w.isoformat(timespec="minutes")
            taken.add(_bucket(w))
    plan.sort(key=lambda e: e["publish_at"])
    return plan


def save(plan: list[dict], start: datetime | None = None) -> Path:
    old = {(e["story"], e["part"]): e for e in read_json(PLAN, [])}
    for e in plan:   # keep what was already uploaded
        prev = old.get((e["story"], e["part"]))
        if prev and _fixed(prev):
            e.update({k: prev[k] for k in ("status", "video_id", "publish_at", "tiktok") if k in prev})
    # build() only orders the parts; the real times come from the three daily slots
    reslot(plan, start or datetime.now() + timedelta(hours=1))
    write_json(PLAN, plan)
    return PLAN


UPLOAD_DIR = OUTPUT / "reddit" / "upload"


def upload_copy(entry: dict, max_mb: float = 8.8) -> Path:
    """720x1280 HEVC copy under `max_mb` (the browser upload tool takes <10 MB per file).
    YouTube re-encodes everything anyway; the cards stay sharp at this size."""
    from .util import ffmpeg, media_duration, run

    src = Path(entry["file"])
    out = UPLOAD_DIR / src.name
    if (out.exists() and out.stat().st_size < max_mb * 1024 * 1024
            and out.stat().st_mtime >= src.stat().st_mtime):   # a re-render replaces the copy
        return out
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    kbps = int((max_mb * 8 * 1024 * 1024 / media_duration(src) - 64000) / 1000)
    run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-vf", "scale=720:1280", "-c:v", "libx265", "-preset", "fast", "-b:v", f"{kbps}k",
         "-maxrate", f"{kbps * 2}k", "-bufsize", f"{kbps * 4}k", "-tag:v", "hvc1",
         "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)])
    return out


def mark(story: str, part: int, status: str = "scheduled") -> None:
    plan = read_json(PLAN, [])
    for e in plan:
        if e["story"] == story and e["part"] == part:
            e["status"] = status
    write_json(PLAN, plan)


TIKTOK_AHEAD = timedelta(days=10)   # TikTok Studio schedules at most 10 days out


def mark_tiktok(story: str, part: int, status: str = "scheduled") -> None:
    plan = read_json(PLAN, [])
    for e in plan:
        if e["story"] == story and e["part"] == part:
            e["tiktok"] = status
    write_json(PLAN, plan)


def next_tiktok() -> dict | None:
    """Next part to schedule on TikTok at the same time as on YouTube: not posted there yet,
    at least 20 minutes away (TikTok's minimum lead) and inside its 10-day window."""
    now = datetime.now()
    for e in read_json(PLAN, []):
        when = datetime.fromisoformat(e["publish_at"])
        if e.get("tiktok") or when < now + timedelta(minutes=20):
            continue
        if when > now + TIKTOK_AHEAD:
            return None
        caption = f"{e['title']}\n\n{HASHTAGS} #truyenma #fyp"
        return {**e, "upload": str(upload_copy(e)), "caption": caption,
                "day": when.day, "month": when.month, "time": when.strftime("%H:%M")}
    return None


def next_pending() -> dict | None:
    """The next part to upload, with Studio-ready date text ("8 thg 11, 2026")."""
    for e in read_json(PLAN, []):
        if e["status"] == "pending":
            when = datetime.fromisoformat(e["publish_at"])
            copy = upload_copy(e)
            return {**e, "upload": str(copy), "date_vi": f"{when.day} thg {when.month}, {when.year}",
                    "time": when.strftime("%H:%M")}
    return None
