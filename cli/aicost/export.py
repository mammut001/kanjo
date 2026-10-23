"""Scan all agent logs and assemble the CONTRACT.md JSON document."""

from __future__ import annotations

import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from . import attribution as attr
from .config import Config
from .identity import Resolver, ScratchpadDecoder
from .pricing import PriceBook, default_book
from .sources import antigravity, claude, codex
from . import __version__
from .sources.base import AGENT_LABELS, Message, ParseError, Session, iso_utc, local_day, local_timezone_name

SCHEMA_VERSION = 1
COST_NOTE = "API-equivalent cost estimated from public API prices. Not actual subscription spend."
SOURCES = {"claude": claude, "antigravity": antigravity, "codex": codex}
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write", "thinking")


# ---- scanning ------------------------------------------------------------------
@dataclass
class SourceStats:
    agent: str
    dirs: List[str]
    files: int = 0
    sessions: int = 0
    subagents: int = 0
    failed: int = 0
    messages: int = 0


@dataclass
class ScanResult:
    sessions: List[Session]
    failed_files: List[str]
    stats: Dict[str, SourceStats]


def scan(dirs: Optional[Dict[str, List[str]]] = None, cache=None) -> ScanResult:
    """Parse every log file. ``dirs`` maps agent -> directories (defaults to the
    standard locations, overridable with AICOST_<AGENT>_DIR)."""
    sessions: List[Session] = []
    failed: List[str] = []
    stats: Dict[str, SourceStats] = {}
    for agent, module in SOURCES.items():
        roots = (dirs or {}).get(agent)
        if roots is None:
            roots = module.roots()
        st = SourceStats(agent=agent, dirs=[r for r in roots])
        stats[agent] = st
        for path, parent in module.discover(roots):
            st.files += 1
            try:
                session = cache.get(agent, path, parent, module.parse_file) if cache else module.parse_file(path, parent)
            except ParseError:
                st.failed += 1
                failed.append(path)
                continue
            except Exception:  # unknown format change: count it, never abort the scan
                st.failed += 1
                failed.append(path)
                continue
            st.messages += len(session.messages)
            if session.subagent_of:
                st.subagents += 1
            else:
                st.sessions += 1
            sessions.append(session)
    if cache:
        cache.save()
    return ScanResult(sessions=sessions, failed_files=failed, stats=stats)


def _merge_same_id(sessions: List[Session]) -> List[Session]:
    """Codex can keep one thread in two files (sessions/ and archived_sessions/)."""
    by_key: Dict[Tuple[str, str], Session] = {}
    out: List[Session] = []
    for s in sessions:
        key = (s.agent, s.id)
        first = by_key.get(key)
        if first is None:
            by_key[key] = s
            out.append(s)
            continue
        first.messages.extend(s.messages)
        first.tool_paths.extend(s.tool_paths)
        first.note_time(s.started)
        first.note_time(s.ended)
        if s.origin_ts is not None and (first.origin_ts is None or s.origin_ts < first.origin_ts):
            first.origin_ts = s.origin_ts
        for cwd, n in s.cwd_counts.items():
            first.note_cwd(cwd, n)
        first.remote_hints.update(s.remote_hints)
        first.title = first.title or s.title
        first.branch = first.branch or s.branch
        first.subagent_of = first.subagent_of or s.subagent_of
    return out


def dedupe(sessions: List[Session]) -> List[Session]:
    """Each message key is billed once, in the earliest session that has it
    (resumed / forked sessions copy earlier history; ATTRIBUTION.md section 7)."""
    sessions = _merge_same_id(sessions)
    def order(s: Session):
        t = s.origin_ts if s.origin_ts is not None else s.started
        return (t if t is not None else math.inf, s.agent, s.id)

    sessions.sort(key=order)
    seen = set()
    for s in sessions:
        kept = []
        for m in sorted(s.messages, key=lambda m: m.ts):
            if m.key:
                if m.key in seen:
                    continue
                seen.add(m.key)
            kept.append(m)
        s.messages = kept
    return sessions


# ---- units: a top-level session plus the sub-agents that follow it ----------------
@dataclass
class Unit:
    top: Session
    subs: List[Session] = field(default_factory=list)

    @property
    def messages(self) -> List[Message]:
        msgs = list(self.top.messages)
        for s in self.subs:
            msgs.extend(s.messages)
        return msgs

    # CONTRACT.md: started / ended are the first / last billed message
    @property
    def started(self):
        return min(m.ts for m in self.messages)

    @property
    def ended(self):
        return max(m.ts for m in self.messages)


def build_units(sessions: List[Session]) -> List[Unit]:
    by_id: Dict[Tuple[str, str], Session] = {(s.agent, s.id): s for s in sessions}

    def root_of(s: Session) -> Session:
        seen = set()
        cur = s
        while cur.subagent_of and (cur.agent, cur.subagent_of) in by_id and cur.id not in seen:
            seen.add(cur.id)
            cur = by_id[(cur.agent, cur.subagent_of)]
        return cur

    units: Dict[Tuple[str, str], Unit] = {}
    order: List[Tuple[str, str]] = []
    for s in sessions:
        root = root_of(s)
        key = (root.agent, root.id)
        if key not in units:
            units[key] = Unit(top=root)
            order.append(key)
        if root is not s:
            units[key].subs.append(s)
    result = [units[k] for k in order]
    # sessions with nothing billed (fully de-duplicated forks, aborted runs) carry no cost
    return [u for u in result if u.messages]


# ---- aggregation helpers ----------------------------------------------------------
def _tokens(values: Dict[str, float]) -> Dict[str, int]:
    t = {k: int(round(values.get(k, 0))) for k in TOKEN_FIELDS}
    t["total"] = t["input"] + t["output"] + t["cache_read"] + t["cache_write"]
    return t


def _apportion(total: int, shares: List[float]) -> List[int]:
    """Integer split of ``total`` by ``shares`` that sums exactly to ``total``."""
    raw = [total * s for s in shares]
    base = [int(math.floor(x)) for x in raw]
    rest = total - sum(base)
    order = sorted(range(len(shares)), key=lambda i: (-(raw[i] - base[i]), i))
    for i in order[:max(rest, 0)]:
        base[i] += 1
    return base


class Agg:
    def __init__(self):
        self.cost = 0.0
        self.tokens = defaultdict(float)
        self.sessions = 0
        self.first = None
        self.last = None

    def add_day(self, day: str):
        if self.first is None or day < self.first:
            self.first = day
        if self.last is None or day > self.last:
            self.last = day

    def to_json(self) -> dict:
        return {
            "cost": round(self.cost, 4),
            "tokens": _tokens(self.tokens),
            "sessions": self.sessions,
            "first_active": self.first,
            "last_active": self.last,
        }


class ProjectAgg(Agg):
    def __init__(self):
        super().__init__()
        self.by_agent: Dict[str, Agg] = defaultdict(Agg)
        self.by_model: Dict[Tuple[str, str], Agg] = defaultdict(Agg)
        self.model_estimated: Dict[Tuple[str, str], bool] = {}
        self.by_day: Dict[str, Agg] = defaultdict(Agg)
        self.by_branch: Dict[str, Agg] = defaultdict(Agg)
        self.any_branch = False
        self.details: List[dict] = []


# ---- main entry -------------------------------------------------------------------
def build_export(config: Optional[Config] = None, dirs: Optional[Dict[str, List[str]]] = None,
                 prices: Optional[PriceBook] = None, home: Optional[str] = None,
                 now: Optional[datetime] = None, scan_result: Optional[ScanResult] = None,
                 cache=None, fs_root: Optional[str] = None) -> dict:
    config = config or Config()
    prices = prices or default_book()
    result = scan_result or scan(dirs, cache=cache)
    sessions = dedupe(result.sessions)
    units = build_units(sessions)

    resolver = Resolver(aliases=config.aliases, home=home, fs_root=fs_root)
    scratch = ScratchpadDecoder(fs_root=fs_root)
    for s in sessions:
        for path, remote in s.remote_hints.items():
            resolver.add_remote_hint(path, remote)
    resolver.prewarm(p for s in sessions for p in list(s.cwd_counts) + [x for call in s.tool_paths for x in call])

    projects: Dict[str, ProjectAgg] = defaultdict(ProjectAgg)
    buckets = {attr.UNATTRIBUTED: ProjectAgg(), attr.EXCLUDED: ProjectAgg()}
    totals = Agg()
    unique_sessions = 0

    for unit in units:
        decision = attr.decide(unit.top, resolver, scratch, config)
        unique_sessions += 1
        msgs = unit.messages
        priced = []
        unit_cost = 0.0
        unit_tokens = {k: 0 for k in TOKEN_FIELDS}
        model_cost: Dict[str, float] = defaultdict(float)
        for m in msgs:
            agent = unit.top.agent
            cost, estimated = prices.cost(m.model, agent, m.input, m.output, m.cache_read,
                                          m.cache_write, m.cache_write_1h)
            priced.append((m, cost, estimated))
            unit_cost += cost
            for k in TOKEN_FIELDS:
                unit_tokens[k] += getattr(m, k)
            if m.model != "<synthetic>":
                model_cost[m.model] += cost
            day = local_day(m.ts)
            totals.add_day(day)
        totals.cost += unit_cost
        for k in TOKEN_FIELDS:
            totals.tokens[k] += unit_tokens[k]

        shares = [share for _, share in decision.shares]
        split_tokens = {k: _apportion(unit_tokens[k], shares) for k in TOKEN_FIELDS}
        models = [name for name, _ in sorted(model_cost.items(), key=lambda kv: -kv[1])]
        subagent_count = sum(1 for s in unit.subs if s.messages)

        for idx, (target, share) in enumerate(decision.shares):
            if target in buckets:
                agg = buckets[target]
                kind = "none" if target == attr.UNATTRIBUTED else "excluded"
            else:
                agg = projects[target]
                kind = decision.kind
            s_tokens = {k: split_tokens[k][idx] for k in TOKEN_FIELDS}
            s_cost = unit_cost * share
            agg.cost += s_cost
            agg.sessions += 1
            for k in TOKEN_FIELDS:
                agg.tokens[k] += s_tokens[k]
            agent = unit.top.agent
            if target not in buckets:
                a = agg.by_agent[agent]
                a.cost += s_cost
                a.sessions += 1
                for k in TOKEN_FIELDS:
                    a.tokens[k] += s_tokens[k]
            branches_seen = set()
            for m, cost, estimated in priced:
                day = local_day(m.ts)
                agg.add_day(day)
                if target in buckets:
                    continue
                if m.model != "<synthetic>":
                    mk = (m.model, agent)
                    ma = agg.by_model[mk]
                    ma.cost += cost * share
                    for k in TOKEN_FIELDS:
                        ma.tokens[k] += getattr(m, k) * share
                    agg.model_estimated[mk] = agg.model_estimated.get(mk, False) or estimated
                da = agg.by_day[day]
                da.cost += cost * share
                for k in TOKEN_FIELDS:
                    da.tokens[k] += getattr(m, k) * share
                if m.branch:
                    agg.any_branch = True
                branch = m.branch or "(unknown)"
                ba = agg.by_branch[branch]
                ba.cost += cost * share
                if branch not in branches_seen:
                    branches_seen.add(branch)
                    ba.sessions += 1
            agg.details.append({
                "id": unit.top.id,
                "agent": agent,
                "label": AGENT_LABELS.get(agent, agent),
                "started": iso_utc(unit.started),
                "ended": iso_utc(unit.ended),
                "cwd": unit.top.cwd,
                "branch": unit.top.branch,
                "models": models,
                "cost": round(s_cost, 4),
                "tokens": _tokens(s_tokens),
                "share": 1.0 if target in buckets else round(share, 6),
                "attribution": kind,
                "subagents": subagent_count,
                "title": unit.top.title,
            })

    project_list = []
    for pid, agg in projects.items():
        project = resolver.project(pid) or resolver.ensure_project(pid)
        doc = {
            "id": project.id,
            "name": project.name,
            "remote": project.remote,
            "paths": sorted(project.paths),
            "path_missing": project.path_missing,
        }
        doc.update(agg.to_json())
        doc["by_agent"] = sorted(
            ({"agent": a, "label": AGENT_LABELS.get(a, a), "cost": round(v.cost, 4),
              "tokens": _tokens(v.tokens), "sessions": v.sessions} for a, v in agg.by_agent.items()),
            key=lambda d: (-d["cost"], d["agent"]))
        doc["by_model"] = sorted(
            ({"model": model, "agent": agent, "cost": round(v.cost, 4), "tokens": _tokens(v.tokens),
              "estimated": bool(agg.model_estimated.get((model, agent)))}
             for (model, agent), v in agg.by_model.items()),
            key=lambda d: (-d["cost"], d["model"], d["agent"]))
        doc["by_day"] = [{"day": day, "cost": round(v.cost, 4), "tokens": _tokens(v.tokens)["total"]}
                         for day, v in sorted(agg.by_day.items())]
        doc["by_branch"] = sorted(
            ({"branch": b, "cost": round(v.cost, 4), "sessions": v.sessions} for b, v in agg.by_branch.items()),
            key=lambda d: (-d["cost"], d["branch"])) if agg.any_branch else []
        doc["sessions_detail"] = sorted(agg.details, key=lambda d: d["started"] or "", reverse=True)
        project_list.append(doc)
    project_list.sort(key=lambda d: (-d["cost"], d["name"].lower(), d["id"]))

    def bucket_json(agg: ProjectAgg) -> dict:
        doc = agg.to_json()
        doc["sessions_detail"] = sorted(agg.details, key=lambda d: d["started"] or "", reverse=True)
        return doc

    totals.sessions = sum(p["sessions"] for p in project_list) + sum(b.sessions for b in buckets.values())
    totals_json = totals.to_json()
    totals_json["unique_sessions"] = unique_sessions  # each session once, incl. buckets, excl. parse_failed

    now = now or datetime.now(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "aicost " + __version__,
        "timezone": local_timezone_name(),
        "currency": "USD",
        "cost_note": COST_NOTE,
        "config": {"dominant_threshold": config.dominant_threshold},
        "totals": totals_json,
        "projects": project_list,
        "buckets": {
            "unattributed": bucket_json(buckets[attr.UNATTRIBUTED]),
            "excluded": bucket_json(buckets[attr.EXCLUDED]),
            "parse_failed": {"sessions": len(result.failed_files), "files": sorted(result.failed_files)},
        },
    }


def check_invariants(doc: dict, tolerance: float = 0.01) -> List[str]:
    """Problems with the CONTRACT.md reconciliation invariant (empty = fine)."""
    problems = []
    parts = list(doc["projects"]) + [doc["buckets"]["unattributed"], doc["buckets"]["excluded"]]
    cost = sum(p["cost"] for p in parts)
    if abs(doc["totals"]["cost"] - cost) > tolerance:
        problems.append("cost: totals %.4f != parts %.4f" % (doc["totals"]["cost"], cost))
    for k in ("input", "output", "cache_read", "cache_write", "thinking", "total"):
        s = sum(p["tokens"][k] for p in parts)
        if doc["totals"]["tokens"][k] != s:
            problems.append("tokens.%s: totals %d != parts %d" % (k, doc["totals"]["tokens"][k], s))
    sessions = sum(p["sessions"] for p in parts)
    if doc["totals"]["sessions"] != sessions:
        problems.append("sessions: totals %d != parts %d" % (doc["totals"]["sessions"], sessions))
    costs = [p["cost"] for p in doc["projects"]]
    if costs != sorted(costs, reverse=True):
        problems.append("projects are not sorted by cost descending")
    return problems
