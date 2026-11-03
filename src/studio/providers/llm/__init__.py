"""Text/JSON generation through the AI CLIs you already pay for (no API keys) + a manual fallback.

Each provider receives a prompt and a JSON schema and must return a dict. A file
work/llm/<task>.response.json always wins: edit it by hand to override any AI answer.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ...core.errors import ManualGateRequired, ProviderUnavailable
from ...core.logging_utils import get_logger
from ...core.project import ProjectContext

log = get_logger()


def extract_json(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.S)
    if fence:
        return json.loads(fence.group(1))
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start >= 0:
        end = max(text.rfind("}"), text.rfind("]"))
        return json.loads(text[start:end + 1])
    raise ValueError("no JSON found in model output")


def _run(cmd: list[str], *, stdin: str, timeout: float) -> str:
    log.debug("llm cmd: %s", " ".join(cmd[:3]) + " ...")
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, cwd=tempfile.gettempdir())
    if proc.returncode != 0:
        raise ProviderUnavailable(f"{cmd[0]} exit {proc.returncode}: {(proc.stderr or proc.stdout)[-600:]}",
                                  code="llm_failed")
    if not proc.stdout.strip():
        raise ProviderUnavailable(f"{cmd[0]} printed nothing (exit 0): {proc.stderr[-600:] or 'no stderr'}",
                                  code="llm_bad_output")
    return proc.stdout


class LLMProvider:
    name = "base"

    def __init__(self, settings):
        self.settings = settings
        self.cfg = settings.get(f"llm.{self.name}", {}) or {}
        self.timeout = float(self.cfg.get("timeout_sec") or settings.get("llm.timeout_sec", 300))

    @property
    def command(self) -> str:
        return self.cfg.get("command") or self.name.split("_")[0]

    def check(self) -> str | None:
        return None if shutil.which(self.command) else f"`{self.command}` CLI not found on PATH"

    def generate(self, prompt: str, schema: dict) -> dict:
        raise NotImplementedError


def _unwrap(out: str) -> Any:
    """CLIs wrap answers differently; accept structured_output / result / response / raw JSON."""
    try:
        data = extract_json(out)
    except (ValueError, json.JSONDecodeError) as e:
        tail = " ".join(out.split())[-300:] or "(empty output)"
        raise ProviderUnavailable(f"no JSON in CLI output: {tail}", code="llm_bad_output") from e
    if isinstance(data, dict):
        for k in ("structured_output", "structuredOutput"):
            if isinstance(data.get(k), dict):
                return data[k]
        if str(data.get("status") or "SUCCESS").upper() not in ("SUCCESS", "OK"):  # agy: status ERROR/...
            raise ProviderUnavailable(f"CLI status {data.get('status')}: {str(data.get('response'))[:300]}",
                                      code="llm_failed")
        if data.get("is_error"):
            raise ProviderUnavailable(f"CLI reported an error: {str(data.get('result'))[:400]}", code="llm_failed")
        for k in ("result", "response", "text", "output"):
            if isinstance(data.get(k), str):
                try:
                    return extract_json(data[k])
                except (ValueError, json.JSONDecodeError) as e:
                    tail = " ".join(data[k].split())[:300] or "(empty)"
                    raise ProviderUnavailable(f"answer has no JSON ({k}): {tail}", code="llm_bad_output") from e
    return data


class ClaudeCLI(LLMProvider):
    name = "claude_cli"

    def generate(self, prompt, schema):
        cmd = [self.command, "-p", "--output-format", "json", "--json-schema", json.dumps(schema), "--tools", ""]
        if self.cfg.get("model"):
            cmd += ["--model", self.cfg["model"]]
        return _unwrap(_run(cmd, stdin=prompt, timeout=self.timeout))


class AgyCLI(LLMProvider):
    name = "agy_cli"

    def generate(self, prompt, schema):
        cmd = [self.command, "-p", prompt, "--output-format", "json", "--json-schema", json.dumps(schema)]
        if self.cfg.get("model"):
            cmd += ["--model", self.cfg["model"]]
        return _unwrap(_run(cmd, stdin="", timeout=self.timeout))


class CodexCLI(LLMProvider):
    name = "codex_cli"

    def generate(self, prompt, schema):
        with tempfile.TemporaryDirectory() as td:
            sp, op = Path(td) / "schema.json", Path(td) / "last.txt"
            sp.write_text(json.dumps(_strict_schema(schema)), encoding="utf-8")
            cmd = [self.command, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
                   "--output-schema", str(sp), "-o", str(op), "-"]
            if self.cfg.get("model"):
                cmd[2:2] = ["-m", self.cfg["model"]]
            _run(cmd, stdin=prompt, timeout=self.timeout)
            return extract_json(op.read_text(encoding="utf-8"))


def _strict_schema(schema: dict) -> dict:
    """OpenAI structured outputs want additionalProperties=false and every property required."""
    s = json.loads(json.dumps(schema))

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" not in node:
                # strict mode rejects free-form objects: ask for the object as a JSON string instead
                # (callers such as knowledge._scene_visual decode it)
                node.clear()
                node.update({"type": "string", "description": "a JSON object, encoded as a string"})
                return
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(s)
    return s


PROVIDERS = {p.name: p for p in (ClaudeCLI, AgyCLI, CodexCLI)}


def generate_json(ctx: ProjectContext, task: str, prompt: str, schema: dict, *,
                  chain: list[str] | None = None, force: bool = False) -> tuple[dict, str]:
    """Run `prompt` through the provider chain. Returns (data, provider_name)."""
    llm_dir = ctx.work / "llm"
    llm_dir.mkdir(exist_ok=True)
    resp = llm_dir / f"{task}.response.json"
    prompt_file = llm_dir / f"{task}.prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    (llm_dir / f"{task}.schema.json").write_text(json.dumps(schema, indent=1), encoding="utf-8")
    if resp.exists() and not force:
        log.info("[llm][%s] using existing %s", task, resp.relative_to(ctx.dir))
        return json.loads(resp.read_text(encoding="utf-8-sig")), "file"

    # providers.llm (config/local.yaml) is the machine allow-list; the workflow chain (or the project's
    # options.llm_chain, e.g. `--set llm_chain=codex_cli,agy_cli`) only orders it
    allowed = ctx.settings.get("providers.llm", ["claude_cli", "manual"])
    override = ctx.project.options.get("llm_chain")
    if isinstance(override, str):
        override = [x.strip() for x in override.split(",") if x.strip()]
    chain = override or chain
    chain = [name for name in (chain or allowed) if name in allowed or name == "manual"]
    errors = []
    for name in chain:
        if name == "manual":
            break
        cls = PROVIDERS.get(name)
        if not cls:
            continue
        prov = cls(ctx.settings)
        reason = prov.check()
        if reason:
            errors.append(f"{name}: {reason}")
            continue
        try:
            log.info("[llm][%s] asking %s ...", task, name)
            data = prov.generate(prompt, schema)
            if not isinstance(data, dict):
                raise ValueError("model did not return a JSON object")
            resp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return data, name
        except (ProviderUnavailable, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            log.warning("[llm][%s] %s failed: %s", task, name, e)
            errors.append(f"{name}: {e}")
    instructions = (
        f"### LLM task `{task}`\n\n"
        f"No AI CLI could answer ({'; '.join(errors) or 'manual mode'}).\n\n"
        f"1. Open `{prompt_file.relative_to(ctx.dir).as_posix()}` and paste it into Claude / ChatGPT / Gemini (web).\n"
        f"2. Save the JSON answer (matching `{task}.schema.json`) as "
        f"`{resp.relative_to(ctx.dir).as_posix()}`.\n"
        f"3. Re-run `studio run \"{ctx.dir}\"`.\n"
    )
    raise ManualGateRequired(task, instructions)
