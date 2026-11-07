import hashlib

import pytest
from PIL import Image

from studio.social_video import memes, reaction_assets
from studio.social_video.util import read_json, write_json


def test_sound_resolver_uses_own_audio_not_related_recommendation():
    page = (
        '<audio src="https://www.myinstants.com/media/sounds/related.mp3"></audio>'
        '<meta content="https://www.myinstants.com/media/sounds/selected.mp3" property="og:audio">'
    )
    assert reaction_assets.resolve_sound(page).endswith("/selected.mp3")
    with pytest.raises(ValueError):
        reaction_assets.resolve_sound('<audio src="https://www.myinstants.com/media/sounds/related.mp3">')
    with pytest.raises(ValueError):
        reaction_assets.resolve_sound('<meta property="og:audio" content="https://example.com/unrelated.mp3">')


def test_curated_pool_rejects_editorial_standins_and_unreviewed_images():
    item = {
        "id": "i:real/cat",
        "kind": "image",
        "role": "reaction",
        "is_meme": True,
        "funny_threads_allowed": True,
        "source_url": "https://tenor.com/view/source",
        "sha256": "123",
        "visual_review": "AGENT_INSPECTED",
    }
    assert reaction_assets.allowed(item)
    for changes in [
        {"is_meme": False},
        {"role": "editorial_overlay"},
        {"source_url": ""},
        {"funny_threads_allowed": False},
        {"visual_review": "PENDING_AGENT_CONTACT_SHEET"},
    ]:
        assert not reaction_assets.allowed({**item, **changes})
    assert not reaction_assets.allowed(
        {**item, "kind": "sound", "audio_review": "SHORT_CLIP_ASR_UNRELIABLE_PREVIEW_BEFORE_USE"}
    )
    assert not reaction_assets.allowed({**item, "kind": "sound", "audio_review": "ASR_MISMATCH_PREVIEW_BEFORE_USE"})


def test_tiengdong_sound_resolver_uses_the_audio_player_only():
    page = (
        '<a href="https://tiengdong.com/wp-content/uploads/related.mp3">Related</a>'
        '<video><source src="https://tiengdong.com/other.mp4"></video>'
        '<audio><source src="https://tiengdong.com/wp-content/uploads/mixi.mp3?_=1"></audio>'
    )
    assert reaction_assets.resolve_sound(page, provider="tiengdong").endswith("/mixi.mp3")
    for invalid in [
        '<a href="https://tiengdong.com/related.mp3">Related</a>',
        '<audio src="https://example.com/other.mp3"></audio>',
        '<audio src="https://tiengdong.com/one.mp3"></audio>'
        '<audio src="https://tiengdong.com/two.mp3"></audio>',
    ]:
        with pytest.raises(ValueError):
            reaction_assets.resolve_sound(invalid, provider="tiengdong")


def test_changed_media_cannot_keep_a_verified_catalog_entry(tmp_path, monkeypatch):
    file = tmp_path / "cat.png"
    file.write_bytes(b"checked source")
    catalog = tmp_path / "library.json"
    write_json(
        catalog,
        {
            "items": [
                {
                    "id": "i:real/cat",
                    "kind": "image",
                    "role": "reaction",
                    "is_meme": True,
                    "funny_threads_allowed": True,
                    "source_url": "https://tenor.com/view/source",
                    "file": "cat.png",
                    "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                    "visual_review": "AGENT_INSPECTED",
                }
            ]
        },
    )
    monkeypatch.setattr(reaction_assets, "CATALOG", catalog)
    monkeypatch.setattr(reaction_assets, "MEMES", tmp_path)
    assert len(reaction_assets.load_curated()) == 1
    file.write_bytes(b"changed or replaced media")
    with pytest.raises(ValueError, match="Changed meme"):
        reaction_assets.load_curated()


def test_scan_preserves_exclusions_and_prevents_duplicate_template_ids(tmp_path, monkeypatch):
    root = tmp_path / "memes"
    folder = root / "images/imgflip"
    folder.mkdir(parents=True)
    for ext in ["png", "jpg"]:
        Image.new("RGB", (32, 32), "red").save(folder / f"123.{ext}")
    write_json(
        root / "meta.json",
        {
            "images/imgflip/123.png": {"catalog_excluded": True},
            "images/imgflip/123.jpg": {
                "source": "imgflip",
                "role": "meme_template",
                "source_url": "https://imgflip.com/memetemplate/123",
                "is_meme": True,
                "funny_threads_allowed": True,
                "visual_review": "AGENT_INSPECTED",
            },
        },
    )
    monkeypatch.setattr(memes, "MEMES", root)
    monkeypatch.setattr(memes, "META", root / "meta.json")
    monkeypatch.setattr(memes, "LIBRARY", root / "library.json")
    result = memes.scan()["items"]
    assert len(result) == 1
    assert result[0]["id"] == "i:imgflip/123"
    assert result[0]["source_url"].endswith("/123")
    assert result[0]["visual_review"] == "AGENT_INSPECTED"


def test_legacy_originals_remain_archived_but_cannot_be_meme_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setattr(reaction_assets, "STUDIO_ROOT", tmp_path)
    library = tmp_path / "assets/shared/overlays/funny_originals/library.json"
    write_json(
        library,
        {
            "items": [
                {"id": "i:drawn/cat", "kind": "image", "production_eligible": True},
                {"id": "s:original/pop", "kind": "sound", "production_eligible": True},
            ]
        },
    )
    meta = {
        "images/vietnam/old.png": {"source": "threadreel-original"},
        "images/imgflip/real.jpg": {"source": "imgflip"},
    }
    rejected = reaction_assets.reject_standins(meta)
    assert "images/vietnam/old.png" in rejected
    assert meta["images/vietnam/old.png"]["is_meme"] is False
    assert meta["images/imgflip/real.jpg"] == {"source": "imgflip"}
    items = read_json(library)["items"]
    assert items[0]["production_eligible"] is False
    assert items[1]["role"] == "functional_effect"
    assert items[1]["is_meme"] is False
