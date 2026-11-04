"""Content-hash bundles: what a worker job needs from the project + assets, and merging results back.

Files travel as blobs named by sha256, so anything the worker already has (same clip, same font,
the same project re-submitted) is never uploaded twice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.cache import HashCache
from ..core.cache import file_sha256 as sha256_file
from ..core.logging_utils import get_logger
from ..core.outputs import archive_previous
from ..core.paths import atomic_replace, is_safe_relative
from ..core.project import ProjectContext

log = get_logger()

# work/ files that remote stages read (written by local generator stages); the rest of work/ is rebuilt
WORK_INPUTS = {"card.png", "script.json", "timeline.json", "words.json"}
SKIP_DIRS = {"output", "logs", "cache", "__pycache__"}
SKIP_PREFIXES = ("output/history/",)  # old renders stay on the controller
# where a worker job may write back into the project (state.json is merged, never copied)
RESULT_PREFIXES = ("output/", "audio/", "subtitles/", "work/", "logs/")
RESULT_FILES = {"project.json", "cost.json", "generation_budget.json"}


def _entry(path: Path, rel: str, hc: HashCache) -> dict[str, Any]:
    return {"path": rel, "sha256": hc.sha(path), "size": path.stat().st_size}


def project_manifest(ctx: ProjectContext, hc: HashCache, *, include_output: bool = False) -> list[dict[str, Any]]:
    """Project files a remote job needs. output/ only when the job starts after render (qc / package)."""
    out = []
    for p in sorted(ctx.dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ctx.dir).as_posix()
        parts = rel.split("/")
        skip = SKIP_DIRS - {"output"} if include_output else SKIP_DIRS
        if parts[0] in skip or p.suffix == ".tmp" or ".remote" in p.name or rel.startswith(SKIP_PREFIXES):
            continue
        if parts[0] == "work" and (len(parts) != 2 or parts[1] not in WORK_INPUTS):
            continue
        if rel == "state.json":
            continue
        out.append(_entry(p, rel, hc))
    if include_output and ctx.settings.get("paths.output"):
        for name in ("final.mp4", "captions.srt", "qc_report.json", "metadata.md", "scene_plan.json"):
            artifact = ctx.result_path(name)
            if artifact.is_file():
                out.append(_entry(artifact, "output/" + name, hc))
    return out


def asset_refs(ctx: ProjectContext) -> set[str]:
    p = ctx.project
    refs = {p.video.background, p.audio.background_music, f"asset:shared/caption_styles/{p.video.caption_style}.yaml"}
    for s in p.scenes:
        refs.update({s.visual.path, s.visual.overlay})
    return {r[len("asset:"):] for r in refs if isinstance(r, str) and r.startswith("asset:")}


def asset_manifest(ctx: ProjectContext, hc: HashCache) -> list[dict[str, Any]]:
    """Assets the remote stages read: `asset:` refs in project.json + the caption fonts."""
    files: dict[str, Path] = {}
    for rel in sorted(asset_refs(ctx)):
        path = ctx.resolve("asset:" + rel, what="asset")
        if path.is_file():
            files[rel] = path
    fonts = ctx.asset_dir("shared/fonts")
    if fonts.is_dir():
        for f in sorted(fonts.iterdir()):
            if f.is_file() and f.suffix.lower() in (".ttf", ".otf", ".ttc"):
                files[f"shared/fonts/{f.name}"] = f
    return [_entry(path, rel, hc) for rel, path in files.items()]


def _remote_name(p: Path) -> Path:
    return p.with_name(f"{p.stem}.remote{p.suffix}")


def apply_results(ctx: ProjectContext, results: list[dict[str, Any]], uploaded: dict[str, str],
                  fetch) -> dict[str, int]:
    """Write job results into the project. `fetch(sha, dest_tmp)` downloads one blob.

    - only RESULT_PREFIXES / RESULT_FILES, safe relative paths;
    - files already identical locally are skipped;
    - a file that existed at submit time and was edited locally since then is NOT overwritten:
      the worker's version is saved next to it as <name>.remote<ext>;
    - a new output/final.mp4 first moves the local final render to output/history/ (like a local render).
    """
    stats = {"written": 0, "same": 0, "conflict": 0, "rejected": 0}
    hc = HashCache(ctx.settings.path("cache") / "hashes.json")
    keep = int(ctx.settings.get("output.keep_history", 3))
    # final.mp4 first: archiving it also moves the old captions / QC report, which the results then replace
    for r in sorted(results, key=lambda r: r["path"] != "output/final.mp4"):
        rel, sha = r["path"], r["sha256"]
        if (not is_safe_relative(rel) or
                not (rel in RESULT_FILES or any(rel.startswith(x) for x in RESULT_PREFIXES))):
            log.warning("[pull] ignoring result outside the allowed folders: %s", rel)
            stats["rejected"] += 1
            continue
        dest = ctx.artifact_path(rel)
        if dest.is_file():
            local = hc.sha(dest)
            if local == sha:
                stats["same"] += 1
                continue
            if rel in uploaded and uploaded[rel] != local:
                dest = _remote_name(dest)
                log.warning("[pull] %s changed locally since submit - worker copy saved as %s", rel, dest.name)
                stats["conflict"] += 1
            elif rel == "output/final.mp4":
                from ..core.outputs import archive_project
                archive_project(ctx)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        fetch(sha, tmp)
        if sha256_file(tmp) != sha:
            tmp.unlink(missing_ok=True)
            raise OSError(f"download of {rel} is corrupted (sha mismatch)")
        atomic_replace(tmp, dest)
        stats["written"] += 1
    hc.save()
    return stats


def merge_state(ctx: ProjectContext, remote_state: dict[str, Any], stages: list[str], node_id: str) -> None:
    st = ctx.state()
    for name in stages:
        entry = (remote_state.get("stages") or {}).get(name)
        if entry:
            entry = dict(entry)
            entry["message"] = f"[{node_id}] {entry.get('message', '')}".strip()
            st.setdefault("stages", {})[name] = entry
    tmp = ctx.state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    atomic_replace(tmp, ctx.state_path)

