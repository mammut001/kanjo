"""Parity golden dump for TUI calculations (subset of keys in parity/mac.json)."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..providers import provider_for, PROVIDER_LABELS
from ..sources.base import AGENT_LABELS
from . import calendar_time as cal
from .i18n import t
from .model import TimeRange
from .range_engine import (
    PARITY_RANGE_ORDER,
    ParityTimeRange,
    TUI_RANGE_TO_PARITY,
    aggregate_models,
    apportion,
    date_interval,
    dominant_fallback_agent,
    filtered_usage,
    parse_iso_dt,
    window_start,
    build_range_helpers,
    filtered_usage as _filtered_usage,
)
from .range_engine import get_tz, ensure_aware, spec_for_tui_range, FilteredUsage


PARITY_TUI_RANGES: Dict[str, TimeRange] = {
    "all": TimeRange.ALL,
    "today": TimeRange.TODAY,
    "days7": TimeRange.DAYS_7,
    "days30": TimeRange.DAYS_30,
    "sinceReset": TimeRange.RESET,
    "billingCycle": TimeRange.CYCLE,
}

PARITY_SCENARIOS = [
    ("America/New_York", "2026-10-24T07:00:00Z"),
    ("Asia/Shanghai", "2026-10-24T07:00:00Z"),
    ("Europe/Berlin", "2026-10-24T07:00:00Z"),
    ("America/New_York", "2026-03-08T07:30:00Z"),
    ("America/New_York", "2026-10-26T04:30:00Z"),
    ("Asia/Shanghai", "2026-01-31T12:00:00Z"),
    ("Europe/Berlin", "2025-02-28T12:00:00Z"),
    ("America/New_York", "2024-02-29T12:00:00Z"),
]


def cents(x: float) -> int:
    return int(round(x * 100))


def stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _token_parts(toks: Any) -> Tuple[int, int, int, int, int, int]:
    if isinstance(toks, dict):
        return (
            int(toks.get("input", 0) or 0),
            int(toks.get("output", 0) or 0),
            int(toks.get("cache_read", 0) or 0),
            int(toks.get("cache_write", 0) or 0),
            int(toks.get("thinking", 0) or 0),
            int(toks.get("total", 0) or 0),
        )
    tot = int(toks or 0) if toks else 0
    return 0, 0, 0, 0, 0, tot


def _exact_breakdowns(doc: dict) -> Dict[str, Tuple[int, int, int, int, int]]:
    acc: Dict[str, List[int]] = {}
    for p in doc.get("projects") or []:
        if not isinstance(p, dict):
            continue
        for a in p.get("by_agent") or []:
            if not isinstance(a, dict):
                continue
            ag = str(a.get("agent") or "")
            if not ag:
                continue
            inp, output, cr, cw, th, _tot = _token_parts(a.get("tokens"))
            cur = acc.setdefault(ag, [0, 0, 0, 0, 0])
            cur[0] += inp
            cur[1] += output
            cur[2] += cr
            cur[3] += cw
            cur[4] += th
    buckets = doc.get("buckets") or {}
    for name in ("unattributed", "excluded"):
        for s in (buckets.get(name) or {}).get("sessions_detail") or []:
            if not isinstance(s, dict):
                continue
            ag = str(s.get("agent") or "")
            if not ag:
                continue
            inp, output, cr, cw, th, _ = _token_parts(s.get("tokens"))
            cur = acc.setdefault(ag, [0, 0, 0, 0, 0])
            cur[0] += inp
            cur[1] += output
            cur[2] += cr
            cur[3] += cw
            cur[4] += th
    return {k: tuple(v) for k, v in acc.items()}


def _share_apportion(total: int, weights: List[float]) -> List[int]:
    if total <= 0 or not weights:
        return [0] * len(weights)
    s = sum(weights)
    if s <= 0:
        return [0] * len(weights)
    quotas = [total * (w / s) for w in weights]
    integers = [int(math.floor(q)) for q in quotas]
    leftover = total - sum(integers)
    remainders = [(quotas[i] - integers[i], i) for i in range(len(weights))]
    remainders.sort(key=lambda r: (-r[0], r[1]))
    for i in range(min(max(0, leftover), len(weights))):
        integers[remainders[i][1]] += 1
    return integers


def _apportioned_breakdown(target: int, sessions: List[dict], spec, fallback: Optional[Tuple[int, int, int, int, int]]) -> Dict[str, int]:
    if target <= 0:
        return {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "thinking": 0}
    w_in = w_out = w_cr = w_cw = w_th = 0.0
    for s in sessions:
        _, in_range = spec.in_range_cost_and_tokens(s)
        if in_range <= 0:
            continue
        inp, out, cr, cw, th, tot = _token_parts(s.get("tokens"))
        denom = max(inp + out + cr + cw, tot)
        if denom <= 0:
            continue
        scale = in_range / denom
        w_in += inp * scale
        w_out += out * scale
        w_cr += cr * scale
        w_cw += cw * scale
        w_th += th * scale
    weighted = w_in + w_out + w_cr + w_cw
    if weighted > 0:
        weights = [w_in, w_out, w_cr, w_cw]
        thinking_ratio = min(1.0, max(0.0, w_th / w_out)) if w_out > 0 else 0.0
    elif fallback and sum(fallback[:4]) > 0:
        weights = [float(x) for x in fallback[:4]]
        thinking_ratio = min(1.0, max(0.0, fallback[4] / fallback[1])) if fallback[1] > 0 else 0.0
    else:
        return {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "thinking": 0, "total": target}
    parts = _share_apportion(target, list(weights))
    thinking = int(round(parts[1] * thinking_ratio))
    thinking = max(0, min(thinking, parts[1]))
    return {
        "input": parts[0],
        "output": parts[1],
        "cacheRead": parts[2],
        "cacheWrite": parts[3],
        "thinking": thinking,
    }


def build_share_summary(doc: dict, parity_range: str, now: datetime) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    tr = PARITY_TUI_RANGES.get(parity_range, TimeRange.ALL)
    filtered = filtered_usage(doc, tr, now=now)
    spec = filtered.spec
    exact = _exact_breakdowns(doc)

    agent_cost: Dict[str, float] = {}
    agent_tokens: Dict[str, int] = {}
    for fp in filtered.projects:
        for a in fp.by_agent:
            ag = str(a.get("agent") or "")
            agent_cost[ag] = agent_cost.get(ag, 0.0) + float(a.get("cost") or 0.0)
            agent_tokens[ag] = agent_tokens.get(ag, 0) + int((a.get("tokens") or {}).get("total", 0) or 0)
    for s in filtered.unattributed.sessions_detail + filtered.excluded.sessions_detail:
        c, t = spec.in_range_cost_and_tokens(s)
        ag = str(s.get("agent") or "")
        agent_cost[ag] = agent_cost.get(ag, 0.0) + c
        agent_tokens[ag] = agent_tokens.get(ag, 0) + t

    active = sorted(
        [a for a in agent_tokens if agent_tokens[a] > 0],
        key=lambda a: (-agent_tokens[a], -agent_cost.get(a, 0.0), a),
    )

    sessions_by_agent: Dict[str, List[dict]] = {}
    project_session_counts: Dict[str, int] = {}
    for fp in filtered.projects:
        for s in fp.sessions_detail:
            ag = str(s.get("agent") or "")
            sessions_by_agent.setdefault(ag, []).append(s)
            project_session_counts[ag] = project_session_counts.get(ag, 0) + 1
    for s in filtered.unattributed.sessions_detail + filtered.excluded.sessions_detail:
        ag = str(s.get("agent") or "")
        sessions_by_agent.setdefault(ag, []).append(s)

    cycle_filtered = filtered_usage(doc, TimeRange.CYCLE, now=now)
    cycle_cost_by_agent: Dict[str, float] = {}
    for fp in cycle_filtered.projects:
        for a in fp.by_agent:
            ag = str(a.get("agent") or "")
            cycle_cost_by_agent[ag] = cycle_cost_by_agent.get(ag, 0.0) + float(a.get("cost") or 0.0)
    for s in cycle_filtered.unattributed.sessions_detail + cycle_filtered.excluded.sessions_detail:
        c, _ = cycle_filtered.spec.in_range_cost_and_tokens(s)
        ag = str(s.get("agent") or "")
        cycle_cost_by_agent[ag] = cycle_cost_by_agent.get(ag, 0.0) + c

    share_rows: Dict[str, Any] = {}
    total_in = total_out = total_cr = total_cw = total_th = 0
    subs = doc.get("subscriptions") or {}

    for agent in active:
        tokens = agent_tokens[agent]
        if spec.is_all:
            fb = exact.get(agent)
            if fb and sum(fb) > 0:
                breakdown = {"input": fb[0], "output": fb[1], "cacheRead": fb[2], "cacheWrite": fb[3], "thinking": fb[4]}
            else:
                breakdown = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "thinking": 0}
        else:
            breakdown = _apportioned_breakdown(tokens, sessions_by_agent.get(agent, []), spec, exact.get(agent))

        total_in += breakdown["input"]
        total_out += breakdown["output"]
        total_cr += breakdown["cacheRead"]
        total_cw += breakdown["cacheWrite"]
        total_th += breakdown["thinking"]

        mult = None
        sub = subs.get(agent) if isinstance(subs, dict) else None
        if isinstance(sub, dict):
            try:
                price = float(sub.get("monthly_price_usd"))
            except (TypeError, ValueError):
                price = None
            usage = cycle_cost_by_agent.get(agent, 0.0)
            if price and price > 0 and math.isfinite(usage):
                mult = usage / price

        share_rows[agent] = {
            "sessions": project_session_counts.get(agent, 0),
            "input": breakdown["input"],
            "output": breakdown["output"],
            "cacheRead": breakdown["cacheRead"],
            "cacheWrite": breakdown["cacheWrite"],
            "thinking": breakdown["thinking"],
            "multiplier": cents(mult) if mult is not None else None,
        }

    share_totals = {
        "cost": cents(filtered.cost),
        "tokens": filtered.tokens,
        "sessions": filtered.sessions,
        "agents": len(share_rows),
        "input": total_in,
        "output": total_out,
        "cacheRead": total_cr,
        "cacheWrite": total_cw,
        "thinking": total_th,
    }
    return share_rows, share_totals


def heat_strip_weekly(by_day: List[dict], ending_on: datetime, tz, fallback_agent: str, weeks: int = 8) -> List[dict]:
    now_local = cal.local_date(tz, ending_on)
    monday = cal.monday_on_or_before(now_local)
    starts = [cal.at_day(tz, monday + __import__("datetime").timedelta(days=-7 * (weeks - 1 - i))) for i in range(weeks)]
    out = [{"start": s, "cost": 0.0, "tokens": 0, "agents": {}, "agentTokens": {}} for s in starts]
    if not starts:
        return []
    first = cal.local_date(tz, starts[0])

    for d in by_day or []:
        if not isinstance(d, dict):
            continue
        day = cal.parse_day(str(d.get("day") or ""))
        if day is None:
            continue
        n = (day - first).days
        if n < 0:
            continue
        idx = n // 7
        if idx >= len(out):
            continue
        w = out[idx]
        try:
            cost = float(d.get("cost") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        try:
            tokens = int(d.get("tokens") or 0)
        except (TypeError, ValueError):
            tokens = 0
        w["cost"] += cost
        w["tokens"] += tokens
        split = d.get("by_agent") if isinstance(d.get("by_agent"), dict) and d.get("by_agent") else {fallback_agent: cost}
        for ag, c in split.items():
            try:
                cv = float(c or 0.0)
            except (TypeError, ValueError):
                cv = 0.0
            w["agents"][str(ag)] = w["agents"].get(str(ag), 0.0) + cv
        tok_split = d.get("by_agent_tokens") if isinstance(d.get("by_agent_tokens"), dict) and d.get("by_agent_tokens") else {fallback_agent: tokens}
        for ag, t in tok_split.items():
            try:
                tv = int(t or 0)
            except (TypeError, ValueError):
                tv = 0
            w["agentTokens"][str(ag)] = w["agentTokens"].get(str(ag), 0) + tv
    return out


def weekly_tokens_reference(now: datetime, generated_at: Optional[datetime]) -> datetime:
    if generated_at is not None and generated_at < now:
        return generated_at
    return now


def weekly_tokens_since(monday_instant: datetime, projects: List[dict], tz) -> int:
    monday = cal.monday_on_or_before(cal.local_date(tz, monday_instant))
    total = 0
    for p in projects or []:
        if not isinstance(p, dict):
            continue
        for d in p.get("by_day") or []:
            if not isinstance(d, dict):
                continue
            day = cal.parse_day(str(d.get("day") or ""))
            if day is None or day < monday:
                continue
            try:
                total += int(d.get("tokens") or 0)
            except (TypeError, ValueError):
                pass
    return total


def subscription_rows(doc: dict, now: datetime) -> Dict[str, Any]:
    subs = doc.get("subscriptions") or {}
    if not subs:
        return {}
    cycle = filtered_usage(doc, TimeRange.CYCLE, now=now)
    cost_by_agent: Dict[str, float] = {}
    for fp in cycle.projects:
        for a in fp.by_agent:
            ag = str(a.get("agent") or "")
            cost_by_agent[ag] = cost_by_agent.get(ag, 0.0) + float(a.get("cost") or 0.0)
    for s in cycle.unattributed.sessions_detail + cycle.excluded.sessions_detail:
        c, _ = cycle.spec.in_range_cost_and_tokens(s)
        ag = str(s.get("agent") or "")
        cost_by_agent[ag] = cost_by_agent.get(ag, 0.0) + c

    rows = []
    for ag, sub in subs.items():
        if not isinstance(sub, dict):
            continue
        usage = cost_by_agent.get(ag, 0.0)
        price = sub.get("monthly_price_usd")
        try:
            price_f = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_f = None
        mult = (usage / price_f) if price_f and price_f > 0 else None
        rows.append((ag, sub, usage, mult))
    rows.sort(key=lambda x: (-x[2], x[0]))

    out: Dict[str, Any] = {}
    for ag, sub, usage, mult in rows:
        out[ag] = {
            "plan": sub.get("plan"),
            "start": sub.get("cycle_start"),
            "end": sub.get("cycle_end"),
            "value": cents(usage),
            "multiplier": cents(mult) if mult is not None else None,
        }
    return out


def quota_rows_for_agent(q: dict, tz, now: datetime) -> List[dict]:
    ended_text = t("overview.quota.ended", "en")
    rows: List[dict] = []
    now_utc = now.astimezone(timezone.utc)

    five_hours = q.get("five_hour_window_hours")
    if five_hours is not None or q.get("five_hour_resets_at"):
        five_reset = parse_iso_dt(q.get("five_hour_resets_at"), default_tz=tz)
        pct = q.get("five_hour_used_percent")
        try:
            pct_f = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            pct_f = None
        if five_reset is not None and five_reset > now_utc:
            detail = "live"
            ended = False
            reset_val = q.get("five_hour_resets_at")
            pct_out = pct_f
        else:
            detail = ended_text
            ended = True
            reset_val = None
            pct_out = None
        rows.append({"id": "five_hour", "reset": reset_val, "ended": ended, "percent": pct_out})

    weekly_reset = parse_iso_dt(q.get("weekly_resets_at"), default_tz=tz)
    if weekly_reset is not None:
        ended = weekly_reset <= now_utc
        pct = q.get("weekly_used_percent")
        try:
            pct_f = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            pct_f = None
        rows.append({
            "id": "weekly",
            "reset": q.get("weekly_resets_at"),
            "ended": ended,
            "percent": None if ended else pct_f,
        })

    for ew in q.get("extra_windows") or []:
        if not isinstance(ew, dict):
            continue
        ew_reset = parse_iso_dt(ew.get("resets_at"), default_tz=tz)
        pct = ew.get("used_percent")
        try:
            pct_f = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            pct_f = None
        if ew_reset is not None and ew_reset > now_utc:
            ended = False
            reset_val = ew.get("resets_at")
            pct_out = pct_f
        else:
            ended = True
            reset_val = None
            pct_out = None
        rows.append({
            "id": ew.get("id"),
            "reset": reset_val,
            "ended": ended,
            "percent": pct_out,
        })
    return rows


def formatted_json(value: Any, depth: int = 0) -> str:
    import json as _json
    indent = "  " * depth
    nxt = indent + "  "
    if isinstance(value, dict):
        if not value:
            return "{}"
        keys = sorted(value.keys())
        entries = [nxt + formatted_json(k, depth + 1) + ": " + formatted_json(value[k], depth + 1) for k in keys]
        return "{\n" + ",\n".join(entries) + "\n" + indent + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        entries = [nxt + formatted_json(v, depth + 1) for v in value]
        return "[\n" + ",\n".join(entries) + "\n" + indent + "]"
    if isinstance(value, float):
        text = repr(value)
        if text.endswith(".0"):
            return text[:-2]
        return text
    return _json.dumps(value, ensure_ascii=False)


def build_parity_dump(doc: dict) -> dict:
    result: Dict[str, Any] = {}
    for zone, instant in PARITY_SCENARIOS:
        report = dict(doc)
        report["timezone"] = zone
        tz = get_tz(report)
        now = parse_iso_dt(instant, default_tz=timezone.utc)
        if now is None:
            continue
        now = ensure_aware(now, tz)

        ranges: Dict[str, Any] = {}
        for parity_key in PARITY_RANGE_ORDER:
            tr = PARITY_TUI_RANGES[parity_key]
            filtered = filtered_usage(report, tr, now=now)
            spec = filtered.spec
            share_rows, share = build_share_summary(report, parity_key, now)

            projects: Dict[str, Any] = {}
            for fp in filtered.projects:
                agents = {
                    str(a.get("agent")): {
                        "cost": cents(float(a.get("cost") or 0.0)),
                        "tokens": int((a.get("tokens") or {}).get("total", 0) or 0),
                    }
                    for a in fp.by_agent
                }
                projects[fp.id] = {
                    "cost": cents(fp.cost),
                    "tokens": fp.tokens,
                    "sessions": fp.sessions,
                    "agents": agents,
                }

            agent_costs: Dict[str, float] = {}
            agent_tokens: Dict[str, int] = {}
            for fp in filtered.projects:
                for a in fp.by_agent:
                    ag = str(a.get("agent"))
                    agent_costs[ag] = agent_costs.get(ag, 0.0) + float(a.get("cost") or 0.0)
                    agent_tokens[ag] = agent_tokens.get(ag, 0) + int((a.get("tokens") or {}).get("total", 0) or 0)
            for s in filtered.unattributed.sessions_detail + filtered.excluded.sessions_detail:
                c, t = spec.in_range_cost_and_tokens(s)
                ag = str(s.get("agent") or "")
                agent_costs[ag] = agent_costs.get(ag, 0.0) + c
                agent_tokens[ag] = agent_tokens.get(ag, 0) + t
            agents = {
                ag: {"cost": cents(agent_costs.get(ag, 0.0)), "tokens": agent_tokens.get(ag, 0)}
                for ag in set(agent_costs) | set(agent_tokens)
            }

            models_list = aggregate_models(filtered)
            models = {
                m["id"]: {"cost": cents(m["cost"]), "tokens": m["tokens"], "estimated": m["estimated"]}
                for m in models_list
            }

            agent_starts = {k: stamp(v) for k, v in spec.agent_starts.items()}
            ranges[parity_key] = {
                "start": stamp(spec.start) if spec.start else None,
                "end": stamp(spec.end) if spec.end else None,
                "agentStarts": agent_starts,
                "cost": cents(filtered.cost),
                "tokens": filtered.tokens,
                "sessions": filtered.sessions,
                "projects": projects,
                "models": models,
                "agents": agents,
                "shareRows": share_rows,
                "share": share,
            }

        subs = subscription_rows(report, now)
        quotas: Dict[str, Any] = {}
        for ag, q in (report.get("quota_windows") or {}).items():
            if isinstance(q, dict):
                quotas[str(ag)] = quota_rows_for_agent(q, tz, now)

        heat: Dict[str, Any] = {}
        for p in report.get("projects") or []:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id") or "")
            fb = dominant_fallback_agent(p)
            weeks = heat_strip_weekly(p.get("by_day") or [], now, tz, fb)
            heat[pid] = [
                {
                    "start": stamp(w["start"]),
                    "cost": cents(w["cost"]),
                    "tokens": w["tokens"],
                    "agents": {k: cents(v) for k, v in w["agents"].items()},
                    "agentTokens": dict(w["agentTokens"]),
                }
                for w in weeks
            ]

        gen = parse_iso_dt(report.get("generated_at"), default_tz=tz)
        reference = weekly_tokens_reference(now, gen)
        monday = cal.at_day(tz, cal.monday_on_or_before(cal.local_date(tz, reference)))

        result[f"{zone}|{instant}"] = {
            "ranges": ranges,
            "subscriptions": subs,
            "quotas": quotas,
            "weeklyTokens": weekly_tokens_since(monday, report.get("projects") or [], tz),
            "heat": heat,
        }
    return result


def write_parity_dump_if_requested(doc: dict, default_golden: Optional[str] = None) -> None:
    path = os.environ.get("KANJO_PARITY_DUMP")
    if not path:
        return
    payload = build_parity_dump(doc)
    text = formatted_json(payload) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)