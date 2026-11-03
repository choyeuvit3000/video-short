"""Error types and process exit codes shared by every command."""

from __future__ import annotations

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_VALIDATION = 2
EXIT_WAITING_MANUAL = 3
EXIT_BUDGET = 4
EXIT_QC_FAIL = 5
EXIT_WAITING_NODE = 6


class StudioError(Exception):
    """Base error. `code` is a short machine-readable category, `scene_id` is set when scene-specific."""

    exit_code = EXIT_ERROR

    def __init__(self, message: str, *, code: str = "error", scene_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.scene_id = scene_id

    def __str__(self) -> str:
        base = super().__str__()
        prefix = f"[{self.code}]"
        if self.scene_id:
            prefix += f"[{self.scene_id}]"
        return f"{prefix} {base}"


class ValidationError(StudioError):
    exit_code = EXIT_VALIDATION


class ToolMissingError(StudioError):
    """An external tool (ffmpeg, a CLI, an optional Python package) is not available."""


class FFmpegError(StudioError):
    def __init__(self, message: str, *, returncode: int, stderr_tail: str, scene_id: str | None = None):
        super().__init__(f"{message} (exit {returncode})\n{stderr_tail}", code="ffmpeg_failed", scene_id=scene_id)
        self.returncode = returncode
        self.stderr_tail = stderr_tail


class ManualGateRequired(StudioError):
    """A step needs a human (web UI, paste). Instructions are written to TODO_MANUAL.md."""

    exit_code = EXIT_WAITING_MANUAL

    def __init__(self, stage: str, instructions: str):
        super().__init__(f"Stage '{stage}' is waiting for manual input - see TODO_MANUAL.md", code="waiting_manual")
        self.stage = stage
        self.instructions = instructions


class BudgetExceeded(StudioError):
    exit_code = EXIT_BUDGET


class ProviderUnavailable(StudioError):
    """Provider cannot run right now (offline, no key, node down). The chain tries the next one."""


class QCFailed(StudioError):
    exit_code = EXIT_QC_FAIL


class WaitingForNode(StudioError):
    """Work was handed to a worker node that has not finished yet (queued / outside its schedule)."""

    exit_code = EXIT_WAITING_NODE

    def __init__(self, message: str):
        super().__init__(message, code="waiting_node")
