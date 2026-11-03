"""Per-project cost ledger (cost.json) with a hard budget check before any paid call."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .errors import BudgetExceeded


class CostLedger:
    def __init__(self, project_dir: Path, max_cost_usd: float):
        self.path = project_dir / "cost.json"
        self.max_cost_usd = max_cost_usd
        self.entries: list[dict] = []
        if self.path.exists():
            self.entries = json.loads(self.path.read_text(encoding="utf-8")).get("entries", [])

    @property
    def total(self) -> float:
        return round(sum(float(e.get("usd", 0)) for e in self.entries), 4)

    def ensure(self, usd: float, what: str) -> None:
        """Raise BudgetExceeded if spending `usd` more would pass the project budget."""
        if usd <= 0:
            return
        if self.total + usd > self.max_cost_usd + 1e-9:
            raise BudgetExceeded(
                f"{what} would cost ~${usd:.4f}; spent ${self.total:.4f} of budget ${self.max_cost_usd:.2f}. "
                "Raise budget.max_cost_usd in project.json or pick a free/local provider.",
                code="budget_exceeded",
            )

    def record(self, *, stage: str, provider: str, usd: float, detail: str = "", scene_id: str | None = None) -> None:
        self.entries.append(
            {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "stage": stage,
                "provider": provider,
                "scene_id": scene_id,
                "usd": round(usd, 6),
                "detail": detail,
            }
        )
        self.path.write_text(
            json.dumps({"total_usd": self.total, "max_cost_usd": self.max_cost_usd, "entries": self.entries},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
