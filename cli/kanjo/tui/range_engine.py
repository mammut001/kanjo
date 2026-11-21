"""Range filtering aligned with KanjoCore RangeEngine / Kanjo.Core RangeEngine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import re
from . import calendar_time as cal

TUI_RANGE_TO_PARITY: Dict[str, str] = {
    "all": "all",
    "today": "today",
    "7d": "days7",
    "30d": "days30",
    "reset": "sinceReset",
    "cycle": "billingCycle",
}

PARITY_RANGE_ORDER = list(dict.fromkeys(TUI_RANGE_TO_PARITY.values()))


class ParityTimeRange(str, Enum):
    ALL = "all"
    TODAY = "today"
    DAYS7 = "days7"
    DAYS30 = "days30"
    SINCE_RESET = "sinceReset"
    BILLING_CYCLE = "billingCycle"


def _tui_range_value(tr) -> str:
    return str(getattr(tr, "value", tr))


def parity_range_from_tui(tr) -> ParityTimeRange:
    raw = TUI_RANGE_TO_PARITY.get(_tui_range_value(tr), "all")
    return ParityTimeRange(raw)


def ensure_aware(dt: Optional[datetime], tz=None) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz or timezone.utc)
    return dt


def parse_iso_dt(value: Optional[str], default_tz=None) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    match = re.match(r"^(.*?\.\d{1,6})\d*(.*)$", text)
    if match:
        text = match.group(1) + match.group(2)
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz or timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def get_tz(doc: Optional[dict] = None):
    name = None
    if isinstance(doc, dict):
        name = doc.get("timezone")
    if not name:
        try:
            from ..sources.base import local_timezone_name
            name = local_timezone_name()
        except Exception:
            name = "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        try:
            from ..sources.base import local_zone
            return local_zone(name)
        except Exception:
            return timezone.utc


@dataclass
class RangeSpec:
    range: ParityTimeRange
    tz: Any
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    agent_starts: Dict[str, datetime] = field(default_factory=dict)
    _day_cache: Dict[str, Tuple[datetime, datetime]] = field(default_factory=dict, repr=False)

    @property
    def is_all(self) -> bool:
        return self.range == ParityTimeRange.ALL

    def window(self, agent: str) -> Optional[Tuple[Optional[datetime], Optional[datetime]]]:
        if self.range == ParityTimeRange.ALL:
            return (None, None)
        if self.range in (ParityTimeRange.SINCE_RESET, ParityTimeRange.BILLING_CYCLE):
            if agent not in self.agent_starts:
                return None
            return (self.agent_starts[agent], self.end)
        return (self.start, self.end)

    def includes_day(self, day_start: datetime, day_end: datetime, agent: str) -> bool:
        w = self.window(agent)
        if w is None:
            return False
        w_start, w_end = w
        if w_start is not None and day_end <= w_start:
            return False
        if w_end is not None and day_start >= w_end:
            return False
        return True

    def includes_instant(self, instant: datetime, agent: str) -> bool:
        w = self.window(agent)
        if w is None:
            return False
        w_start, w_end = w
        if w_start is not None and instant < w_start:
            return False
        if w_end is not None and instant >= w_end:
            return False
        return True

    def day_range(self, day: str) -> Optional[Tuple[datetime, datetime]]:
        if day in self._day_cache:
            return self._day_cache[day]
        d = cal.parse_day(day)
        if d is None:
            return None
        rng = cal.day_range(self.tz, d)
        self._day_cache[day] = rng
        return rng

    def includes_session(self, session: dict) -> bool:
        if not isinstance(session, dict):
            return False
        ag = str(session.get("agent") or "")
        w = self.window(ag)
        if w is None:
            return False
        by_day = session.get("by_day")
        if isinstance(by_day, list) and by_day:
            for d in by_day:
                if not isinstance(d, dict):
                    continue
                rng = self.day_range(str(d.get("day") or ""))
                if rng is None:
                    continue
                d0, d1 = rng
                try:
                    c = float(d.get("cost") or 0.0)
                except (TypeError, ValueError):
                    c = 0.0
                try:
                    t = int(d.get("tokens") or 0)
                except (TypeError, ValueError):
                    t = 0
                if self.includes_day(d0, d1, ag) and (c > 0 or t > 0):
                    return True
            return False
        started = parse_iso_dt(session.get("started"), default_tz=self.tz)
        ended = parse_iso_dt(session.get("ended"), default_tz=self.tz) or started
        if not started and not ended:
            return False
        s0 = min(started or ended, ended or started)
        s1 = max(started or ended, ended or started)
        w_start, w_end = w
        if w_start is not None and (s1 < w_start or (s1 == w_start and s0 < s1)):
            return False
        if w_end is not None and s0 >= w_end:
            return False
        return True

    def in_range_cost_and_tokens(self, session: dict) -> Tuple[float, int]:
        if not isinstance(session, dict):
            return 0.0, 0
        if self.is_all:
            return _session_totals(session)
        if not self.includes_session(session):
            return 0.0, 0
        by_day = session.get("by_day")
        if isinstance(by_day, list) and by_day:
            c = 0.0
            t = 0
            ag = str(session.get("agent") or "")
            for d in by_day:
                if not isinstance(d, dict):
                    continue
                rng = self.day_range(str(d.get("day") or ""))
                if rng is None:
                    continue
                if self.includes_day(rng[0], rng[1], ag):
                    try:
                        c += float(d.get("cost") or 0.0)
                    except (TypeError, ValueError):
                        pass
                    try:
                        t += int(d.get("tokens") or 0)
                    except (TypeError, ValueError):
                        pass
            return c, t
        started = parse_iso_dt(session.get("started"), default_tz=self.tz)
        ended = parse_iso_dt(session.get("ended"), default_tz=self.tz) or started
        total_c, total_t = _session_totals(session)
        if not started and not ended:
            return total_c, total_t
        s0 = min(started or ended, ended or started)
        s1 = max(started or ended, ended or started)
        dur = (s1 - s0).total_seconds()
        if dur <= 0:
            return total_c, total_t
        w = self.window(str(session.get("agent") or ""))
        if w is None:
            return 0.0, 0
        w_start, w_end = w
        r0 = w_start or s0
        r1 = w_end or s1
        overlap0 = max(s0, r0)
        overlap1 = min(s1, r1)
        if overlap1 <= overlap0:
            return 0.0, 0
        share = min(1.0, max(0.0, (overlap1 - overlap0).total_seconds() / dur))
        return total_c * share, int(round(total_t * share))


def _session_totals(session: dict) -> Tuple[float, int]:
    try:
        c = float(session.get("cost") or 0.0)
    except (TypeError, ValueError):
        c = 0.0
    toks = session.get("tokens")
    try:
        t = int(toks.get("total", 0) if isinstance(toks, dict) else int(toks or 0))
    except (TypeError, ValueError):
        t = 0
    return c, t


def _token_parts(toks: Any) -> Tuple[int, int, int, int, int, int]:
    if isinstance(toks, dict):
        inp = int(toks.get("input", 0) or 0)
        out = int(toks.get("output", 0) or 0)
        cr = int(toks.get("cache_read", 0) or 0)
        cw = int(toks.get("cache_write", 0) or 0)
        th = int(toks.get("thinking", 0) or 0)
        tot = int(toks.get("total", 0) or 0)
        return inp, out, cr, cw, th, tot
    tot = int(toks or 0) if toks else 0
    return 0, 0, 0, 0, 0, tot


def apportion(total: int, weights: Sequence[float]) -> List[int]:
    if not weights or total <= 0:
        return [0] * len(weights)
    sum_w = sum(weights)
    if sum_w <= 0:
        norm = [1.0 / len(weights)] * len(weights)
    else:
        norm = [w / sum_w for w in weights]
    quotas = [total * w for w in norm]
    integers = [int(w // 1) for w in quotas]
    remainders = sorted(
        ((quotas[i] - integers[i], i) for i in range(len(weights))),
        key=lambda x: (-round(x[0], 9), x[1]),
    )
    leftover = total - sum(integers)
    for _, idx in remainders[: max(0, leftover)]:
        integers[idx] += 1
    return integers


def window_start(quota_entry: Optional[dict], now: datetime, tz) -> Optional[datetime]:
    if not quota_entry or not isinstance(quota_entry, dict):
        return None
    reset_iso = quota_entry.get("weekly_resets_at")
    hours = quota_entry.get("weekly_window_hours", 168)
    try:
        hours = float(hours if hours is not None else 168)
    except (ValueError, TypeError):
        hours = 168.0
    if hours <= 0:
        return None
    reset = parse_iso_dt(reset_iso, default_tz=tz)
    if not reset:
        return None
    now_utc = ensure_aware(now, tz).astimezone(timezone.utc)
    reset_utc = reset.astimezone(timezone.utc)
    if hours == 168:
        diff_days = (now_utc - reset_utc).total_seconds() / (7 * 86400)
        k = math.floor(diff_days)
        start = cal.add_weeks(tz, reset_utc, k)
        while start > now_utc:
            k -= 1
            start = cal.add_weeks(tz, reset_utc, k)
        while cal.add_weeks(tz, reset_utc, k + 1) <= now_utc:
            k += 1
            start = cal.add_weeks(tz, reset_utc, k)
        return start
    period_sec = hours * 3600
    diff = (now_utc - reset_utc).total_seconds()
    kk = int(diff // period_sec) if diff >= 0 else int(diff // period_sec)
    return reset_utc + timedelta(seconds=kk * period_sec)


def date_interval(
    range: ParityTimeRange,
    now: datetime,
    tz,
    quota: Optional[dict] = None,
    subscriptions: Optional[dict] = None,
) -> RangeSpec:
    now = ensure_aware(now, tz)
    today = cal.start_of_day(tz, now)

    def days_back(n: int) -> datetime:
        return cal.add_days(tz, today, -n)

    if range == ParityTimeRange.ALL:
        return RangeSpec(range, tz)
    if range == ParityTimeRange.TODAY:
        return RangeSpec(range, tz, start=days_back(0), end=now)
    if range == ParityTimeRange.DAYS7:
        return RangeSpec(range, tz, start=days_back(6), end=now)
    if range == ParityTimeRange.DAYS30:
        return RangeSpec(range, tz, start=days_back(29), end=now)
    if range == ParityTimeRange.SINCE_RESET:
        starts: Dict[str, datetime] = {}
        for ag, q in (quota or {}).items():
            if isinstance(q, dict):
                s = window_start(q, now, tz)
                if s is not None:
                    starts[str(ag)] = ensure_aware(s, tz)
        return RangeSpec(range, tz, end=now, agent_starts=starts)
    starts = {}
    for ag, sub in (subscriptions or {}).items():
        if isinstance(sub, dict):
            s = parse_iso_dt(sub.get("cycle_start"), default_tz=tz)
            if s is not None:
                starts[str(ag)] = ensure_aware(s, tz)
    return RangeSpec(range, tz, end=now, agent_starts=starts)


def spec_for_tui_range(doc: dict, time_range, now: Optional[datetime] = None) -> RangeSpec:
    doc = doc or {}
    tz = get_tz(doc)
    now = ensure_aware(now, tz) or datetime.now(tz)
    pr = parity_range_from_tui(time_range)
    return date_interval(
        pr, now, tz,
        doc.get("quota_windows"),
        doc.get("subscriptions"),
    )


def dominant_fallback_agent(project: dict) -> str:
    by_agent = project.get("by_agent") or []
    total = 0.0
    top = None
    top_cost = -1.0
    for a in by_agent:
        if not isinstance(a, dict):
            continue
        try:
            c = float(a.get("cost") or 0.0)
        except (TypeError, ValueError):
            c = 0.0
        total += max(c, 0.0)
        if c > top_cost:
            top_cost = c
            top = a
    if total > 0 and top is not None and top_cost > 0:
        return str(top.get("agent") or "unknown")
    if by_agent and isinstance(by_agent[0], dict):
        return str(by_agent[0].get("agent") or "unknown")
    return "unknown"


@dataclass
class FilteredProject:
    project: dict
    cost: float
    tokens: int
    sessions: int
    by_agent: List[dict]
    by_day: List[dict]
    sessions_detail: List[dict]
    first_active: Optional[str]
    last_active: Optional[str]

    @property
    def id(self) -> str:
        return str(self.project.get("id") or "")


@dataclass
class FilteredBucket:
    cost: float
    tokens: int
    sessions: int
    sessions_detail: List[dict]
    first_active: Optional[str]
    last_active: Optional[str]


@dataclass
class FilteredUsage:
    spec: RangeSpec
    projects: List[FilteredProject]
    unattributed: FilteredBucket
    excluded: FilteredBucket
    cost: float
    tokens: int
    sessions: int
    first_active: Optional[str]
    last_active: Optional[str]


def filter_project(p: dict, spec: RangeSpec, fallback_agent: str) -> FilteredProject:
    if spec.is_all:
        toks = p.get("tokens")
        try:
            tok_total = int(toks.get("total", 0) if isinstance(toks, dict) else int(toks or 0))
        except (TypeError, ValueError):
            tok_total = 0
        try:
            cost = float(p.get("cost") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        return FilteredProject(
            p, cost, tok_total, int(p.get("sessions") or 0),
            list(p.get("by_agent") or []), list(p.get("by_day") or []),
            list(p.get("sessions_detail") or []),
            p.get("first_active"), p.get("last_active"),
        )

    agent_cost: Dict[str, float] = {}
    agent_tokens: Dict[str, int] = {}
    agent_sessions: Dict[str, int] = {}
    days: List[dict] = []

    for d in p.get("by_day") or []:
        if not isinstance(d, dict):
            continue
        d_str = str(d.get("day") or "")
        rng = spec.day_range(d_str)
        if rng is None:
            continue
        cost_split = d.get("by_agent") if isinstance(d.get("by_agent"), dict) and d.get("by_agent") else {fallback_agent: d.get("cost", 0.0)}
        token_split = d.get("by_agent_tokens") if isinstance(d.get("by_agent_tokens"), dict) and d.get("by_agent_tokens") else {fallback_agent: d.get("tokens", 0)}

        dc: Dict[str, float] = {}
        dt: Dict[str, int] = {}
        agents = set(cost_split.keys()) | set(token_split.keys())
        for ag in agents:
            if spec.includes_day(rng[0], rng[1], str(ag)):
                if ag in cost_split:
                    try:
                        dc[str(ag)] = float(cost_split[ag] or 0.0)
                    except (TypeError, ValueError):
                        dc[str(ag)] = 0.0
                if ag in token_split:
                    try:
                        dt[str(ag)] = int(token_split[ag] or 0)
                    except (TypeError, ValueError):
                        dt[str(ag)] = 0
        if not dc and not dt:
            continue
        for ag, c in dc.items():
            agent_cost[ag] = agent_cost.get(ag, 0.0) + c
        for ag, t in dt.items():
            agent_tokens[ag] = agent_tokens.get(ag, 0) + t
        days.append({
            "day": d_str,
            "cost": sum(dc.values()),
            "tokens": sum(dt.values()),
            "by_agent": dc,
            "by_agent_tokens": dt,
        })

    sessions = [s for s in (p.get("sessions_detail") or []) if spec.includes_session(s)]
    for s in sessions:
        ag = str(s.get("agent") or fallback_agent)
        agent_sessions[ag] = agent_sessions.get(ag, 0) + 1

    labels: Dict[str, str] = {}
    for s in p.get("sessions_detail") or []:
        if isinstance(s, dict) and s.get("agent"):
            labels[str(s["agent"])] = str(s.get("label") or s["agent"])
    for a in p.get("by_agent") or []:
        if isinstance(a, dict) and a.get("agent"):
            labels[str(a["agent"])] = str(a.get("label") or a["agent"])

    keys = set(agent_cost) | set(agent_tokens) | set(agent_sessions)
    by_agent: List[dict] = []
    for k in keys:
        cost = agent_cost.get(k, 0.0)
        tok = agent_tokens.get(k, 0)
        sess = agent_sessions.get(k, 0)
        if cost > 0 or tok > 0 or sess > 0:
            by_agent.append({
                "agent": k,
                "label": labels.get(k, k),
                "cost": cost,
                "tokens": {"total": tok},
                "sessions": sess,
            })
    by_agent.sort(key=lambda a: (-a["cost"], a["agent"]))

    return FilteredProject(
        p,
        sum(d["cost"] for d in days),
        sum(d["tokens"] for d in days),
        len(sessions),
        by_agent,
        days,
        sessions,
        days[0]["day"] if days else None,
        days[-1]["day"] if days else None,
    )


def filter_bucket(b: dict, spec: RangeSpec, tz) -> FilteredBucket:
    b = b if isinstance(b, dict) else {}
    if spec.is_all:
        toks = b.get("tokens")
        try:
            tok_total = int(toks.get("total", 0) if isinstance(toks, dict) else int(toks or 0))
        except (TypeError, ValueError):
            tok_total = 0
        try:
            cost = float(b.get("cost") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        return FilteredBucket(cost, tok_total, int(b.get("sessions") or 0),
                              list(b.get("sessions_detail") or []),
                              b.get("first_active"), b.get("last_active"))

    ss = [s for s in (b.get("sessions_detail") or []) if spec.includes_session(s)]
    days: List[str] = []
    for s in ss:
        for key in ("started", "ended"):
            dt = parse_iso_dt(s.get(key), default_tz=tz)
            if dt is not None:
                days.append(cal.day_string(tz, dt))
    total_cost = 0.0
    total_tokens = 0
    for s in ss:
        c, t = spec.in_range_cost_and_tokens(s)
        total_cost += c
        total_tokens += t
    return FilteredBucket(
        total_cost, total_tokens, len(ss), ss,
        min(days) if days else None,
        max(days) if days else None,
    )


def filtered_usage(doc: dict, time_range=None, now: Optional[datetime] = None) -> FilteredUsage:
    doc = doc or {}
    tz = get_tz(doc)
    now = ensure_aware(now, tz) or datetime.now(tz)
    spec = spec_for_tui_range(doc, time_range, now=now)

    projects_raw = []
    for i, p in enumerate(doc.get("projects") or []):
        if not isinstance(p, dict):
            continue
        fb = dominant_fallback_agent(p)
        fp = filter_project(p, spec, fb)
        projects_raw.append((i, fp))

    buckets = doc.get("buckets") or {}
    u = filter_bucket(buckets.get("unattributed") or {}, spec, tz)
    e = filter_bucket(buckets.get("excluded") or {}, spec, tz)

    if spec.is_all:
        raw_tot = doc.get("totals") or {}
        try:
            cost = float(raw_tot.get("cost", 0.0) or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        toks = raw_tot.get("tokens") or {}
        try:
            tokens = int(toks.get("total", 0) or 0) if isinstance(toks, dict) else int(toks or 0)
        except (TypeError, ValueError):
            tokens = 0
        try:
            sessions = int(raw_tot.get("sessions", 0) or 0)
        except (TypeError, ValueError):
            sessions = 0
        return FilteredUsage(
            spec, [fp for _, fp in projects_raw], u, e, cost, tokens, sessions,
            raw_tot.get("first_active"), raw_tot.get("last_active"),
        )

    sorted_projects = [fp for _, fp in sorted(projects_raw, key=lambda x: (-x[1].cost, x[0]))]
    days = [d for fp in sorted_projects for d in (fp.first_active, fp.last_active) if d]
    days += [x for x in (u.first_active, u.last_active, e.first_active, e.last_active) if x]

    return FilteredUsage(
        spec,
        sorted_projects,
        u,
        e,
        sum(p.cost for p in sorted_projects) + u.cost + e.cost,
        sum(p.tokens for p in sorted_projects) + u.tokens + e.tokens,
        sum(p.sessions for p in sorted_projects) + u.sessions + e.sessions,
        min(days) if days else None,
        max(days) if days else None,
    )


def build_range_helpers(doc: dict, time_range=None, now: Optional[datetime] = None):
    """Compatibility shim for model.py — same predicate API as legacy _build_range_helpers."""
    doc = doc or {}
    tz = get_tz(doc)
    now = ensure_aware(now, tz) or datetime.now(tz)
    spec = spec_for_tui_range(doc, time_range, now=now)

    def agent_window(ag: str) -> Optional[Tuple[Optional[datetime], Optional[datetime]]]:
        return spec.window(ag)

    def day_included(day_str: str, ag: str) -> bool:
        rng = spec.day_range(str(day_str))
        if rng is None:
            return False
        return spec.includes_day(rng[0], rng[1], ag)

    def session_included(s: dict) -> bool:
        return spec.includes_session(s)

    def session_in_range_cost_tokens(s: dict) -> Tuple[float, int]:
        return spec.in_range_cost_and_tokens(s)

    return tz, now, agent_window, day_included, session_included, session_in_range_cost_tokens


def aggregate_models(filtered: FilteredUsage) -> List[dict]:
    """Port of ModelAggregation.Aggregate — returns list with model, agent, cost, tokens (total), estimated, id."""
    spec = filtered.spec
    model_map: Dict[str, dict] = {}

    def merge(key: str, model: str, agent: str, cost: float, tok_total: int, estimated: bool,
              parts: Optional[Tuple[int, int, int, int, int, int]] = None) -> None:
        if key in model_map:
            cur = model_map[key]
            cur["cost"] += cost
            cur["tokens"] += tok_total
            cur["estimated"] = cur["estimated"] or estimated
        else:
            model_map[key] = {
                "model": model,
                "agent": agent,
                "id": key,
                "cost": cost,
                "tokens": tok_total,
                "estimated": estimated,
            }

    if spec.is_all:
        for fp in filtered.projects:
            for m in fp.project.get("by_model") or []:
                if not isinstance(m, dict):
                    continue
                model = str(m.get("model") or "")
                agent = str(m.get("agent") or "")
                key = f"{agent}/{model}"
                try:
                    mc = float(m.get("cost") or 0.0)
                except (TypeError, ValueError):
                    mc = 0.0
                _, _, _, _, _, tot = _token_parts(m.get("tokens"))
                merge(key, model, agent, mc, tot, bool(m.get("estimated")))

    def process_group(sessions: List[dict], target_cost: float, target_tokens: int) -> None:
        if not sessions:
            return
        if not (target_cost > 0) and target_tokens <= 0:
            return
        raw_pairs = [spec.in_range_cost_and_tokens(s) for s in sessions]
        raw_costs = [c for c, _ in raw_pairs]
        raw_tokens = [float(t) for _, t in raw_pairs]
        sum_c = sum(raw_costs)
        if sum_c > 0:
            sess_costs = [target_cost * (c / sum_c) for c in raw_costs]
        else:
            eq = target_cost / len(sessions)
            sess_costs = [eq] * len(sessions)
        sess_toks = apportion(target_tokens, raw_tokens)

        for idx, s in enumerate(sessions):
            models = s.get("models") or []
            if not models or not isinstance(models, list):
                continue
            sc = sess_costs[idx]
            st = sess_toks[idx]
            if not (sc > 0) and st <= 0:
                continue
            inp, out, cr, cw, th, orig_tot = _token_parts(s.get("tokens"))
            orig_sum = inp + out + cr + cw
            split = apportion(st, [float(inp), float(out), float(cr), float(cw)]) if orig_sum > 0 else [0, 0, 0, 0]
            scaled_th = int(round(th * (st / orig_tot))) if orig_tot > 0 else 0
            ag = str(s.get("agent") or "")
            cnt = len(models)
            if cnt == 1:
                model = str(models[0])
                key = f"{ag}/{model}"
                merge(key, model, ag, sc, st, False)
            else:
                share_c = sc / cnt
                for i, mn in enumerate(models):
                    model = str(mn)

                    def split_field(v: int) -> int:
                        base, rem = divmod(v, cnt)
                        return base + rem if i == 0 else base

                    si, so, scr, scw = (split_field(x) for x in split)
                    sth = split_field(scaled_th)
                    if si + so + scr + scw > 0:
                        split_total = si + so + scr + scw
                    else:
                        split_total = split_field(st)
                    key = f"{ag}/{model}"
                    merge(key, model, ag, share_c, split_total, True)

    # Shared by both ranges: All takes exact project by_model above and only splits bucket sessions.
    for fp in ([] if spec.is_all else filtered.projects):
        # Per (project, agent): each agent splits only its own in-range cost and tokens; the
        # remainder (agents without in-range sessions, or no by_agent) is spread over all sessions.
        rest_cost = fp.cost
        rest_tokens = fp.tokens
        for a in fp.by_agent:
            ag = str(a.get("agent") or "")
            own = [s for s in fp.sessions_detail if str(s.get("agent") or "") == ag]
            if not own:
                continue
            _, _, _, _, _, a_tok = _token_parts(a.get("tokens"))
            a_cost = float(a.get("cost") or 0.0)
            process_group(own, a_cost, a_tok)
            rest_cost -= a_cost
            rest_tokens -= a_tok
        process_group(fp.sessions_detail, rest_cost if rest_cost > 1e-9 else 0.0, max(0, rest_tokens))
    process_group(filtered.unattributed.sessions_detail, filtered.unattributed.cost, filtered.unattributed.tokens)
    process_group(filtered.excluded.sessions_detail, filtered.excluded.cost, filtered.excluded.tokens)

    out = [m for m in model_map.values() if m["tokens"] > 0 or m["cost"] > 0]
    out.sort(key=lambda m: (-m["tokens"], -m["cost"], m["model"]))
    return out