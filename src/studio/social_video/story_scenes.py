"""Pin optional scene photos before the narration/layout checkpoint."""

from pathlib import Path

from ..core.errors import ManualGateRequired
from .quality import sha256
from .util import read_json, write_json


def prepare(folder, vi):
    from . import images

    scenes = read_json(folder / "scene_plan.json", {})
    for paragraph, query in (vi.get("scenes") or {}).items():
        old = scenes.get(str(paragraph), {})
        if old.get("query") == query and Path(old.get("path", "")).is_file():
            if sha256(Path(old["path"])) == old.get("sha256"):
                continue
        photo = images.find(query, folder / "img")
        if photo is None:
            raise ManualGateRequired("story_scene", "Thiếu ảnh minh họa đã chọn; đổi ảnh trước khi duyệt bố cục.")
        scenes[str(paragraph)] = {"query": query, "path": str(photo.resolve()), "sha256": sha256(photo)}
    write_json(folder / "scene_plan.json", {k: v for k, v in scenes.items() if k in (vi.get("scenes") or {})})


def photo(folder, paragraph):
    scenes = read_json(folder / "scene_plan.json", {})
    candidates = sorted(int(k) for k in scenes)
    if not candidates:
        return None
    selected = max((k for k in candidates if k <= paragraph), default=candidates[0])
    item = scenes[str(selected)]
    path = Path(item["path"])
    if not path.is_file() or sha256(path) != item["sha256"]:
        raise ManualGateRequired("story_scene", "Ảnh đã đổi; chuẩn bị lại preview trước khi duyệt giọng.")
    return path
