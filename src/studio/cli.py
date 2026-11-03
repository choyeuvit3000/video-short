"""`studio` command line. Every command returns the exit codes in core/errors.py:
0 ok · 1 error · 2 validation · 3 waiting for a manual step · 4 budget · 5 QC fail."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.table import Table

from . import __version__
from .core.config import deep_merge, get_settings
from .core.errors import EXIT_ERROR, EXIT_OK, EXIT_VALIDATION, ManualGateRequired, StudioError
from .core.ffmpeg import ffmpeg_bin, ffprobe_bin, has_encoder, has_filter, run_ffmpeg
from .core.logging_utils import attach_run_log, console
from .core.media_probe import probe
from .core.project import ProjectContext, scaffold
from .core.schema import Project

app = typer.Typer(help="AI Shorts Studio - multi-workflow short/long video pipeline.", no_args_is_help=True,
                  add_completion=False, pretty_exceptions_enable=False)
voices_app = typer.Typer(help="Manage voices (free / api / local models).", no_args_is_help=True)
discover_app = typer.Typer(help="Find hot posts through official APIs (you choose what to render).",
                           no_args_is_help=True)
app.add_typer(voices_app, name="voices")
app.add_typer(discover_app, name="discover")

ProjectArg = Annotated[Path, typer.Argument(help="Project folder (contains project.json)")]


def _guard(fn: Callable[[], int | None]) -> None:
    """Run a command body and turn StudioError into a clean message + the right exit code."""
    try:
        code = fn() or EXIT_OK
    except ManualGateRequired as e:
        console.print(f"[yellow]WAITING MANUAL[/] {e}")
        code = e.exit_code
    except StudioError as e:
        console.print(f"[red]FAILED[/] {e}")
        code = e.exit_code
    raise typer.Exit(code)


def _ctx(project_dir: Path, command: str) -> ProjectContext:
    ctx = ProjectContext(project_dir)
    log_path = attach_run_log(ctx.dir, command)
    console.print(f"[dim]log: {log_path}[/]")
    return ctx


def slugify(text: str, max_len: int = 40) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-") or "project"


# ------------------------------------------------------------------ doctor


@app.command()
def doctor(gpu: Annotated[bool, typer.Option("--gpu", help="Also check NVIDIA GPU / NVENC")] = False) -> None:
    """Check tools, fonts, AI CLIs, optional packages and write access."""
    s = get_settings()
    rows: list[tuple[str, str, str]] = []

    def add(name: str, ok: bool | None, detail: str = "") -> None:
        rows.append((name, {True: "[green]OK[/]", False: "[red]MISSING[/]", None: "[yellow]optional[/]"}[ok], detail))

    add("python", sys.version_info >= (3, 11), f"{platform.python_version()} ({sys.executable})")
    try:
        ff = ffmpeg_bin()
        ver = subprocess.run([ff, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
        add("ffmpeg", True, f"{ver[:60]} - {ff}")
        add("ffprobe", bool(ffprobe_bin()), ffprobe_bin())
        add("libass (burn captions)", has_filter("ass"), "")
        add("lavfi gradients", has_filter("gradients"), "fallback: use background color:#hex")
    except StudioError as e:
        add("ffmpeg", False, str(e))
    try:
        from .renderers.fonts import find_font

        add("font", True, str(find_font(s.path("assets") / "shared" / "fonts")))
    except FileNotFoundError as e:
        add("font", False, str(e))
    for cli in ("claude", "agy", "codex"):
        path = shutil.which(s.get(f"llm.{cli}_cli.command") or cli)
        add(f"{cli} CLI", True if path else None, path or "not on PATH (LLM chain skips it)")
    for mod, label in (("edge_tts", "edge-tts"), ("piper", "piper-tts [piper]"),
                       ("faster_whisper", "faster-whisper [align]"), ("fastapi", "fastapi [worker]")):
        found = importlib.util.find_spec(mod) is not None
        add(label, True if found else (False if mod == "edge_tts" else None), "")
    for key in ("projects", "cache"):
        d = s.path(key)
        try:
            d.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=d):
                pass
            add(f"write {key}/", True, str(d))
        except OSError as e:
            add(f"write {key}/", False, str(e))
    add(".env", True if (s.root / ".env").exists() else None, "copy .env.example -> .env for API keys")
    if gpu:
        smi = shutil.which("nvidia-smi")
        if smi:
            q = subprocess.run([smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                               capture_output=True, text=True)
            add("nvidia-smi", q.returncode == 0, q.stdout.strip() or q.stderr.strip())
        else:
            add("nvidia-smi", False, "no NVIDIA driver found")
        if has_encoder("h264_nvenc"):
            try:
                run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.5", "-c:v", "h264_nvenc",
                            "-f", "null", "-"], stage="doctor")
                add("h264_nvenc encode", True, "set render.encoder: h264_nvenc in config/local.yaml")
            except StudioError as e:
                add("h264_nvenc encode", False, str(e)[:120])
        else:
            add("h264_nvenc", False, "ffmpeg build has no nvenc")
        try:
            import torch  # type: ignore[import-not-found]

            add("torch CUDA", torch.cuda.is_available(), torch.__version__)
        except ImportError:
            add("torch", None, "not installed (only needed for GPU TTS / ComfyUI venvs)")

    t = Table(title=f"studio doctor v{__version__}  ·  {s.root}")
    for c in ("check", "status", "detail"):
        t.add_column(c, overflow="fold")
    for r in rows:
        t.add_row(*r)
    console.print(t)
    hard_fail = any("MISSING" in r[1] and r[0] in ("python", "ffmpeg", "ffprobe", "font", "edge-tts") for r in rows)
    raise typer.Exit(EXIT_ERROR if hard_fail else EXIT_OK)


# ------------------------------------------------------------------ workflows / new


@app.command()
def workflows() -> None:
    """List workflow recipes, their cost tier and status."""
    from .workflows import list_workflows

    t = Table(title="workflows")
    for c in ("name", "tier", "status", "formats", "cost", "description"):
        t.add_column(c, overflow="fold")
    for wf in list_workflows(get_settings()):
        st = wf["status"]
        t.add_row(wf["name"], str(wf.get("tier", "")), f"[green]{st}[/]" if st == "ready" else f"[yellow]{st}[/]",
                  ", ".join(wf.get("formats", [])), str(wf.get("cost", "")), str(wf.get("description", "")))
    console.print(t)


@app.command()
def new(
    workflow: Annotated[str, typer.Argument(help="story_reader | ai_cinematic | ... (see `studio workflows`)")],
    name: Annotated[str, typer.Argument(help="Short name; becomes the folder slug")],
    fmt: Annotated[list[str], typer.Option("--format", "-f", help="Repeat for several outputs")] = None,
    lang: Annotated[str, typer.Option("--lang", help="vi | en")] = "vi",
    text_file: Annotated[Path | None, typer.Option("--text-file", help="Source text (copied to source/)")] = None,
    url: Annotated[str | None, typer.Option("--url", help="Source URL (Reddit uses the official API)")] = None,
    brief_file: Annotated[Path | None, typer.Option("--brief-file", help="ai_cinematic brief")] = None,
    voice: Annotated[str | None, typer.Option("--voice", help="Voice id (see `studio voices list`)")] = None,
    out_dir: Annotated[Path | None, typer.Option("--dir", help="Exact project folder (single format)")] = None,
    sets: Annotated[list[str], typer.Option("--set", help="Workflow option key=value, e.g. rewrite=none")] = None,
) -> None:
    """Create project folder(s) from a workflow recipe."""

    def body() -> int:
        from .workflows import load_workflow, project_defaults

        s = get_settings()
        wf = load_workflow(s, workflow)
        if wf["status"] != "ready":
            console.print(f"[yellow]workflow {workflow} is '{wf['status']}': only the generic stages run[/]")
        formats = fmt or [wf.get("formats", ["short_9x16"])[0]]
        for f in formats:
            s.format(f)  # validates the name
        if lang not in ("vi", "en"):
            raise StudioError("--lang must be vi or en", code="bad_lang")
        for src in (text_file, brief_file):
            if src and not src.is_file():
                raise StudioError(f"file not found: {src}", code="missing_file")
        if out_dir and len(formats) > 1:
            raise StudioError("--dir works with a single --format", code="bad_args")
        options: dict = {}
        for item in sets or []:
            key, sep, value = item.partition("=")
            if not sep or not key.strip():
                raise StudioError(f"--set expects key=value, got {item!r}", code="bad_args")
            options[key.strip()] = yaml.safe_load(value) if value else ""
        base = f"{datetime.now():%Y%m%d}_{slugify(name)}"
        created = []
        for f in formats:
            suffix = f"_{f.split('_')[0]}" if len(formats) > 1 else ""
            pid = (base + suffix)[:64]
            pdir = out_dir or (s.path("projects") / workflow / pid)
            data = deep_merge(project_defaults(wf, f), {
                "project_id": pid, "workflow": workflow, "language": lang, "title": "",
                "video": {"format": f}, "options": options,
                "budget": {"max_cost_usd": float(s.get("budget.default_max_cost_usd", 0))},
            })
            if voice:
                data.setdefault("audio", {})["voice_profile"] = voice
            if url:
                data["source"] = {"type": "url", "url": url}
            scaffold(pdir, Project.model_validate(data))
            if text_file:
                shutil.copy2(text_file, pdir / "source" / "source.md")
            if brief_file:
                shutil.copy2(brief_file, pdir / "source" / "brief.md")
            created.append(pdir)
        for d in created:
            console.print(f"[green]created[/] {d}")
        console.print(f'next: studio run "{created[0]}"')
        return EXIT_OK

    _guard(body)


# ------------------------------------------------------------------ pipeline commands


@app.command()
def run(
    project: ProjectArg,
    from_stage: Annotated[str | None, typer.Option("--from", help="Start at this stage")] = None,
    only: Annotated[list[str], typer.Option("--only", help="Run only these stages (repeatable)")] = None,
    force: Annotated[bool, typer.Option("--force", help="Regenerate source/script/scenes/storyboard")] = False,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Re-synthesize TTS audio")] = False,
    strict: Annotated[bool, typer.Option("--strict", help="QC warnings fail the run")] = False,
    allow_sidecar: Annotated[bool, typer.Option("--allow-sidecar-subs")] = False,
) -> None:
    """Run the project's workflow (resumable; stops with exit 3 at manual steps)."""
    from .pipeline.runner import RunOptions, run_pipeline

    def body() -> int:
        ctx = _ctx(project, "run")
        ro = RunOptions(from_stage=from_stage, only=only or [], force=force,
                        stage_opts={"overwrite": overwrite, "strict": strict, "allow_sidecar": allow_sidecar})
        run_pipeline(ctx, ro)
        console.print(f"[green]DONE[/] {ctx.dir / 'output' / 'final.mp4'}")
        return EXIT_OK

    _guard(body)


@app.command()
def validate(project: ProjectArg,
             media: Annotated[bool, typer.Option(help="Require media files to exist")] = True) -> None:
    """Check project.json and referenced files."""
    from .core.validator import validate_project

    def body() -> int:
        ctx = _ctx(project, "validate")
        issues = validate_project(ctx, require_media=media)
        for i in issues:
            console.print(("[red]ERROR[/] " if i.level == "error" else "[yellow]WARN[/]  ") + str(i))
        errors = sum(1 for i in issues if i.level == "error")
        console.print(f"{len(ctx.project.scenes)} scenes, {errors} error(s), {len(issues) - errors} warning(s)")
        return EXIT_VALIDATION if errors else EXIT_OK

    _guard(body)


def _single_stage(project: Path, stage: str, **opts) -> None:
    from .workflows import get_stages

    def body() -> int:
        ctx = _ctx(project, stage)
        ctx.set_stage(stage, "running")
        try:
            msg = get_stages()[stage](ctx, opts)
        except StudioError as e:
            ctx.set_stage(stage, "failed", str(e))
            raise
        ctx.set_stage(stage, "done", msg)
        console.print(f"[green]{stage}[/] {msg}")
        return EXIT_OK

    _guard(body)


@app.command()
def voice(project: ProjectArg, overwrite: Annotated[bool, typer.Option("--overwrite")] = False) -> None:
    """Generate narration audio + word timings + timeline."""
    _single_stage(project, "voice", overwrite=overwrite)


@app.command()
def render(
    project: ProjectArg,
    burn_subs: Annotated[bool | None, typer.Option("--burn-subs/--no-burn-subs")] = None,
    allow_sidecar: Annotated[bool, typer.Option("--allow-sidecar-subs")] = False,
) -> None:
    """Render output/final.mp4 from the timeline."""
    _single_stage(project, "render", burn_subs=burn_subs, allow_sidecar=allow_sidecar)


@app.command()
def qc(project: ProjectArg, strict: Annotated[bool, typer.Option("--strict")] = False) -> None:
    """Check output/final.mp4 (codec, size, fps, duration, captions) -> output/qc_report.json."""
    _single_stage(project, "qc", strict=strict)


@app.command()
def package(project: ProjectArg) -> None:
    """Write output/metadata.md (title, hashtags, AI disclosure, credits)."""
    _single_stage(project, "package")


@app.command()
def status(project: ProjectArg) -> None:
    """Show stage status of a project."""

    def body() -> int:
        ctx = ProjectContext(project)
        from .pipeline.runner import stages_for

        st = ctx.state().get("stages", {})
        t = Table(title=f"{ctx.project.project_id} ({ctx.project.workflow}, {ctx.project.video.format})")
        for c in ("stage", "status", "at", "message"):
            t.add_column(c, overflow="fold")
        for name in stages_for(ctx):
            e = st.get(name, {})
            t.add_row(name, e.get("status", "pending"), e.get("at", ""), e.get("message", ""))
        console.print(t)
        final = ctx.dir / "output" / "final.mp4"
        if final.exists():
            console.print(f"output: {final} ({probe(final).duration:.2f}s)")
        return EXIT_OK

    _guard(body)


# ------------------------------------------------------------------ voices

SAMPLE_TEXT = {
    "vi": "Xin chào, đây là giọng đọc thử cho kênh video ngắn của bạn.",
    "en": "Hi there, this is a quick sample of the voice for your short video channel.",
}


@voices_app.command("list")
def voices_list(
    lang: Annotated[str | None, typer.Option("--lang")] = None,
    tier: Annotated[str | None, typer.Option("--tier", help="free | api | local")] = None,
) -> None:
    """List voice profiles with tier, status, location and install state."""
    from .voices import is_installed, load_registry

    reg = load_registry(get_settings())
    t = Table(title=f"voices (defaults: {reg.defaults})")
    for c in ("id", "lang", "tier", "provider", "status", "location", "installed", "$/1k chars", "fallback"):
        t.add_column(c, overflow="fold")
    for p in reg.profiles.values():
        if (lang and p.lang != lang) or (tier and p.tier != tier):
            continue
        inst = "-" if not p.files else ("[green]yes[/]" if is_installed(reg, p) else "[yellow]no[/]")
        st = f"[green]{p.status}[/]" if p.usable else f"[dim]{p.status}[/]"
        t.add_row(p.id, p.lang, p.tier, p.provider, st, p.location, inst, f"{p.cost_per_1k_chars:g}",
                  p.fallback or "")
    console.print(t)


@voices_app.command("install")
def voices_install(voice_id: str, force: Annotated[bool, typer.Option("--force")] = False) -> None:
    """Download a local model (official URLs from voices/local/manifest.yaml) into voices/local/models/."""
    from .voices import install, load_registry

    def body() -> int:
        reg = load_registry(get_settings())
        d = install(reg, reg.get(voice_id), force=force)
        console.print(f"[green]installed[/] {voice_id} -> {d}")
        return EXIT_OK

    _guard(body)


def _synth_sample(voice_id: str, text: str | None, out_dir: Path) -> Path:
    from .core.cost import CostLedger
    from .providers.tts import get_provider
    from .voices import load_registry

    reg = load_registry(get_settings())
    prof = reg.get(voice_id)
    prov = get_provider(prof.provider, reg)
    reason = prov.check(prof)
    if reason:
        raise StudioError(f"{voice_id}: {reason}", code="tts_unavailable")
    text = text or SAMPLE_TEXT.get(prof.lang, SAMPLE_TEXT["en"])
    if prof.estimate_cost(text) > 0:
        CostLedger(out_dir, 0).ensure(prof.estimate_cost(text), f"preview {voice_id}")
    out = out_dir / f"{voice_id}{prov.extension}"
    res = prov.synthesize(text, prof, out)
    return res.audio_path


@voices_app.command("preview")
def voices_preview(voice_id: str, text: Annotated[str | None, typer.Option("--text")] = None) -> None:
    """Synthesize a sample into voices/samples/ to listen and compare."""

    def body() -> int:
        out_dir = get_settings().path("voices") / "samples"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = _synth_sample(voice_id, text, out_dir)
        console.print(f"[green]sample[/] {path} ({probe(path).duration:.2f}s)")
        return EXIT_OK

    _guard(body)


@voices_app.command("test")
def voices_test(voice_id: str) -> None:
    """Check that a voice works right now (synthesizes to a temp folder)."""

    def body() -> int:
        with tempfile.TemporaryDirectory() as td:
            path = _synth_sample(voice_id, None, Path(td))
            info = probe(path)
            if not info.has_audio or info.duration < 0.5:
                raise StudioError(f"{voice_id}: produced no usable audio", code="tts_failed")
            console.print(f"[green]OK[/] {voice_id}: {info.duration:.2f}s {info.acodec} {info.sample_rate} Hz")
        return EXIT_OK

    _guard(body)


# ------------------------------------------------------------------ discover


def _print_posts(posts: list[dict], title: str) -> None:
    t = Table(title=title)
    for c in ("#", "score", "chars", "title", "url"):
        t.add_column(c, overflow="fold")
    for i, p in enumerate(posts, 1):
        t.add_row(str(i), str(p.get("score", "")), str(p.get("chars", "")), p.get("title", ""), p.get("url") or "")
    console.print(t)
    console.print('pick one: studio new story_reader "<name>" --url <url>')


@discover_app.command("reddit")
def discover_reddit(
    subreddit: str,
    period: Annotated[str, typer.Option("--period", help="hour|day|week|month|year|all")] = "day",
    limit: Annotated[int, typer.Option("--limit")] = 15,
    text_only: Annotated[bool, typer.Option("--text-only/--all")] = True,
    nsfw: Annotated[bool, typer.Option("--nsfw")] = False,
    save: Annotated[Path | None, typer.Option("--save", help="Write the list as JSON")] = None,
) -> None:
    """Top posts of a subreddit via the official Reddit API (needs REDDIT_CLIENT_ID/SECRET)."""
    from .providers.source import reddit_discover

    def body() -> int:
        get_settings()  # loads .env
        posts = reddit_discover(subreddit, period=period, limit=limit, allow_nsfw=nsfw)
        if text_only:
            posts = [p for p in posts if p["text_post"] and p["enough_text"]]
        if save:
            save.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_posts(posts, f"r/{subreddit} top/{period}")
        return EXIT_OK

    _guard(body)


@discover_app.command("threads")
def discover_threads(query: str, limit: Annotated[int, typer.Option("--limit")] = 15) -> None:
    """Keyword search on Threads via the official API (needs THREADS_ACCESS_TOKEN)."""
    from .providers.source import threads_discover

    def body() -> int:
        get_settings()
        _print_posts(threads_discover(query, limit=limit), f"threads: {query}")
        return EXIT_OK

    _guard(body)


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"studio {__version__} (python {platform.python_version()}, {os.name})")


if __name__ == "__main__":
    app()
