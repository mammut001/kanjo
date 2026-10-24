"""Scoring and decision (ATTRIBUTION.md sections 3, 4 and 5).

* Every tool call contributes 1 point per distinct path it touched to the
  project that path maps to (section 2.2). Paths that map to no project score
  nothing.
* A project with >= ``dominant_threshold`` of the points takes the whole
  session (``dominant``); otherwise the session is split by points (``split``).
* With no points: the cwd's project (``cwd``), then the project encoded in a
  scratchpad path (``scratchpad``), else the unattributed bucket (``none``).
* User overrides and excludes (section 8) are checked first, on the session's
  working directory.
* Sub-agents follow their parent's decision (section 5); that is applied by
  the caller, which only asks for decisions of top-level and orphan sessions.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .config import Config
from .identity import Resolver, ScratchpadDecoder
from .sources.base import Session

UNATTRIBUTED = "__unattributed__"
EXCLUDED = "__excluded__"
_EPS = 1e-9


@dataclass
class Decision:
    kind: str                                   # dominant|split|cwd|scratchpad|override|none|excluded
    shares: List[Tuple[str, float]]             # [(project id or bucket, share)], shares sum to 1
    scores: Dict[str, int] = field(default_factory=dict)


def score(session: Session, resolver: Resolver) -> Counter:
    points: Counter = Counter()
    for call in session.tool_paths:
        for path in set(call):  # the same path twice in one call scores once
            project = resolver.resolve(path)
            if project is not None:
                points[project.id] += 1
    return points


def _ranked_cwds(session: Session) -> List[str]:
    """Message cwds, most used first (first-seen order breaks ties)."""
    order = OrderedDict()
    for cwd, count in session.cwd_counts.items():
        order[cwd] = count
    if session.cwd and session.cwd not in order:
        order[session.cwd] = 0
    items = list(order.items())
    items.sort(key=lambda kv: -kv[1])  # stable sort keeps first-seen order on ties
    return [cwd for cwd, _ in items]


def _cwd_project(session: Session, resolver: Resolver) -> Optional[str]:
    weights: Counter = Counter()
    first_seen: Dict[str, int] = {}
    for rank, cwd in enumerate(_ranked_cwds(session)):
        project = resolver.resolve(cwd, allow_missing_fallback=True)
        if project is not None:
            weights[project.id] += max(session.cwd_counts.get(cwd, 0), 1)
            first_seen.setdefault(project.id, rank)
    if not weights:
        return None
    return max(weights, key=lambda pid: (weights[pid], -first_seen[pid]))


def _scratchpad_project(session: Session, resolver: Resolver, scratch: ScratchpadDecoder) -> Optional[str]:
    weights: Counter = Counter()
    candidates = _ranked_cwds(session) + [p for call in session.tool_paths for p in call]
    for path in candidates:
        decoded = scratch.project_path(path)
        if not decoded:
            continue
        project = resolver.resolve(decoded, allow_missing_fallback=True)
        if project is not None:
            weights[project.id] += 1
    if not weights:
        return None
    return max(weights, key=lambda pid: (weights[pid], pid))


def decide(session: Session, resolver: Resolver, scratch: ScratchpadDecoder, config: Config) -> Decision:
    rule = config.match_override(session.cwd)
    if rule is not None:
        kind, target = rule
        if kind == "exclude":
            return Decision("excluded", [(EXCLUDED, 1.0)])
        project = resolver.ensure_project(target)
        return Decision("override", [(project.id, 1.0)])

    points = score(session, resolver)
    total = sum(points.values())
    if total > 0:
        threshold = config.dominant_threshold
        winners = [pid for pid, pts in points.items() if pts / total >= threshold - _EPS]
        if winners:
            cwd_pid = _cwd_project(session, resolver) if len(winners) > 1 else None
            best = max(winners, key=lambda pid: (pid == cwd_pid, points[pid], pid))
            return Decision("dominant", [(best, 1.0)], dict(points))
        shares = sorted(((pid, pts / total) for pid, pts in points.items()),
                        key=lambda kv: (-kv[1], kv[0]))
        return Decision("split", shares, dict(points))

    pid = _cwd_project(session, resolver)
    if pid:
        return Decision("cwd", [(pid, 1.0)])
    pid = _scratchpad_project(session, resolver, scratch)
    if pid:
        return Decision("scratchpad", [(pid, 1.0)])
    return Decision("none", [(UNATTRIBUTED, 1.0)])
