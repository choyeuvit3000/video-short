"""Threads discover -> --url flow and secret redaction on the console (AUDIT_REPORT §2, items 8-9)."""

import httpx
import pytest
from typer.testing import CliRunner

from studio.cli import app
from studio.core.errors import ProviderUnavailable
from studio.core.logging_utils import redact
from studio.pipeline.runner import RunOptions, run_pipeline
from studio.providers import source as src
from studio.workflows import load_workflow, project_defaults

from .conftest import make_project

POSTS = [
    {"id": "1", "url": "https://www.threads.net/@minh.dev/post/C9xYz_Ab1", "author": "minh.dev",
     "text": "Chuyện ở công ty cũ\nSếp bắt cả team làm thêm giờ mà không trả lương...", "timestamp": "2026-11-01"},
    {"id": "2", "url": "https://www.threads.com/@an/post/DD2", "author": "an", "text": "Một dòng thôi"},
    {"id": "3", "url": None, "author": "x", "text": "no permalink -> not cached"},
]


def test_threads_cache_lookup(tmp_path):
    assert src.save_threads_posts(tmp_path, POSTS) == 2
    # .net / .com, query string and trailing slash all find the same post
    post = src.from_url("https://www.threads.com/@minh.dev/post/C9xYz_Ab1/?xmt=abc", cache_dir=tmp_path)
    assert post.platform == "threads" and post.author == "minh.dev"
    assert post.title == "Chuyện ở công ty cũ" and post.body.startswith("Sếp bắt")
    one = src.from_url("https://threads.net/@an/post/DD2", cache_dir=tmp_path)
    assert one.title == "@an" and one.body == "Một dòng thôi"
    src.save_threads_posts(tmp_path, [{"url": "https://threads.net/@b/post/E3", "text": "mới"}])
    assert src.from_url("https://threads.net/@an/post/DD2", cache_dir=tmp_path).body == "Một dòng thôi"  # merged
    with pytest.raises(ProviderUnavailable) as e:
        src.from_url("https://www.threads.net/@someone/post/ZZZ", cache_dir=tmp_path)
    assert e.value.code == "source_manual" and "discover threads" in str(e.value)


def test_story_reader_uses_threads_cache(tmp_path, settings):
    src.save_threads_posts(settings.path("cache"), POSTS)
    ctx = make_project(tmp_path / "p", settings, workflow="story_reader",
                       source={"type": "url", "url": POSTS[0]["url"]},
                       **project_defaults(load_workflow(settings, "story_reader"), "test_9x16"))
    run_pipeline(ctx, RunOptions(only=["source"]))
    assert ctx.project.source.platform == "threads" and ctx.project.source.author == "minh.dev"


def test_threads_api_error_hides_token(monkeypatch):
    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "EAAB-very-secret-123")

    def fake_get(url, params=None, **kw):
        req = httpx.Request("GET", url, params=params)
        return httpx.Response(400, request=req)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(ProviderUnavailable) as e:
        src.threads_discover("hello")
    assert "EAAB-very-secret-123" not in str(e.value) and "400" in str(e.value)


def test_redact():
    assert redact("for url https://x/y?q=1&access_token=EAA123&limit=5") == \
        "for url https://x/y?q=1&access_token=***&limit=5"
    assert redact('{"Authorization": "Bearer abcdef123456"}') == '{"Authorization": "Bearer ***"}'
    assert redact("Bearer abcdef123456") == "Bearer ***"
    assert redact("api_key=sk-1 password: hunter2 THREADS_ACCESS_TOKEN=EAA9") == \
        "api_key=*** password: *** THREADS_ACCESS_TOKEN=***"
    # prose stays readable
    assert redact("THREADS_ACCESS_TOKEN not set in .env") == "THREADS_ACCESS_TOKEN not set in .env"
    assert redact("missing or wrong token") == "missing or wrong token"


def test_cli_failed_line_is_redacted(monkeypatch):
    def boom(query, limit=15):
        raise ProviderUnavailable("Threads API error for ?access_token=EAAB-leak-42 [bad]", code="source_api")

    monkeypatch.setattr(src, "threads_discover", boom)
    r = CliRunner().invoke(app, ["discover", "threads", "hello"])
    assert r.exit_code != 0
    assert "FAILED" in r.output and "EAAB-leak-42" not in r.output
    assert "access_token=***" in r.output and "[bad]" in r.output  # markup is escaped, not swallowed
