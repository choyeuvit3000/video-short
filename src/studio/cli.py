"""`studio` command line. Every command returns the exit codes in core/errors.py:
0 ok · 1 error · 2 validation · 3 waiting for a manual step · 4 budget · 5 QC fail · 6 waiting for a worker node."""

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
from rich.markup import escape
from rich.table import Table

from . import __version__
from .core.config import deep_merge, get_settings
from .core.errors import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_VALIDATION,
    ManualGateRequired,
    StudioError,
    ValidationError,
    WaitingForNode,
)
from .core.ffmpeg import ffmpeg_bin, ffprobe_bin, has_encoder, has_filter, run_ffmpeg
from .core.logging_utils import _RedactFilter, attach_run_log, console, get_logger, redact
from .core.media_probe import probe
from .core.project import ProjectContext, scaffold
from .core.schema import Project

app = typer.Typer(
    help="AI Shorts Studio - multi-workflow short/long video pipeline.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
voices_app = typer.Typer(help="Manage voices (free / api / local models).", no_args_is_help=True)
discover_app = typer.Typer(
    help="Find hot posts through official APIs (you choose what to render).", no_args_is_help=True
)
nodes_app = typer.Typer(help="Worker machines from config/nodes.yaml.", no_args_is_help=True)
jobs_app = typer.Typer(help="Jobs on worker nodes (list / pull results / cancel).", no_args_is_help=True)
worker_app = typer.Typer(help="Run this machine as a studio-worker node.", no_args_is_help=True)
app.add_typer(voices_app, name="voices")
app.add_typer(discover_app, name="discover")
app.add_typer(nodes_app, name="nodes")
app.add_typer(jobs_app, name="jobs")
app.add_typer(worker_app, name="worker")

ProjectArg = Annotated[Path, typer.Argument(help="Project folder (contains project.json)")]


def _guard(fn: Callable[[], int | None]) -> None:
    """Run a command body and turn StudioError into a clean message + the right exit code."""
    try:
        code = fn() or EXIT_OK
    except ManualGateRequired as e:
        console.print(f"[yellow]WAITING MANUAL[/] {escape(redact(str(e)))}")
        code = e.exit_code
    except WaitingForNode as e:
        console.print(f"[yellow]WAITING NODE[/] {escape(redact(str(e)))}")
        code = e.exit_code
    except StudioError as e:  # messages may quote URLs or CLI output: never print a token
        console.print(f"[red]FAILED[/] {escape(redact(str(e)))}")
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
    for mod, label in (
        ("edge_tts", "edge-tts"),
        ("piper", "piper-tts [piper]"),
        ("faster_whisper", "faster-whisper [align]"),
        ("fastapi", "fastapi [worker]"),
        ("manim", "manim [manim]"),
    ):
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
    add(
        "LaTeX (manim formulas, optional)",
        True if shutil.which("latex") else None,
        "not needed: formulas fall back to Unicode text",
    )
    add(".env", True if (s.root / ".env").exists() else None, "copy .env.example -> .env for API keys")
    if gpu:
        smi = shutil.which("nvidia-smi")
        if smi:
            q = subprocess.run(
                [smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                capture_output=True,
                text=True,
            )
            add("nvidia-smi", q.returncode == 0, q.stdout.strip() or q.stderr.strip())
        else:
            add("nvidia-smi", False, "no NVIDIA driver found")
        if has_encoder("h264_nvenc"):
            try:
                run_ffmpeg(
                    ["-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.5", "-c:v", "h264_nvenc", "-f", "null", "-"],
                    stage="doctor",
                )
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
        t.add_row(
            wf["name"],
            str(wf.get("tier", "")),
            f"[green]{st}[/]" if st == "ready" else f"[yellow]{st}[/]",
            ", ".join(wf.get("formats", [])),
            str(wf.get("cost", "")),
            str(wf.get("description", "")),
        )
    console.print(t)


@app.command()
def topics() -> None:
    """List knowledge topic packs (workflows/_shared/topics) for knowledge_explainer --topic."""
    from .workflows.topics import list_topics

    t = Table(title="topics")
    for c in ("id", "name", "review", "sources", "disclaimer", "templates"):
        t.add_column(c, overflow="fold")
    for tp in list_topics(get_settings()):
        t.add_row(
            tp.id,
            tp.label("vi"),
            "yes" if tp.review_required else "no",
            "required" if tp.require_sources else "-",
            ("on screen" if tp.disclaimer_on_screen else "description") if tp.disclaimer else "-",
            str(len(tp.templates)),
        )
    console.print(t)


@app.command()
def new(
    workflow: Annotated[str, typer.Argument(help="story_reader | ai_cinematic | ... (see `studio workflows`)")],
    name: Annotated[str, typer.Argument(help="Short name; becomes the folder slug")],
    fmt: Annotated[list[str], typer.Option("--format", "-f", help="Repeat for several outputs")] = None,
    lang: Annotated[str, typer.Option("--lang", help="vi | en")] = "vi",
    text_file: Annotated[Path | None, typer.Option("--text-file", help="Source text (copied to source/)")] = None,
    url: Annotated[str | None, typer.Option("--url", help="Source URL (Reddit uses the official API)")] = None,
    brief_file: Annotated[
        Path | None, typer.Option("--brief-file", help="Brief file (ai_cinematic, knowledge_explainer)")
    ] = None,
    brief: Annotated[str | None, typer.Option("--brief", help="Brief as text (stored in options.brief)")] = None,
    topic: Annotated[str | None, typer.Option("--topic", help="Knowledge topic (see `studio topics`)")] = None,
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
        if brief:
            options["brief"] = brief
        if topic:
            options["topic"] = topic
        base = f"{datetime.now():%Y%m%d}_{slugify(name)}"
        created = []
        for f in formats:
            suffix = f"_{f.split('_')[0]}" if len(formats) > 1 else ""
            pid = (base + suffix)[:64]
            pdir = out_dir or (s.path("projects") / workflow / pid)
            data = deep_merge(
                project_defaults(wf, f),
                {
                    "project_id": pid,
                    "workflow": workflow,
                    "language": lang,
                    "title": "",
                    "video": {"format": f},
                    "options": options,
                    "budget": {"max_cost_usd": float(s.get("budget.default_max_cost_usd", 0))},
                },
            )
            if voice:
                data.setdefault("audio", {})["voice_profile"] = voice
            elif not data.get("audio", {}).get("voice_profile"):
                from .voices import load_registry

                data.setdefault("audio", {})["voice_profile"] = load_registry(s).default_for(lang, workflow).id
            if data.get("options", {}).get("topic"):
                _apply_topic(s, data, user_options=options)
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


def _apply_topic(s, data: dict, *, user_options: dict | None = None) -> None:
    """Topic pack look (caption style, palette, backdrop, on-screen disclaimer) and option defaults as project
    defaults - editable later. Topic options override the workflow's defaults, never the user's --set."""
    from .workflows.topics import load_topic

    tp = load_topic(s, str(data["options"]["topic"]))
    for key, value in tp.options.items():
        if key not in (user_options or {}):
            data["options"][key] = value
    if tp.caption_style:
        data.setdefault("video", {})["caption_style"] = tp.caption_style
    if tp.palette:
        data["options"].setdefault("palette", tp.palette)
    note = tp.disclaimer_for(data.get("language", "vi"))
    if note and tp.disclaimer_on_screen:
        data["options"].setdefault("on_screen_note", note)


# ------------------------------------------------------------------ pipeline commands


@app.command()
def run(
    project: ProjectArg,
    from_stage: Annotated[str | None, typer.Option("--from", help="Start at this stage")] = None,
    only: Annotated[list[str], typer.Option("--only", help="Run only these stages (repeatable)")] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Regenerate source/script/scenes/storyboard and rebuild render/qc/package even if up to date",
        ),
    ] = False,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Re-synthesize TTS audio")] = False,
    strict: Annotated[bool, typer.Option("--strict", help="QC warnings fail the run")] = False,
    allow_sidecar: Annotated[bool, typer.Option("--allow-sidecar-subs")] = False,
    node: Annotated[
        str | None, typer.Option("--node", help="Run validate/voice/render/qc/package on a worker: 'auto' or a node id")
    ] = None,
    wait: Annotated[bool, typer.Option("--wait/--no-wait", help="Wait for the worker and pull results")] = True,
    timeout_min: Annotated[
        float | None, typer.Option("--timeout", help="Minutes to wait (default remote.wait_timeout_min)")
    ] = None,
    fallback: Annotated[str, typer.Option("--fallback", help="Named node unavailable: local | fail")] = "local",
) -> None:
    """Run the project's workflow (resumable; exit 3 at manual steps, exit 6 while a worker has the job)."""
    from .pipeline.runner import RunOptions, run_pipeline

    def body() -> int:
        ctx = _ctx(project, "run")
        ro = RunOptions(
            from_stage=from_stage,
            only=only or [],
            force=force,
            stage_opts={"overwrite": overwrite, "strict": strict, "allow_sidecar": allow_sidecar},
        )
        if node and node != "local":
            _run_remote(ctx, ro, node, wait=wait, timeout_min=timeout_min, fallback=fallback)
        else:
            run_pipeline(ctx, ro)
        console.print(f"[green]DONE[/] {ctx.final_video}")
        return EXIT_OK

    _guard(body)


def _run_remote(ctx: ProjectContext, ro, node_id: str, *, wait: bool, timeout_min: float | None, fallback: str) -> None:
    from .nodes import NodeUnavailable, select_node
    from .nodes.client import NodeClient
    from .nodes.remote import pull_job, split_stages, submit_project, wait_for_job
    from .pipeline.runner import RunOptions, run_pipeline, select_stages

    if fallback not in ("local", "fail"):
        raise StudioError("--fallback must be local or fail", code="bad_args")
    log = get_logger()
    local_part, remote_part = split_stages(select_stages(ctx, ro))
    try:
        target = select_node(ctx.settings, node_id)
    except NodeUnavailable as e:
        if fallback == "fail":
            raise
        log.warning("%s - running locally (--fallback local)", e)
        target = None
    if target is None or not remote_part:
        if target is None and node_id == "auto":
            log.warning("no worker node is available now - running locally")
        run_pipeline(ctx, ro)
        return
    if local_part:
        run_pipeline(ctx, RunOptions(only=local_part, force=ro.force, stage_opts=ro.stage_opts))
    client = NodeClient.for_node(target)
    job_id = submit_project(ctx, client, remote_part, ro.stage_opts)
    if not wait:
        raise WaitingForNode(f'job {job_id} submitted to {target.id} - later: studio jobs pull "{ctx.dir}"')
    s = ctx.settings
    wait_for_job(
        client,
        job_id,
        poll_sec=float(s.get("remote.poll_sec", 10)),
        timeout_sec=60 * float(timeout_min or s.get("remote.wait_timeout_min", 180)),
    )
    pull_job(ctx, client, job_id)


@app.command()
def approve(project: ProjectArg) -> None:
    """Mark the script as fact-checked (options.reviewed = true) so the review gate passes."""

    def body() -> int:
        ctx = _ctx(project, "approve")
        if not ctx.project.scenes:
            raise StudioError("nothing to approve: the project has no scenes yet - run it first", code="no_scenes")
        from .core.user_review import require

        require(ctx.dir, "script")
        ctx.project.options["reviewed"] = True
        ctx.save()
        console.print(f'[green]approved[/] {len(ctx.project.scenes)} scenes - next: studio run "{project}"')
        return EXIT_OK

    _guard(body)


@app.command()
def validate(
    project: ProjectArg, media: Annotated[bool, typer.Option(help="Require media files to exist")] = True
) -> None:
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
        if ctx.settings.get("reviews.required", True) and stage in ("voice", "render"):
            from .core.user_review import checkpoint

            checkpoint(ctx.dir, "script" if stage == "voice" else "voice")
        if ctx.settings.get("planning.required", False) and stage in ("voice", "render"):
            from .core.creative_brief import ensure_ready

            ensure_ready(ctx.dir)
        if ctx.project.audio.source != "manual" and stage in ("voice", "render"):
            from .pipeline.voice import choose_profile
            from .voices import load_registry

            choose_profile(ctx, load_registry(ctx.settings))
        if ctx.settings.get("planning.required", False) and stage == "render":
            from .core.creative_brief import reserve_render

            reserve_render(ctx.dir, "single-stage-render")
        ctx.set_stage(stage, "running")
        tracked = stage == "render" and ctx.settings.get("planning.required", False)
        try:
            msg = get_stages()[stage](ctx, opts)
        except Exception as e:
            if tracked:
                from .core.creative_brief import finish_render

                finish_render(ctx.dir, False)
            ctx.set_stage(stage, "failed", str(e))
            raise
        if tracked:
            from .core.creative_brief import finish_render

            finish_render(ctx.dir, True)
        ctx.set_stage(stage, "done", msg)
        if ctx.settings.get("reviews.required", True) and stage in ("voice", "render"):
            from .core.user_review import checkpoint

            gate = "voice" if stage == "voice" else "final"
            if stage == "render":
                from .core.qc import run_qc

                run_qc(ctx)
            checkpoint(ctx.dir, gate)
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
        final = ctx.final_video
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
        t.add_row(p.id, p.lang, p.tier, p.provider, st, p.location, inst, f"{p.cost_per_1k_chars:g}", p.fallback or "")
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


@voices_app.command("audition")
def voices_audition(voice_id: str, text: Annotated[str | None, typer.Option("--text")] = None) -> None:
    """Create a quarantined local sample; never approve a voice for production."""

    def body() -> int:
        from .core.voice_audition import DEFAULT_TEXT, audition_sample
        from .voices import load_registry

        registry = load_registry(get_settings())
        sample = audition_sample(registry, registry.get(voice_id), text or DEFAULT_TEXT)
        console.print(f"[yellow]QUARANTINED[/] {sample} ({probe(sample).duration:.2f}s); listening review required")
        return EXIT_OK

    _guard(body)


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
    from .providers.source import save_threads_posts, threads_discover

    def body() -> int:
        s = get_settings()
        posts = threads_discover(query, limit=limit)
        save_threads_posts(s.path("cache"), posts)  # the API cannot fetch a post by URL later
        _print_posts(posts, f"threads: {query}")
        return EXIT_OK

    _guard(body)


# ------------------------------------------------------------------ nodes / jobs / worker


@nodes_app.command("status")
def nodes_status() -> None:
    """Show every node: enabled, token present, schedule, health, queue, GPU."""
    from .nodes import check_node, load_nodes

    def body() -> int:
        table = Table("node", "role", "url", "schedule now", "status", "queue", "gpu")
        for n in load_nodes(get_settings()).values():
            if not n.is_worker:
                table.add_row(n.id, n.role, "-", "-", "controller", "-", "-")
                continue
            ok, reason, h = check_node(n)
            q = h.get("queue") or {}
            queue = f"{q.get('queued', 0)} queued / {q.get('running', 0)} running" if h else "-"
            g = h.get("gpu") or {}
            gpu = f"{g['name']} {g['util_pct']}% {g['mem_used_mb']}/{g['mem_total_mb']} MB" if g else "-"
            if ok:
                status_txt = f"[green]{reason}[/]" + (f" - {h['paused_reason']}" if h.get("paused_reason") else "")
            else:
                status_txt = f"[red]{reason}[/]"
            table.add_row(
                n.id, n.role, n.url or "-", "open" if n.schedule.is_open() else "closed", status_txt, queue, gpu
            )
        console.print(table)
        return EXIT_OK

    _guard(body)


def _client(node_id: str):
    from .nodes import get_node
    from .nodes.client import NodeClient

    return NodeClient.for_node(get_node(get_settings(), node_id))


def _worker_nodes(node_id: str | None) -> list[str]:
    from .nodes import load_nodes

    if node_id:
        return [node_id]
    return [n.id for n in load_nodes(get_settings()).values() if n.is_worker and n.enabled and n.token]


@jobs_app.command("list")
def jobs_list(
    node: Annotated[str | None, typer.Option("--node")] = None, limit: Annotated[int, typer.Option("--limit")] = 20
) -> None:
    """Jobs on the worker node(s), newest first."""
    from .nodes.remote import load_index

    def body() -> int:
        idx = load_index(get_settings())
        table = Table("node", "job", "status", "stage", "project", "created", "finished", "project folder")
        for nid in _worker_nodes(node):
            try:
                jobs = _client(nid).jobs(limit)
            except StudioError as e:
                console.print(f"[red]{nid}[/]: {e}")
                continue
            for j in jobs:
                table.add_row(
                    nid,
                    j["id"],
                    j["status"],
                    j.get("stage") or "",
                    j.get("project_id") or "",
                    j.get("created_at") or "",
                    j.get("finished_at") or "",
                    idx.get(j["id"], {}).get("project_dir", "-"),
                )
        console.print(table)
        return EXIT_OK

    _guard(body)


def _resolve_job(target: str, node: str | None) -> tuple[str, str, Path | None]:
    """TARGET = project folder (work/remote_job.json) or job id (cache/remote_jobs.json)."""
    from .nodes.remote import load_index

    rec_file = Path(target) / "work" / "remote_job.json"
    if rec_file.is_file():
        rec = json.loads(rec_file.read_text(encoding="utf-8"))
        return rec["job_id"], node or rec["node"], Path(target)
    idx = load_index(get_settings()).get(target)
    if idx:
        return target, node or idx["node"], Path(idx["project_dir"])
    if node:
        return target, node, None
    raise StudioError(
        f"'{target}' is neither a project with work/remote_job.json nor a known job id "
        "(pass --node for a job submitted from another machine)",
        code="unknown_job",
    )


@jobs_app.command("pull")
def jobs_pull(
    target: Annotated[str, typer.Argument(help="Project folder or job id")],
    node: Annotated[str | None, typer.Option("--node")] = None,
) -> None:
    """Download a finished job's results into its project (locally edited files are kept, see *.remote.*)."""
    from .nodes.remote import pull_job

    def body() -> int:
        job_id, nid, proj = _resolve_job(target, node)
        if proj is None:
            raise StudioError(f"unknown project folder for job {job_id} - pass the project folder", code="unknown_job")
        ctx = _ctx(proj, "pull")
        pull_job(ctx, _client(nid), job_id)
        console.print(f"[green]PULLED[/] {job_id} -> {ctx.dir / 'output'}")
        return EXIT_OK

    _guard(body)


@jobs_app.command("cancel")
def jobs_cancel(
    target: Annotated[str, typer.Argument(help="Project folder or job id")],
    node: Annotated[str | None, typer.Option("--node")] = None,
) -> None:
    """Cancel a queued job (a running job stops before its next stage)."""

    def body() -> int:
        job_id, nid, _ = _resolve_job(target, node)
        r = _client(nid).cancel(job_id)
        console.print(f"{job_id} on {nid}: {r['status']}")
        return EXIT_OK

    _guard(body)


@worker_app.command("serve")
def worker_serve(
    host: Annotated[str | None, typer.Option("--host", help="Bind address (default worker.host)")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
    ignore_schedule: Annotated[bool, typer.Option("--ignore-schedule", help="Run jobs at any time")] = False,
    log_file: Annotated[Path | None, typer.Option("--log-file", help="Also append the worker log here")] = None,
) -> None:
    """Start the HTTP worker + job loop on this machine (normally via scripts/install_worker.ps1)."""
    import logging
    import threading

    def body() -> int:
        if log_file:
            # a plain StreamHandler: per-job run logs replace FileHandlers, this one must survive them
            log_file.parent.mkdir(parents=True, exist_ok=True)
            h = logging.StreamHandler(log_file.open("a", encoding="utf-8"))
            h.setLevel(logging.INFO)
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
            h.addFilter(_RedactFilter())
            get_logger()  # set up the studio logger first: it skips its own setup once a handler exists
            for name in ("studio", "uvicorn"):
                logging.getLogger(name).addHandler(h)
        try:
            import uvicorn

            from .worker.app import create_app
            from .worker.service import WorkerService
        except ImportError as e:
            raise StudioError(
                f'worker extra not installed: uv pip install -e ".[worker]" ({e})', code="missing_extra"
            ) from e
        s = get_settings()
        bind = host or s.get("worker.host", "127.0.0.1")
        if bind in ("0.0.0.0", "::") and not s.get("worker.allow_any_interface", False):
            raise StudioError(
                "refusing to listen on every interface - bind the Tailscale IP "
                "(or set worker.allow_any_interface: true if you really mean it)",
                code="worker_bind",
            )
        service = WorkerService(s, ignore_schedule=ignore_schedule or None)
        stop = threading.Event()
        loop = threading.Thread(target=service.loop, args=(stop,), name="studio-worker-loop", daemon=True)
        loop.start()
        p = port or int(s.get("worker.port", 8765))
        console.print(f"studio-worker [bold]{service.node_id}[/] on http://{bind}:{p}  data: {service.data_dir}")
        get_logger().info("[worker] %s listening on http://%s:%s (data %s)", service.node_id, bind, p, service.data_dir)
        try:
            uvicorn.run(create_app(service), host=bind, port=p, log_level="warning")
        finally:
            stop.set()
            loop.join(timeout=30)
        return EXIT_OK

    _guard(body)


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"studio {__version__} (python {platform.python_version()}, {os.name})")


@app.command("brief")
def brief_command(
    project: Path,
    interactive: bool = False,
    detailed: bool = False,
    answers: Path | None = None,
    accept_recommendations: bool = False,
    approve: bool = False,
    reviewer: str = "",
    reset_budget: bool = False,
    reason: str = "",
):
    """Interview the creator and approve a concrete creative brief before generation."""
    from .core import creative_brief as cb

    def body():
        folder = project.resolve()
        supplied = json.loads(answers.read_text(encoding="utf-8-sig")) if answers else {}
        data = cb.prepare(folder, supplied, accept_recommendations=accept_recommendations)
        if interactive:
            fields = list(cb.LABELS) if detailed else data["missing"]
            updates = {}
            for key in fields:
                default = data["answers"][key] or data["recommendations"][key]
                field = cb.Brief.model_fields[key]
                choices = getattr(field.annotation, "__args__", ())
                suffix = " [" + " / ".join(map(str, choices)) + "]" if choices else ""
                updates[key] = typer.prompt(cb.LABELS[key] + suffix, default=str(default))
            data = cb.prepare(folder, updates)
        console.print((folder / "VIDEO_BRIEF.md").read_text(encoding="utf-8"))
        if approve:
            cb.preflight(folder)
            data = cb.approve(folder, reviewer)
            console.print("Brief approved: " + data["approved_fingerprint"][:12])
        if reset_budget:
            if not reason.strip():
                raise ValidationError("--reason is required to grant another render", code="brief_incomplete")
            ledger = cb._read(folder / "generation_budget.json", {"attempts": []})
            ledger.setdefault("resets", []).append({"reason": reason, "attempts": ledger["attempts"]})
            ledger["attempts"] = []
            cb._write(folder / "generation_budget.json", ledger)
        return EXIT_OK

    _guard(body)


@app.command("preflight")
def preflight_command(project: Path):
    """Generate static storyboard/estimates only: no TTS, model calls or video render."""
    from .core.creative_brief import preflight

    _guard(lambda: (console.print(preflight(project.resolve())), EXIT_OK)[1])


@app.command("review")
def review_command(project: Path, stage: str = "script", action: str = "prepare", message: str = ""):
    """Three user-owned checkpoints. Approve only following an actual user response."""
    from .core import user_review

    def body():
        if stage not in user_review.STAGES:
            raise ValidationError("stage must be script, voice or final", code="review_stage")
        if action == "prepare":
            result = user_review.prepare(project, stage)
        elif action == "approve":
            result = user_review.approve(project, stage, message)
        else:
            raise ValidationError("action must be prepare or approve", code="review_action")
        console.print(result)
        return EXIT_OK

    _guard(body)


# Native social video commands (approved merged Threads + Reddit).
from .social_video.commands import register as _register_social  # noqa: E402

_register_social(app)

if __name__ == "__main__":
    app()
