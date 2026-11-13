"""Pure view-model transformations for the Kanjo TUI."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from enum import Enum
import math
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from ..sources.base import AGENT_LABELS, local_zone, local_timezone_name
from ..providers import provider_for, PROVIDER_LABELS

# Agent colours from ui/Sources/KanjoCore/AgentColors.swift
AGENT_COLORS: Dict[str, Tuple[int, int, int]] = {
    "claude": (0xD9, 0x77, 0x57),
    "codex": (0x3E, 0x79, 0xD6),
    "antigravity": (0x7A, 0x6A, 0xD8),
    "grok": (0x0C, 0x7E, 0x86),
    "minimax": (0xD6, 0x3A, 0x8A),
    "qwen": (0x08, 0x2D, 0xFF),
    "commandcode": (0x2E, 0x1B, 0x9C),
    "opencode": (0xB0, 0x8A, 0x1E),
    "copilot": (0x1F, 0x88, 0x3D),
    "pi": (0xC4, 0x1E, 0x3A),
    "workbuddy": (0xB6, 0x62, 0xCA),
    "workbuddy_ai": (0x00, 0x5E, 0x52),
    "grok_bot": (0xDC, 0x3C, 0x00),
    "qoderwork": (0x82, 0x3D, 0x44),
    "qodercli": (0x6E, 0x7F, 0x15),
    "qodercli_cn": (0x87, 0x2B, 0x83),
    "zcode": (0x3C, 0x5A, 0x31),
    "kimicode": (0x98, 0x5C, 0x26),
    "musecode": (0xC7, 0x7C, 0x80),
    "codebuddy": (0x00, 0xA0, 0x97),
    "qoder_ide": (0x24, 0x8B, 0xB2),
    "hermes": (0xA2, 0xA6, 0x00),
    "openclaw": (0xA8, 0x00, 0x5C),
    "devin": (0x00, 0x66, 0x94),
    "mimocode": (0xC2, 0x7C, 0x38),
    "prime_agent": (0x8F, 0x32, 0xD0),
    "omp": (0x00, 0x54, 0x62),
    "deepseek_harness": (0x00, 0x44, 0xA0),
    "qwenwork": (0x00, 0xA0, 0x6B),
}
DEFAULT_AGENT_COLOR = (0x9A, 0x9A, 0x9A)


def agent_color(agent: str) -> Tuple[int, int, int]:
    return AGENT_COLORS.get(agent, DEFAULT_AGENT_COLOR)


class TimeRange(str, Enum):
    ALL = "all"
    TODAY = "today"
    DAYS_7 = "7d"
    DAYS_30 = "30d"
    RESET = "reset"
    CYCLE = "cycle"


RANGE_TABS: List[Tuple[TimeRange, str]] = [
    (TimeRange.ALL, "All"),
    (TimeRange.TODAY, "Today"),
    (TimeRange.DAYS_7, "7d"),
    (TimeRange.DAYS_30, "30d"),
    (TimeRange.RESET, "Since reset"),
    (TimeRange.CYCLE, "Cycle"),
]


class ViewMode(str, Enum):
    PROJECTS = "projects"
    MODELS = "models"
    AGENTS = "agents"
    DAYS = "days"


VIEW_MODES: List[Tuple[ViewMode, str]] = [
    (ViewMode.PROJECTS, "Projects"),
    (ViewMode.MODELS, "Models"),
    (ViewMode.AGENTS, "Agents"),
    (ViewMode.DAYS, "Days"),
]


class QuotaLevel(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


def quota_level(percent: Optional[float]) -> Optional[QuotaLevel]:
    if percent is None or not math.isfinite(percent):
        return None
    if percent >= 95.0:
        return QuotaLevel.CRITICAL
    if percent >= 80.0:
        return QuotaLevel.WARNING
    return QuotaLevel.NORMAL


# ---- Formatting Helpers ----

def format_tokens(n: int) -> str:
    """Format token count in compact format: 1.21B, 266.2M, 45.2k, 500."""
    v = abs(float(n))
    sign = "-" if n < 0 else ""
    if v < 1000:
        return sign + str(int(v))
    if v < 1_000_000:
        scaled = v / 1000.0
        if scaled < 10:
            s = f"{scaled:.1f}k"
        else:
            s = f"{round(scaled)}k"
        if s.endswith(".0k"):
            s = s[:-3] + "k"
        return sign + s
    if v < 1_000_000_000:
        scaled = v / 1_000_000.0
        s = f"{scaled:.1f}M"
        if s.endswith(".0M"):
            s = s[:-3] + "M"
        return sign + s
    scaled = v / 1_000_000_000.0
    if scaled < 10:
        s = f"{scaled:.2f}B"
        if s.endswith("0B"):
            s = s[:-2] + "B"
        if s.endswith(".0B"):
            s = s[:-3] + "B"
    else:
        s = f"{scaled:.1f}B"
        if s.endswith(".0B"):
            s = s[:-3] + "B"
    return sign + s


def format_money(amount: float) -> str:
    """Format USD currency amount, e.g. $275.99, -$5.00, $0.00."""
    if not math.isfinite(amount):
        return "—"
    if amount < 0:
        return f"-${abs(amount):,.2f}"
    return f"${amount:,.2f}"


def parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
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
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def format_reset_countdown(reset_dt: Optional[datetime], now: datetime, tz: datetime.tzinfo) -> str:
    """Format relative countdown to reset_dt: resets in 2d 4h, resets 18:40, resets in 35m."""
    if reset_dt is None:
        return "—"
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    reset_utc = reset_dt if reset_dt.tzinfo else reset_dt.replace(tzinfo=timezone.utc)
    diff = (reset_utc - now_utc).total_seconds()
    if diff <= 0:
        return "window ended"
    minutes = max(1, math.ceil(diff / 60))
    if minutes < 60:
        return f"resets in {minutes}m"
    if minutes < 1440:
        # Check if same local day
        local_reset = reset_utc.astimezone(tz)
        local_now = now_utc.astimezone(tz)
        if local_reset.date() == local_now.date():
            return f"resets {local_reset.strftime('%H:%M')}"
        h = minutes // 60
        m = minutes % 60
        return f"resets in {h}h {m}m"
    d = minutes // 1440
    h = (minutes % 1440) // 60
    return f"resets in {d}d {h}h"


def get_tz(doc: dict) -> datetime.tzinfo:
    name = doc.get("timezone") or local_timezone_name()
    try:
        return ZoneInfo(name)
    except Exception:
        return local_zone(name)


def window_start(quota_entry: Optional[dict], now: datetime, tz: datetime.tzinfo) -> Optional[datetime]:
    """Calculate current weekly quota window start for an agent (weekly_resets_at - window_hours)."""
    if not quota_entry:
        return None
    reset_iso = quota_entry.get("weekly_resets_at")
    hours = quota_entry.get("weekly_window_hours", 168)
    reset = parse_iso_dt(reset_iso)
    if not reset or hours <= 0:
        return None
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    reset_utc = reset.astimezone(timezone.utc)
    period_sec = hours * 3600
    if hours == 168:
        # 7-day cadence
        diff = (now_utc - reset_utc).total_seconds()
        k = math.floor(diff / period_sec)
        start = reset_utc + timedelta(seconds=k * period_sec)
        while start > now_utc:
            start -= timedelta(seconds=period_sec)
        while (start + timedelta(seconds=period_sec)) <= now_utc:
            start += timedelta(seconds=period_sec)
        return start
    diff = (now_utc - reset_utc).total_seconds()
    k = math.floor(diff / period_sec)
    return reset_utc + timedelta(seconds=k * period_sec)


def format_month_day_time(dt: datetime, tz: datetime.tzinfo) -> str:
    """Format e.g. Nov 8 16:55."""
    local_dt = dt.astimezone(tz)
    return f"{local_dt.strftime('%b')} {local_dt.day} {local_dt.strftime('%H:%M')}"


def get_accounts_window(quota_windows: Optional[dict], subscriptions: Optional[dict],
                        now: Optional[datetime] = None, tz_name: Optional[str] = None) -> Tuple[datetime, str, str]:
    """Window = current Antigravity weekly quota window start (weekly_resets_at − window hours),
    else billing cycle start, else last 7 days.
    Returns (window_start_dt, kind, label).
    """
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(tz_name) if tz_name else local_zone(tz_name)
    qw = quota_windows or {}
    subs = subscriptions or {}

    # 1. Antigravity weekly quota window
    if "antigravity" in qw and qw["antigravity"].get("weekly_resets_at"):
        start = window_start(qw["antigravity"], now, tz)
        if start is not None:
            lbl = f"Antigravity accounts · this quota week (since {format_month_day_time(start, tz)})"
            return start, "quota_week", lbl

    # 2. Antigravity billing cycle start
    if "antigravity" in subs and subs["antigravity"].get("cycle_start"):
        start = parse_iso_dt(subs["antigravity"]["cycle_start"])
        if start is not None:
            lbl = f"Antigravity accounts · this billing cycle (since {format_month_day_time(start, tz)})"
            return start, "billing_cycle", lbl

    # 3. Fallback: last 7 days
    start = now - timedelta(days=7)
    lbl = f"Antigravity accounts · last 7 days (since {format_month_day_time(start, tz)})"
    return start, "last_7d", lbl


# ---- HeatStrip & Sparkline ----

_BLOCK_CHARS = " ▂▃▄▅▆▇█"
_ASCII_CHARS = " .:-=+*#%"


def heat_level(value: float, peak: float, levels: int = 8) -> int:
    if value <= 0 or peak <= 0:
        return 0
    ratio = min(value / peak, 1.0)
    return min(max(1, math.ceil(ratio * levels)), levels)


def compute_8w_strip(by_day: List[dict], now: datetime, tz: datetime.tzinfo,
                     fallback_agent: str = "unknown", ascii_mode: bool = False) -> List[Tuple[str, Optional[str]]]:
    """Compute 8-week heat strip ending on the week of `now`.
    Returns list of 8 (char, dominant_agent) pairs, oldest week first.
    """
    now_local = now.astimezone(tz)
    today = datetime(now_local.year, now_local.month, now_local.day, tzinfo=tz)
    monday_offset = today.weekday()  # Monday = 0
    this_monday = today - timedelta(days=monday_offset)

    # 8 weeks of start dates (Mondays)
    week_starts = [this_monday - timedelta(days=7 * (7 - i)) for i in range(8)]
    week_costs: List[float] = [0.0] * 8
    week_agent_costs: List[Dict[str, float]] = [{} for _ in range(8)]

    first_start = week_starts[0]
    first_date = first_start.date()

    for d in by_day:
        d_str = d.get("day")
        if not d_str:
            continue
        try:
            d_date = date.fromisoformat(d_str)
        except ValueError:
            continue
        days_from_first = (d_date - first_date).days
        if days_from_first < 0:
            continue
        w_idx = days_from_first // 7
        if w_idx >= 8:
            continue
        c = float(d.get("cost", 0.0))
        week_costs[w_idx] += c
        split = d.get("by_agent")
        if split:
            for ag, cost_val in split.items():
                week_agent_costs[w_idx][ag] = week_agent_costs[w_idx].get(ag, 0.0) + float(cost_val)
        else:
            week_agent_costs[w_idx][fallback_agent] = week_agent_costs[w_idx].get(fallback_agent, 0.0) + c

    peak = max(week_costs) if week_costs else 0.0
    out: List[Tuple[str, Optional[str]]] = []
    for i in range(8):
        c = week_costs[i]
        lvl = heat_level(c, peak, 8)
        # Dominant agent
        top_ag = None
        if week_agent_costs[i]:
            top_ag = max(week_agent_costs[i].items(), key=lambda kv: kv[1])[0]
        if lvl == 0:
            char = " " if ascii_mode else " "
            out.append((char, None))
        else:
            char = _ASCII_CHARS[lvl] if ascii_mode else _BLOCK_CHARS[lvl - 1]
            out.append((char, top_ag or fallback_agent))
    return out


def compute_30d_sparkline(by_day: List[dict], now: datetime, tz: datetime.tzinfo,
                          ascii_mode: bool = False) -> Tuple[str, float]:
    """Compute 30-day sparkline ending on `today`. Returns (sparkline_string, peak_cost)."""
    now_local = now.astimezone(tz)
    today = datetime(now_local.year, now_local.month, now_local.day, tzinfo=tz)
    day_map: Dict[str, float] = {}
    for d in by_day:
        d_str = d.get("day")
        if d_str:
            day_map[d_str] = day_map.get(d_str, 0.0) + float(d.get("cost", 0.0))

    days = [(today - timedelta(days=29 - i)).date().isoformat() for i in range(30)]
    costs = [day_map.get(day_str, 0.0) for day_str in days]
    peak = max(costs) if costs else 0.0

    chars = []
    for c in costs:
        lvl = heat_level(c, peak, 8)
        if lvl == 0:
            chars.append("." if ascii_mode else " ")
        else:
            chars.append(_ASCII_CHARS[lvl] if ascii_mode else _BLOCK_CHARS[lvl - 1])
    return "".join(chars), peak


# ---- Range Filtering ----

@dataclass
class FilteredData:
    time_range: TimeRange
    projects: List[dict]
    unattributed: dict
    excluded: dict
    parse_failed_count: int
    total_cost: float
    total_tokens: int
    total_sessions: int
    projects_count: int
    agent_shares: List[Tuple[str, str, float, float]]  # (agent, label, cost, share_pct)
    by_day: List[dict]  # aggregated daily costs across all filtered projects
    by_model: List[dict]  # aggregated models across all filtered projects
    by_agent: List[dict]  # aggregated agents view rows
    first_active: Optional[str] = None
    last_active: Optional[str] = None


def filter_report(doc: dict, time_range: TimeRange = TimeRange.ALL,
                  now: Optional[datetime] = None) -> FilteredData:
    """Filter projects and totals by selected range, matching TimeRange.swift semantics."""
    now = now or datetime.now(timezone.utc)
    tz = get_tz(doc)
    qw = doc.get("quota_windows", {})
    subs = doc.get("subscriptions", {})

    now_local = now.astimezone(tz)
    today_start = datetime(now_local.year, now_local.month, now_local.day, tzinfo=tz)

    # Calculate agent window [start, end)
    range_start: Optional[datetime] = None
    range_end: Optional[datetime] = now
    agent_starts: Dict[str, datetime] = {}

    if time_range == TimeRange.ALL:
        range_end = None
    elif time_range == TimeRange.TODAY:
        range_start = today_start
    elif time_range == TimeRange.DAYS_7:
        range_start = today_start - timedelta(days=6)
    elif time_range == TimeRange.DAYS_30:
        range_start = today_start - timedelta(days=29)
    elif time_range == TimeRange.RESET:
        for ag, q in qw.items():
            s = window_start(q, now, tz)
            if s is not None:
                agent_starts[ag] = s
    elif time_range == TimeRange.CYCLE:
        for ag, sub in subs.items():
            s_iso = sub.get("cycle_start")
            s = parse_iso_dt(s_iso)
            if s is not None:
                agent_starts[ag] = s

    def agent_window(ag: str) -> Optional[Tuple[Optional[datetime], Optional[datetime]]]:
        if time_range == TimeRange.ALL:
            return (None, None)
        if time_range in (TimeRange.RESET, TimeRange.CYCLE):
            if ag not in agent_starts:
                return None
            return (agent_starts[ag], range_end)
        return (range_start, range_end)

    def day_included(day_str: str, ag: str) -> bool:
        w = agent_window(ag)
        if w is None:
            return False
        w_start, w_end = w
        try:
            d_date = date.fromisoformat(day_str)
        except ValueError:
            return False
        d0 = datetime(d_date.year, d_date.month, d_date.day, tzinfo=tz)
        d1 = d0 + timedelta(days=1)
        if w_start is not None and d1 <= w_start:
            return False
        if w_end is not None and d0 >= w_end:
            return False
        return True

    def session_included(s: dict) -> bool:
        ag = s.get("agent", "")
        w = agent_window(ag)
        if w is None:
            return False
        w_start, w_end = w
        started = parse_iso_dt(s.get("started"))
        ended = parse_iso_dt(s.get("ended")) or started
        if not started and not ended:
            return False
        s0 = min(started or ended, ended or started)
        s1 = max(started or ended, ended or started)
        if w_start is not None and s1 < w_start:
            return False
        if w_end is not None and s0 >= w_end:
            return False
        return True

    def session_in_range_cost_tokens(s: dict) -> Tuple[float, int]:
        total_c = float(s.get("cost", 0.0))
        toks = s.get("tokens", {})
        total_t = toks.get("total", 0) if isinstance(toks, dict) else int(toks or 0)
        if time_range == TimeRange.ALL:
            return total_c, total_t
        if not session_included(s):
            return 0.0, 0
        ag = s.get("agent", "")
        w = agent_window(ag)
        if w is None:
            return 0.0, 0
        w_start, w_end = w
        started = parse_iso_dt(s.get("started"))
        ended = parse_iso_dt(s.get("ended")) or started
        if not started and not ended:
            return total_c, total_t
        s0 = min(started or ended, ended or started)
        s1 = max(started or ended, ended or started)
        dur = (s1 - s0).total_seconds()
        if dur <= 0:
            return total_c, total_t
        r0 = w_start or s0
        r1 = w_end or s1
        overlap0 = max(s0, r0)
        overlap1 = min(s1, r1)
        if overlap1 <= overlap0:
            return 0.0, 0
        share = min(1.0, max(0.0, (overlap1 - overlap0).total_seconds() / dur))
        return total_c * share, int(round(total_t * share))

    filtered_projects: List[dict] = []
    all_projects = doc.get("projects", [])

    for p in all_projects:
        fallback_ag = "unknown"
        if p.get("by_agent"):
            fallback_ag = p["by_agent"][0].get("agent", "unknown")

        if time_range == TimeRange.ALL:
            filtered_p = dict(p)
            filtered_projects.append(filtered_p)
            continue

        # Filter by_day
        f_by_day = []
        p_agent_cost: Dict[str, float] = {}
        p_agent_tokens: Dict[str, int] = {}

        for d in p.get("by_day", []):
            d_str = d.get("day", "")
            cost_split = d.get("by_agent") or {fallback_ag: d.get("cost", 0.0)}
            tok_split = d.get("by_agent_tokens") or {fallback_ag: d.get("tokens", 0)}

            dc: Dict[str, float] = {}
            dt: Dict[str, int] = {}
            agents_to_check = set(cost_split.keys()).union(tok_split.keys())
            for ag in agents_to_check:
                if day_included(d_str, ag):
                    if ag in cost_split:
                        dc[ag] = float(cost_split[ag])
                    if ag in tok_split:
                        dt[ag] = int(tok_split[ag])

            if dc or dt:
                for ag, c in dc.items():
                    p_agent_cost[ag] = p_agent_cost.get(ag, 0.0) + c
                for ag, t in dt.items():
                    p_agent_tokens[ag] = p_agent_tokens.get(ag, 0) + t
                f_by_day.append({
                    "day": d_str,
                    "cost": sum(dc.values()),
                    "tokens": sum(dt.values()),
                    "by_agent": dc,
                    "by_agent_tokens": dt,
                })

        # Filter sessions_detail
        f_sessions = [s for s in p.get("sessions_detail", []) if session_included(s)]
        p_agent_sessions: Dict[str, int] = {}
        for s in f_sessions:
            ag = s.get("agent", fallback_ag)
            p_agent_sessions[ag] = p_agent_sessions.get(ag, 0) + 1

        all_agents = set(p_agent_cost.keys()).union(p_agent_tokens.keys()).union(p_agent_sessions.keys())
        f_by_agent = []
        for ag in sorted(all_agents, key=lambda a: (-p_agent_cost.get(a, 0.0), a)):
            label = AGENT_LABELS.get(ag, ag)
            f_by_agent.append({
                "agent": ag,
                "label": label,
                "cost": p_agent_cost.get(ag, 0.0),
                "tokens": {"total": p_agent_tokens.get(ag, 0)},
                "sessions": p_agent_sessions.get(ag, 0),
            })

        p_cost = sum(d["cost"] for d in f_by_day)
        p_tokens = sum(d["tokens"] for d in f_by_day)
        p_sess = len(f_sessions)

        filtered_p = dict(p)
        filtered_p["cost"] = p_cost
        filtered_p["tokens"] = {"total": p_tokens}
        filtered_p["sessions"] = p_sess
        filtered_p["by_agent"] = f_by_agent
        filtered_p["by_day"] = f_by_day
        filtered_p["sessions_detail"] = f_sessions
        filtered_p["first_active"] = f_by_day[0]["day"] if f_by_day else None
        filtered_p["last_active"] = f_by_day[-1]["day"] if f_by_day else None

        filtered_projects.append(filtered_p)

    # Sort projects by cost desc
    filtered_projects.sort(key=lambda p: (-p["cost"], p.get("name", "").lower()))

    # Filter buckets
    buckets = doc.get("buckets", {})
    raw_unattr = buckets.get("unattributed", {})
    raw_excl = buckets.get("excluded", {})

    def filter_bucket(b: dict) -> dict:
        if time_range == TimeRange.ALL:
            return dict(b)
        ss = [s for s in b.get("sessions_detail", []) if session_included(s)]
        c = 0.0
        t = 0
        days = []
        for s in ss:
            sc, st = session_in_range_cost_tokens(s)
            c += sc
            t += st
            started = parse_iso_dt(s.get("started"))
            if started:
                days.append(started.astimezone(tz).date().isoformat())
        fb = dict(b)
        fb["cost"] = c
        fb["tokens"] = {"total": t}
        fb["sessions"] = len(ss)
        fb["sessions_detail"] = ss
        fb["first_active"] = min(days) if days else None
        fb["last_active"] = max(days) if days else None
        return fb

    filtered_unattr = filter_bucket(raw_unattr)
    filtered_excl = filter_bucket(raw_excl)
    parse_failed = buckets.get("parse_failed", {})
    failed_count = parse_failed.get("sessions", 0)

    # Calculate overall totals
    if time_range == TimeRange.ALL:
        raw_tot = doc.get("totals", {})
        total_cost = float(raw_tot.get("cost", 0.0))
        toks = raw_tot.get("tokens", {})
        total_tokens = toks.get("total", 0) if isinstance(toks, dict) else int(toks or 0)
        total_sessions = int(raw_tot.get("sessions", 0))
    else:
        total_cost = sum(p["cost"] for p in filtered_projects) + filtered_unattr["cost"] + filtered_excl["cost"]
        total_tokens = sum(p["tokens"]["total"] for p in filtered_projects) + filtered_unattr["tokens"]["total"] + filtered_excl["tokens"]["total"]
        total_sessions = sum(p["sessions"] for p in filtered_projects) + filtered_unattr["sessions"] + filtered_excl["sessions"]

    # Active projects with usage (or all if range is All)
    active_projects = [p for p in filtered_projects if (time_range == TimeRange.ALL or p["cost"] > 0 or p["tokens"]["total"] > 0 or p["sessions"] > 0)]

    # Agent breakdown across report
    agent_cost_total: Dict[str, float] = {}
    for p in filtered_projects:
        for a in p.get("by_agent", []):
            ag = a.get("agent", "")
            agent_cost_total[ag] = agent_cost_total.get(ag, 0.0) + float(a.get("cost", 0.0))
    for s in filtered_unattr.get("sessions_detail", []) + filtered_excl.get("sessions_detail", []):
        sc, _ = session_in_range_cost_tokens(s)
        ag = s.get("agent", "")
        agent_cost_total[ag] = agent_cost_total.get(ag, 0.0) + sc

    agent_shares: List[Tuple[str, str, float, float]] = []
    tot_for_share = total_cost if total_cost > 0 else 1.0
    for ag, c in sorted(agent_cost_total.items(), key=lambda kv: (-kv[1], kv[0])):
        if c > 0 or time_range == TimeRange.ALL:
            share_pct = (c / tot_for_share) * 100.0
            agent_shares.append((ag, AGENT_LABELS.get(ag, ag), c, share_pct))

    # Aggregated Days View
    daily_agg: Dict[str, Dict[str, Any]] = {}
    for p in filtered_projects:
        for d in p.get("by_day", []):
            d_str = d.get("day")
            if not d_str:
                continue
            if d_str not in daily_agg:
                daily_agg[d_str] = {"day": d_str, "cost": 0.0, "tokens": 0}
            daily_agg[d_str]["cost"] += float(d.get("cost", 0.0))
            daily_agg[d_str]["tokens"] += int(d.get("tokens", 0))

    by_day_list = sorted(daily_agg.values(), key=lambda d: d["day"], reverse=True)

    # Aggregated Models View
    model_agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if time_range == TimeRange.ALL:
        for p in all_projects:
            for m in p.get("by_model", []):
                key = (m.get("model", ""), m.get("agent", ""))
                if key not in model_agg:
                    model_agg[key] = {
                        "model": key[0],
                        "agent": key[1],
                        "provider": PROVIDER_LABELS.get(provider_for(key[0], key[1]), "Other"),
                        "cost": 0.0,
                        "tokens": 0,
                    }
                model_agg[key]["cost"] += float(m.get("cost", 0.0))
                tok_val = m.get("tokens", {})
                tok_count = tok_val.get("total", 0) if isinstance(tok_val, dict) else int(tok_val or 0)
                model_agg[key]["tokens"] += tok_count
    else:
        # Apportion from filtered sessions in filtered projects
        for p in filtered_projects:
            for s in p.get("sessions_detail", []):
                models = s.get("models", [])
                if not models:
                    continue
                sc, st = session_in_range_cost_tokens(s)
                share_c = sc / len(models)
                share_t = int(round(st / len(models)))
                ag = s.get("agent", "")
                for m_name in models:
                    key = (m_name, ag)
                    if key not in model_agg:
                        model_agg[key] = {
                            "model": m_name,
                            "agent": ag,
                            "provider": PROVIDER_LABELS.get(provider_for(m_name, ag), "Other"),
                            "cost": 0.0,
                            "tokens": 0,
                        }
                    model_agg[key]["cost"] += share_c
                    model_agg[key]["tokens"] += share_t

    by_model_list = sorted(model_agg.values(), key=lambda m: (-m["cost"], m["model"]))

    # Aggregated Agents View
    agent_rows: Dict[str, Dict[str, Any]] = {}
    for p in filtered_projects:
        for a in p.get("by_agent", []):
            ag = a.get("agent", "")
            if ag not in agent_rows:
                agent_rows[ag] = {
                    "agent": ag,
                    "label": a.get("label", AGENT_LABELS.get(ag, ag)),
                    "sessions": 0,
                    "tokens": 0,
                    "cost": 0.0,
                }
            agent_rows[ag]["cost"] += float(a.get("cost", 0.0))
            agent_rows[ag]["sessions"] += int(a.get("sessions", 0))
            tok_val = a.get("tokens", {})
            tok_count = tok_val.get("total", 0) if isinstance(tok_val, dict) else int(tok_val or 0)
            agent_rows[ag]["tokens"] += tok_count

    for s in filtered_unattr.get("sessions_detail", []) + filtered_excl.get("sessions_detail", []):
        sc, st = session_in_range_cost_tokens(s)
        ag = s.get("agent", "")
        if ag not in agent_rows:
            agent_rows[ag] = {
                "agent": ag,
                "label": AGENT_LABELS.get(ag, ag),
                "sessions": 0,
                "tokens": 0,
                "cost": 0.0,
            }
        agent_rows[ag]["cost"] += sc
        agent_rows[ag]["tokens"] += st
        agent_rows[ag]["sessions"] += 1

    by_agent_list = []
    for ag, row in sorted(agent_rows.items(), key=lambda kv: (-kv[1]["cost"], kv[0])):
        row_share = (row["cost"] / tot_for_share) * 100.0 if tot_for_share > 0 else 0.0
        row["share_pct"] = row_share
        by_agent_list.append(row)

    first_act = min((p["first_active"] for p in filtered_projects if p.get("first_active")), default=None)
    last_act = max((p["last_active"] for p in filtered_projects if p.get("last_active")), default=None)

    return FilteredData(
        time_range=time_range,
        projects=active_projects,
        unattributed=filtered_unattr,
        excluded=filtered_excl,
        parse_failed_count=failed_count,
        total_cost=total_cost,
        total_tokens=total_tokens,
        total_sessions=total_sessions,
        projects_count=len(active_projects),
        agent_shares=agent_shares,
        by_day=by_day_list,
        by_model=by_model_list,
        by_agent=by_agent_list,
        first_active=first_act,
        last_active=last_act,
    )


# ---- View Models for Rendering ----

@dataclass
class TotalViewModel:
    cost_str: str
    tokens_str: str
    sessions_str: str
    projects_str: str
    shares: List[Tuple[str, str, float, float, Tuple[int, int, int]]]  # agent, label, cost, pct, rgb


@dataclass
class QuotaMeterWindow:
    name: str
    percent: Optional[float]
    level: Optional[QuotaLevel]
    detail: str


@dataclass
class SubscriptionMeter:
    agent: str
    plan_label: str
    price_str: str
    usage_str: str
    multiplier_str: str
    color: Tuple[int, int, int]
    windows: List[QuotaMeterWindow]


@dataclass
class AntigravityAccountRow:
    email: str
    tokens_str: str
    cost_str: str
    is_current: bool
    is_unattributed: bool


@dataclass
class AntigravityAccountsSection:
    header_label: str
    rows: List[AntigravityAccountRow]


@dataclass
class ProjectRowViewModel:
    id: str
    name: str
    cost_str: str
    tokens_str: str
    sessions_str: str
    agents: List[str]
    last_active_str: str
    heat_strip: List[Tuple[str, Optional[str]]]
    is_bucket: bool = False
    is_total: bool = False


@dataclass
class ModelRowViewModel:
    model: str
    provider: str
    tokens_str: str
    cost_str: str


@dataclass
class AgentRowViewModel:
    agent: str
    label: str
    sessions_str: str
    tokens_str: str
    cost_str: str
    share_pct: float
    color: Tuple[int, int, int]


@dataclass
class DayRowViewModel:
    date_str: str
    cost_str: str
    tokens_str: str
    cost_ratio: float  # 0.0 to 1.0


@dataclass
class ProjectDetailViewModel:
    id: str
    name: str
    remote: Optional[str]
    paths: List[str]
    cost_str: str
    tokens_str: str
    sessions_str: str
    by_agent: List[Tuple[str, str, str, str, float, Tuple[int, int, int]]]  # label, cost, tok, sess, pct, rgb
    by_model: List[Tuple[str, str, str, str]]  # model, provider, cost, tok
    sparkline_30d: str
    sparkline_peak_str: str


def build_total_view_model(filtered: FilteredData) -> TotalViewModel:
    cost_str = format_money(filtered.total_cost)
    tok_str = f"{format_tokens(filtered.total_tokens)} tokens"
    sess_str = f"{filtered.total_sessions} sessions"
    proj_str = f"{filtered.projects_count} projects"
    shares = []
    for ag, lbl, c, pct in filtered.agent_shares:
        shares.append((ag, lbl, c, pct, agent_color(ag)))
    return TotalViewModel(
        cost_str=cost_str,
        tokens_str=tok_str,
        sessions_str=sess_str,
        projects_str=proj_str,
        shares=shares,
    )


def build_subscription_meters(doc: dict, now: Optional[datetime] = None) -> List[SubscriptionMeter]:
    """Build htop CPU-meter style subscription blocks."""
    now = now or datetime.now(timezone.utc)
    tz = get_tz(doc)
    subs = doc.get("subscriptions", {})
    qw = doc.get("quota_windows", {})
    if not subs:
        return []

    # Cycle usage for each agent
    cycle_filtered = filter_report(doc, TimeRange.CYCLE, now=now)
    usage_map = {row["agent"]: row["cost"] for row in cycle_filtered.by_agent}

    meters: List[SubscriptionMeter] = []
    for ag in sorted(subs.keys()):
        sub = subs[ag]
        plan_label = sub.get("plan_label", ag)
        price = sub.get("monthly_price_usd")
        usage = usage_map.get(ag, 0.0)

        price_str = f"${price:,.2f}/mo" if (price is not None and price > 0) else "—"
        usage_str = f"usage {format_money(usage)}"
        if price is not None and price > 0 and usage > 0:
            multiplier = usage / price
            mult_str = f"{multiplier:.1f}×"
        else:
            mult_str = "—"

        # Quota windows
        q = qw.get(ag, {})
        windows: List[QuotaMeterWindow] = []

        # Weekly window
        weekly_reset = parse_iso_dt(q.get("weekly_resets_at"))
        weekly_hours = q.get("weekly_window_hours", 168)
        weekly_pct = q.get("weekly_used_percent")
        weekly_title = "Weekly" if weekly_hours == 168 else f"{weekly_hours}-hour"

        if weekly_reset is not None:
            now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
            reset_utc = weekly_reset if weekly_reset.tzinfo else weekly_reset.replace(tzinfo=timezone.utc)
            ended = reset_utc <= now_utc
            pct = None if ended else weekly_pct
            detail = "window ended" if ended else format_reset_countdown(weekly_reset, now, tz)
            windows.append(QuotaMeterWindow(
                name=weekly_title,
                percent=pct,
                level=quota_level(pct),
                detail=detail,
            ))

        # 5-hour window
        five_hours = q.get("five_hour_window_hours")
        if five_hours is not None or q.get("five_hour_resets_at"):
            five_reset = parse_iso_dt(q.get("five_hour_resets_at"))
            five_pct = q.get("five_hour_used_percent")
            five_title = f"{int(round(five_hours)) if five_hours else 5}-hour"
            if five_reset is not None:
                now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
                reset_utc = five_reset if five_reset.tzinfo else five_reset.replace(tzinfo=timezone.utc)
                ended = reset_utc <= now_utc
                pct = None if ended else five_pct
                detail = "window ended" if ended else format_reset_countdown(five_reset, now, tz)
                windows.append(QuotaMeterWindow(
                    name=five_title,
                    percent=pct,
                    level=quota_level(pct),
                    detail=detail,
                ))

        # Extra windows (e.g. Claude & GPT weekly in Antigravity)
        for ew in q.get("extra_windows", []):
            ew_reset = parse_iso_dt(ew.get("resets_at"))
            ew_pct = ew.get("used_percent")
            ew_title = ew.get("title", "Extra")
            if ew_reset is not None:
                now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
                reset_utc = ew_reset if ew_reset.tzinfo else ew_reset.replace(tzinfo=timezone.utc)
                ended = reset_utc <= now_utc
                pct = None if ended else ew_pct
                detail = "window ended" if ended else format_reset_countdown(ew_reset, now, tz)
                windows.append(QuotaMeterWindow(
                    name=ew_title,
                    percent=pct,
                    level=quota_level(pct),
                    detail=detail,
                ))

        meters.append(SubscriptionMeter(
            agent=ag,
            plan_label=plan_label,
            price_str=price_str,
            usage_str=usage_str,
            multiplier_str=mult_str,
            color=agent_color(ag),
            windows=windows,
        ))

    return meters


def build_antigravity_accounts_section(
    doc: dict,
    now: Optional[datetime] = None,
    antigravity_data: Optional[List[dict]] = None,
    current_account: Optional[str] = None
) -> Optional[AntigravityAccountsSection]:
    """Build Antigravity accounts section if attribution data exists."""
    now = now or datetime.now(timezone.utc)
    qw = doc.get("quota_windows", {})
    subs = doc.get("subscriptions", {})
    window_start_dt, kind, header_label = get_accounts_window(qw, subs, now=now, tz_name=doc.get("timezone"))

    rows_data = antigravity_data or doc.get("antigravity_accounts")
    if not rows_data:
        return None

    # Check if there is any attribution data
    has_any = any(r.get("account") != "unknown" or r.get("tokens", 0) > 0 for r in rows_data)
    if not has_any:
        return None

    out_rows: List[AntigravityAccountRow] = []
    unattr_row: Optional[AntigravityAccountRow] = None

    for r in rows_data:
        acc = r.get("account", "").strip()
        toks = int(r.get("tokens", 0))
        cost = float(r.get("cost", 0.0))
        is_cur = r.get("is_current", False)
        if current_account and acc.lower() == current_account.lower():
            is_cur = True

        if acc.lower() in ("unknown", "unattributed", ""):
            unattr_row = AntigravityAccountRow(
                email="unattributed",
                tokens_str=format_tokens(toks),
                cost_str=format_money(cost),
                is_current=False,
                is_unattributed=True,
            )
        else:
            out_rows.append(AntigravityAccountRow(
                email=acc,
                tokens_str=format_tokens(toks),
                cost_str=format_money(cost),
                is_current=is_cur,
                is_unattributed=False,
            ))

    # Known rows sorted by tokens descending
    out_rows.sort(key=lambda r: -parse_tokens_str(r.tokens_str))
    if unattr_row is not None:
        out_rows.append(unattr_row)

    return AntigravityAccountsSection(header_label=header_label, rows=out_rows)


def parse_tokens_str(tok_str: str) -> float:
    try:
        if tok_str.endswith("B"):
            return float(tok_str[:-1]) * 1e9
        if tok_str.endswith("M"):
            return float(tok_str[:-1]) * 1e6
        if tok_str.endswith("k"):
            return float(tok_str[:-1]) * 1e3
        return float(tok_str)
    except ValueError:
        return 0.0


def build_project_rows(filtered: FilteredData, now: datetime, tz: datetime.tzinfo,
                       ascii_mode: bool = False, filter_query: str = "") -> List[ProjectRowViewModel]:
    """Build row view models for the Projects view table."""
    rows: List[ProjectRowViewModel] = []
    query = filter_query.strip().lower()

    for p in filtered.projects:
        name = p.get("name", "Unnamed")
        if query and query not in name.lower():
            continue
        c_str = format_money(p["cost"])
        t_str = format_tokens(p["tokens"]["total"])
        s_str = str(p["sessions"])
        agents = [a["agent"] for a in p.get("by_agent", []) if a.get("cost", 0) > 0 or a.get("tokens", {}).get("total", 0) > 0 or a.get("sessions", 0) > 0]
        last_act = p.get("last_active") or "—"
        fallback_ag = agents[0] if agents else "unknown"
        heat = compute_8w_strip(p.get("by_day", []), now, tz, fallback_agent=fallback_ag, ascii_mode=ascii_mode)

        rows.append(ProjectRowViewModel(
            id=p.get("id", ""),
            name=name + (" (missing)" if p.get("path_missing") else ""),
            cost_str=c_str,
            tokens_str=t_str,
            sessions_str=s_str,
            agents=agents,
            last_active_str=last_act,
            heat_strip=heat,
        ))

    return rows


def build_project_footer_rows(filtered: FilteredData, now: datetime, tz: datetime.tzinfo,
                              ascii_mode: bool = False) -> List[ProjectRowViewModel]:
    """Footer rows for Projects view: Unattributed, Excluded, Parse failed, Total."""
    footers: List[ProjectRowViewModel] = []
    u = filtered.unattributed
    e = filtered.excluded

    empty_heat = [(" " if ascii_mode else " ", None)] * 8

    # Unattributed
    u_c = format_money(u.get("cost", 0.0))
    u_t = format_tokens(u.get("tokens", {}).get("total", 0))
    u_s = str(u.get("sessions", 0))
    u_last = u.get("last_active") or "—"
    footers.append(ProjectRowViewModel(
        id="__unattributed__",
        name="Unattributed",
        cost_str=u_c,
        tokens_str=u_t,
        sessions_str=u_s,
        agents=[],
        last_active_str=u_last,
        heat_strip=empty_heat,
        is_bucket=True,
    ))

    # Excluded
    e_c = format_money(e.get("cost", 0.0))
    e_t = format_tokens(e.get("tokens", {}).get("total", 0))
    e_s = str(e.get("sessions", 0))
    e_last = e.get("last_active") or "—"
    footers.append(ProjectRowViewModel(
        id="__excluded__",
        name="Excluded",
        cost_str=e_c,
        tokens_str=e_t,
        sessions_str=e_s,
        agents=[],
        last_active_str=e_last,
        heat_strip=empty_heat,
        is_bucket=True,
    ))

    # Parse failed
    if filtered.parse_failed_count > 0:
        footers.append(ProjectRowViewModel(
            id="__parse_failed__",
            name="Parse failed",
            cost_str="—",
            tokens_str="—",
            sessions_str=str(filtered.parse_failed_count),
            agents=[],
            last_active_str="—",
            heat_strip=empty_heat,
            is_bucket=True,
        ))

    # Total
    tot_c = format_money(filtered.total_cost)
    tot_t = format_tokens(filtered.total_tokens)
    tot_s = str(filtered.total_sessions)
    tot_last = filtered.last_active or "—"
    footers.append(ProjectRowViewModel(
        id="__total__",
        name="Total",
        cost_str=tot_c,
        tokens_str=tot_t,
        sessions_str=tot_s,
        agents=[],
        last_active_str=tot_last,
        heat_strip=empty_heat,
        is_total=True,
    ))

    return footers


def build_model_rows(filtered: FilteredData, filter_query: str = "") -> List[ModelRowViewModel]:
    rows: List[ModelRowViewModel] = []
    query = filter_query.strip().lower()
    for m in filtered.by_model:
        name = m.get("model", "")
        if query and query not in name.lower() and query not in m.get("provider", "").lower():
            continue
        rows.append(ModelRowViewModel(
            model=name,
            provider=m.get("provider", "Other"),
            tokens_str=format_tokens(m.get("tokens", 0)),
            cost_str=format_money(m.get("cost", 0.0)),
        ))
    return rows


def build_agent_rows(filtered: FilteredData, filter_query: str = "") -> List[AgentRowViewModel]:
    rows: List[AgentRowViewModel] = []
    query = filter_query.strip().lower()
    for a in filtered.by_agent:
        lbl = a.get("label", a.get("agent", ""))
        if query and query not in lbl.lower() and query not in a.get("agent", "").lower():
            continue
        ag = a.get("agent", "")
        rows.append(AgentRowViewModel(
            agent=ag,
            label=lbl,
            sessions_str=str(a.get("sessions", 0)),
            tokens_str=format_tokens(a.get("tokens", 0)),
            cost_str=format_money(a.get("cost", 0.0)),
            share_pct=float(a.get("share_pct", 0.0)),
            color=agent_color(ag),
        ))
    return rows


def build_day_rows(filtered: FilteredData, filter_query: str = "") -> List[DayRowViewModel]:
    rows: List[DayRowViewModel] = []
    query = filter_query.strip().lower()
    peak = max((d.get("cost", 0.0) for d in filtered.by_day), default=0.0)
    for d in filtered.by_day:
        d_str = d.get("day", "")
        if query and query not in d_str.lower():
            continue
        c = float(d.get("cost", 0.0))
        ratio = (c / peak) if peak > 0 else 0.0
        rows.append(DayRowViewModel(
            date_str=d_str,
            cost_str=format_money(c),
            tokens_str=format_tokens(d.get("tokens", 0)),
            cost_ratio=ratio,
        ))
    return rows


def build_project_detail(project: dict, now: datetime, tz: datetime.tzinfo,
                         ascii_mode: bool = False) -> ProjectDetailViewModel:
    """Build detail pane model for a selected project."""
    name = project.get("name", "Unnamed")
    remote = project.get("remote")
    paths = project.get("paths", [])
    cost_str = format_money(project.get("cost", 0.0))
    tok_val = project.get("tokens", {})
    tok_count = tok_val.get("total", 0) if isinstance(tok_val, dict) else int(tok_val or 0)
    tokens_str = format_tokens(tok_count)
    sessions_str = str(project.get("sessions", 0))

    # Breakdown by agent
    by_agent: List[Tuple[str, str, str, str, float, Tuple[int, int, int]]] = []
    tot_c = float(project.get("cost", 0.0)) or 1.0
    for a in project.get("by_agent", []):
        ag = a.get("agent", "")
        c = float(a.get("cost", 0.0))
        t = a.get("tokens", {}).get("total", 0) if isinstance(a.get("tokens"), dict) else int(a.get("tokens") or 0)
        s = int(a.get("sessions", 0))
        pct = (c / tot_c) * 100.0
        by_agent.append((
            a.get("label", AGENT_LABELS.get(ag, ag)),
            format_money(c),
            format_tokens(t),
            str(s),
            pct,
            agent_color(ag),
        ))

    # Breakdown by model
    by_model: List[Tuple[str, str, str, str]] = []
    for m in project.get("by_model", []):
        m_name = m.get("model", "")
        ag = m.get("agent", "")
        prov = PROVIDER_LABELS.get(provider_for(m_name, ag), "Other")
        c = float(m.get("cost", 0.0))
        t = m.get("tokens", {}).get("total", 0) if isinstance(m.get("tokens"), dict) else int(m.get("tokens") or 0)
        by_model.append((
            m_name,
            prov,
            format_money(c),
            format_tokens(t),
        ))

    # 30-day sparkline
    spark, peak = compute_30d_sparkline(project.get("by_day", []), now, tz, ascii_mode=ascii_mode)
    peak_str = f"{format_money(peak)}/day max"

    return ProjectDetailViewModel(
        id=project.get("id", ""),
        name=name,
        remote=remote,
        paths=paths,
        cost_str=cost_str,
        tokens_str=tokens_str,
        sessions_str=sessions_str,
        by_agent=by_agent,
        by_model=by_model,
        sparkline_30d=spark,
        sparkline_peak_str=peak_str,
    )
