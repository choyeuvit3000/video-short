"""Worker node registry (config/nodes.yaml): schedules and node selection for `studio run --node`.

Tokens never live in nodes.yaml - each node names an environment variable (`token_env`) read from .env.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..core.config import Settings, load_yaml
from ..core.errors import StudioError, ValidationError

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WINDOW_RE = re.compile(r"^\s*(?P<days>[a-z,\-*]+)\s+(?P<start>\d{1,2}:\d{2})\s*-\s*(?P<end>\d{1,2}:\d{2})\s*$")


class NodeUnavailable(StudioError):
    pass


def _parse_days(spec: str) -> set[int]:
    if spec in ("*", "daily", "all"):
        return set(range(7))
    out: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            if a not in DAYS or b not in DAYS:
                raise ValidationError(f"bad day range '{part}'", code="bad_schedule")
            i, j = DAYS.index(a), DAYS.index(b)
            out.update(DAYS.index(d) for d in (DAYS[i:j + 1] if i <= j else DAYS[i:] + DAYS[:j + 1]))
        else:
            if part not in DAYS:
                raise ValidationError(f"bad day '{part}'", code="bad_schedule")
            out.add(DAYS.index(part))
    return out


def _hm(s: str) -> time:
    h, m = (int(x) for x in s.split(":"))
    if h == 24 and m == 0:
        return time(23, 59, 59)
    return time(h, m)


@dataclass(frozen=True)
class Window:
    """`mon-fri 08:30-17:30`; an end before the start wraps past midnight (the days are start days)."""

    days: frozenset[int]
    start: time
    end: time

    @classmethod
    def parse(cls, text: str) -> Window:
        t = text.strip().lower()
        if t in ("always", "*", "daily"):
            return cls(frozenset(range(7)), time(0, 0), time(23, 59, 59))
        m = _WINDOW_RE.match(t)
        if not m:
            raise ValidationError(f"bad schedule window '{text}' - expected e.g. 'mon-fri 08:30-17:30'",
                                  code="bad_schedule")
        return cls(frozenset(_parse_days(m["days"])), _hm(m["start"]), _hm(m["end"]))

    def contains(self, local: datetime) -> bool:
        t = local.time()
        if self.start <= self.end:
            return local.weekday() in self.days and self.start <= t <= self.end
        # overnight: today after start, or after midnight belonging to yesterday's window
        if local.weekday() in self.days and t >= self.start:
            return True
        return (local.weekday() - 1) % 7 in self.days and t <= self.end


@dataclass
class Schedule:
    timezone: str = "UTC"
    windows: list[Window] = field(default_factory=list)  # empty = always

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> Schedule:
        raw = raw or {}
        tz = raw.get("timezone") or "UTC"
        try:
            ZoneInfo(tz)
        except Exception as e:  # ZoneInfoNotFoundError / ValueError
            raise ValidationError(f"unknown timezone '{tz}' (pip install tzdata on Windows)",
                                  code="bad_schedule") from e
        return cls(tz, [Window.parse(w) for w in raw.get("windows") or []])

    def local(self, now: datetime | None = None) -> datetime:
        now = now or datetime.now(ZoneInfo("UTC"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("UTC"))
        return now.astimezone(ZoneInfo(self.timezone))

    def is_open(self, now: datetime | None = None) -> bool:
        if not self.windows:
            return True
        loc = self.local(now)
        return any(w.contains(loc) for w in self.windows)

    def next_open(self, now: datetime | None = None, horizon_days: int = 8) -> datetime | None:
        """Start of the next window (local time), or None if already open / never opens."""
        if self.is_open(now):
            return None
        loc = self.local(now)
        best: datetime | None = None
        for d in range(horizon_days):
            day = (loc + timedelta(days=d)).date()
            for w in self.windows:
                if day.weekday() in w.days:
                    cand = datetime.combine(day, w.start, tzinfo=loc.tzinfo)
                    if cand > loc and (best is None or cand < best):
                        best = cand
        return best


@dataclass
class Node:
    id: str
    role: str = "worker"
    enabled: bool = True
    url: str | None = None
    token_env: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    schedule: Schedule = field(default_factory=Schedule)
    policy: dict[str, Any] = field(default_factory=dict)

    @property
    def token(self) -> str | None:
        return os.environ.get(self.token_env) if self.token_env else None

    @property
    def is_worker(self) -> bool:
        return self.role == "worker"

    @property
    def services(self) -> list[str]:
        return list(self.capabilities.get("services") or [])


def load_nodes(settings: Settings) -> dict[str, Node]:
    raw = load_yaml(settings.root / "config" / "nodes.yaml").get("nodes") or []
    # config/local.yaml `nodes:` patches a node by id (e.g. enabled/url on this machine) or adds a new one
    local_over = {n.get("id"): n for n in (settings.get("nodes") or []) if isinstance(n, dict)}
    known = {n.get("id") for n in raw}
    nodes: dict[str, Node] = {}
    for item in [*raw, *(n for i, n in local_over.items() if i not in known)]:
        item = {**item, **local_over.get(item.get("id"), {})}
        if not item.get("id"):
            raise ValidationError("every node in config/nodes.yaml needs an id", code="config_error")
        nodes[item["id"]] = Node(
            id=item["id"], role=item.get("role", "worker"), enabled=bool(item.get("enabled", True)),
            url=item.get("url"), token_env=item.get("token_env"),
            capabilities=dict(item.get("capabilities") or {}),
            schedule=Schedule.from_dict(item.get("schedule")), policy=dict(item.get("policy") or {}),
        )
    return nodes


def get_node(settings: Settings, node_id: str) -> Node:
    nodes = load_nodes(settings)
    if node_id not in nodes:
        raise ValidationError(f"unknown node '{node_id}'. Known: {', '.join(nodes) or '-'}", code="unknown_node")
    return nodes[node_id]


def check_node(node: Node, *, client_factory=None, timeout: float = 5.0) -> tuple[bool, str, dict]:
    """(usable, reason, health). Usable = enabled worker, token set, /v1/health answers with auth."""
    if not node.is_worker:
        return False, "controller", {}
    if not node.enabled:
        return False, "disabled in nodes.yaml", {}
    if not node.url:
        return False, "no url", {}
    if not node.token:
        return False, f"{node.token_env or 'token_env'} not set in .env", {}
    from .client import NodeClient

    try:
        client = client_factory(node) if client_factory else NodeClient.for_node(node, timeout=timeout)
        health = client.health()
    except StudioError as e:
        return False, str(e), {}
    return True, "online" if health.get("in_schedule", True) else "online, outside schedule", health


def select_node(settings: Settings, wanted: str = "auto", *, required_service: str | None = None,
                client_factory=None) -> Node | None:
    """`auto` -> first usable worker that is inside its schedule (None if there is none).
    A named node must be usable (but may be outside its schedule - the job then waits in its queue)."""
    nodes = load_nodes(settings)
    if wanted not in ("auto", None):
        node = get_node(settings, wanted)
        ok, reason, _ = check_node(node, client_factory=client_factory)
        if not ok:
            raise NodeUnavailable(f"node '{wanted}' is not available: {reason}", code="node_unavailable")
        return node
    for node in nodes.values():
        if required_service and required_service not in node.services:
            continue
        ok, _, health = check_node(node, client_factory=client_factory)
        if ok and health.get("accepting", True) and health.get("in_schedule", True):
            return node
    return None
