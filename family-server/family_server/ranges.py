"""Pure per-time-range aggregation for the family dashboard (no HTML).

Input is each member's merged summary (see ``aggregate.merge_member_reports``) plus
the per-device summaries; output is one plain dict per range that both the server
renderer and ``static/dashboard.js`` draw from. Daily data only reaches back
``DAY_WINDOW`` days, so day ranges are summed from ``summary.days`` and "all" uses
``all_time`` with a monthly trend.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .aggregate import TOKEN_KEYS, _as_float, _as_int

RANGE_ORDER = ("today", "this_week", "last_week", "7d", "30d", "since_reset", "cycle", "all")
RANGE_LABELS = {
    "today": "今天",
    "this_week": "本周",
    "last_week": "上周",
    "7d": "7 天",
    "30d": "30 天",
    "since_reset": "重置以来",
    "cycle": "周期",
    "all": "全部",
}
DEFAULT_RANGE = "this_week"
DAY_WINDOW = 62
OTHER_LABEL = "其他"
CHART_SERIES_LIMIT = 6

# Model / agent series in the trend chart; member colours come from the dashboard palette.
SERIES_PALETTE = ["#6366f1", "#14b8a6", "#e11d48", "#eab308", "#0ea5e9", "#a855f7"]
OTHER_COLOR = "#94a3b8"


def parse_range_key(raw: Optional[str]) -> str:
    """Valid range key from a query value; anything else falls back to the default."""
    if isinstance(raw, str) and raw in RANGE_LABELS:
        return raw
    return DEFAULT_RANGE


def _parse_day(value: Any) -> Optional[date]:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def last_reset_start(
    resets_at: Optional[datetime],
    window_hours: Any,
    now: datetime,
) -> Optional[datetime]:
    """Start of the current quota week: resets_at - window, rolled forward past stale resets."""
    if resets_at is None:
        return None
    if resets_at.tzinfo is None:
        resets_at = resets_at.replace(tzinfo=timezone.utc)
    hours = _as_float(window_hours)
    if not 1.0 <= hours <= 24 * 62:
        hours = 168.0
    window = timedelta(hours=hours)
    start = resets_at - window
    if start > now:
        # Report claims a reset more than a window away; step back to the one containing now.
        steps = int((start - now) / window) + 1
        start -= window * steps
    elif start + window <= now:
        steps = int((now - start) / window)
        start += window * steps
    return start


def range_bounds(
    key: str,
    today: date,
    cycle: Tuple[date, date, date],
    reset_day: Optional[date] = None,
) -> Optional[dict]:
    """Date bounds for a range, inclusive. None when the range cannot be computed.

    ``cycle`` is (prev_start, current_start, next_start) from compute_cycle_boundaries.
    The comparison period is the previous period of the same length (for "cycle", the
    previous billing cycle); "all" has none.
    """
    week_start = today - timedelta(days=today.weekday())
    if key == "today":
        start = end = today
        prev = (today - timedelta(days=1), today - timedelta(days=1))
        label = "较昨天"
    elif key == "this_week":
        start, end = week_start, week_start + timedelta(days=6)
        prev = (start - timedelta(days=7), start - timedelta(days=1))
        label = "较上周"
    elif key == "last_week":
        start = week_start - timedelta(days=7)
        end = start + timedelta(days=6)
        prev = (start - timedelta(days=7), start - timedelta(days=1))
        label = "较前一周"
    elif key in ("7d", "30d"):
        n = 7 if key == "7d" else 30
        start, end = today - timedelta(days=n - 1), today
        prev = (start - timedelta(days=n), start - timedelta(days=1))
        label = f"较前 {n} 天"
    elif key == "since_reset":
        if reset_day is None or reset_day > today:
            return None
        start, end = reset_day, today
        n = (end - start).days + 1
        prev = (start - timedelta(days=n), start - timedelta(days=1))
        label = f"较前 {n} 天"
    elif key == "cycle":
        prev_start, cur_start, next_start = cycle
        start, end = cur_start, next_start - timedelta(days=1)
        prev = (prev_start, cur_start - timedelta(days=1))
        label = "较上周期"
    elif key == "all":
        return {"start": None, "end": None, "prev": None, "compare_label": None, "bucket": "month"}
    else:
        return None
    return {"start": start, "end": end, "prev": prev, "compare_label": label, "bucket": "day"}


class _Acc:
    """Running sum of Period dicts: tokens, cost, models, providers and agents."""

    def __init__(self) -> None:
        self.tokens = {k: 0 for k in TOKEN_KEYS}
        self.cost = 0.0
        self.models: Dict[str, dict] = {}
        self.providers: Dict[str, dict] = {}
        self.agents: Dict[str, dict] = {}

    def add(self, period: dict) -> None:
        tok = period.get("tokens")
        if isinstance(tok, dict):
            for k in TOKEN_KEYS:
                self.tokens[k] += _as_int(tok.get(k))
        self.cost += _as_float(period.get("cost_usd"))
        for tm in period.get("top_models") or ():
            if not isinstance(tm, dict) or not isinstance(tm.get("model"), str) or not tm["model"]:
                continue
            e = self.models.setdefault(tm["model"], {"tokens": 0, "cost": 0.0, "provider": ""})
            e["tokens"] += _as_int(tm.get("tokens_total"))
            e["cost"] += _as_float(tm.get("cost_usd"))
            if not e["provider"] and isinstance(tm.get("provider"), str):
                e["provider"] = tm["provider"]
        for p in period.get("by_provider") or ():
            if not isinstance(p, dict) or not isinstance(p.get("provider"), str) or not p["provider"]:
                continue
            label = p.get("label") if isinstance(p.get("label"), str) and p.get("label") else p["provider"]
            e = self.providers.setdefault(p["provider"], {"label": label, "tokens": 0, "cost": 0.0})
            e["tokens"] += _as_int((p.get("tokens") or {}).get("total") if isinstance(p.get("tokens"), dict) else 0)
            e["cost"] += _as_float(p.get("cost_usd"))
        for a in period.get("by_agent") or ():
            if not isinstance(a, dict) or not isinstance(a.get("agent"), str) or not a["agent"]:
                continue
            label = a.get("label") if isinstance(a.get("label"), str) and a.get("label") else a["agent"]
            e = self.agents.setdefault(a["agent"], {"label": label, "tokens": 0, "cost": 0.0})
            e["tokens"] += _as_int(a.get("tokens_total"))
            e["cost"] += _as_float(a.get("cost_usd"))

    def merge(self, other: "_Acc") -> None:
        for k in TOKEN_KEYS:
            self.tokens[k] += other.tokens[k]
        self.cost += other.cost
        for name, src in (("models", other.models), ("providers", other.providers), ("agents", other.agents)):
            dst = getattr(self, name)
            for key, e in src.items():
                d = dst.setdefault(key, {k: v for k, v in e.items() if k not in ("tokens", "cost")})
                d["tokens"] = d.get("tokens", 0) + e["tokens"]
                d["cost"] = d.get("cost", 0.0) + e["cost"]
                if name == "models" and not d.get("provider") and e.get("provider"):
                    d["provider"] = e["provider"]


def _sorted_items(entries: Dict[str, dict]) -> List[Tuple[str, dict]]:
    return sorted(entries.items(), key=lambda kv: (-kv[1]["tokens"], -kv[1]["cost"], kv[0]))


def model_rows(acc: _Acc, users: Optional[Dict[str, int]] = None) -> List[dict]:
    """Model ranking with an "其他" row so the token sum always equals the total."""
    total = acc.tokens["total"]
    rows = []
    listed_tokens = 0
    listed_cost = 0.0
    for name, e in _sorted_items(acc.models):
        if e["tokens"] <= 0 and e["cost"] <= 0:
            continue
        listed_tokens += e["tokens"]
        listed_cost += e["cost"]
        row = {
            "model": name,
            "provider": e.get("provider") or "",
            "tokens": e["tokens"],
            "cost": round(e["cost"], 2),
            "share": (e["tokens"] / total * 100.0) if total > 0 else 0.0,
        }
        if users is not None:
            row["users"] = users.get(name, 0)
        rows.append(row)
    rest = total - listed_tokens
    if rest > 0:
        row = {
            "model": OTHER_LABEL,
            "provider": "",
            "tokens": rest,
            "cost": round(max(0.0, acc.cost - listed_cost), 2),
            "share": rest / total * 100.0,
            "other": True,
        }
        if users is not None:
            row["users"] = None
        rows.append(row)
    return rows


def _group_rows(entries: Dict[str, dict], total: int) -> List[dict]:
    return [
        {
            "key": key,
            "label": e["label"],
            "tokens": e["tokens"],
            "cost": round(e["cost"], 2),
            "share": (e["tokens"] / total * 100.0) if total > 0 else 0.0,
        }
        for key, e in _sorted_items(entries)
        if e["tokens"] > 0 or e["cost"] > 0
    ]


def _valid_days(summary: Optional[dict], tracking_start: Optional[date]) -> Dict[date, dict]:
    out: Dict[date, dict] = {}
    if not isinstance(summary, dict):
        return out
    for p in summary.get("days") or ():
        if not isinstance(p, dict):
            continue
        d = _parse_day(p.get("period"))
        if d is None or (tracking_start is not None and d < tracking_start):
            continue
        out[d] = p
    return out


def _valid_months(summary: Optional[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if not isinstance(summary, dict):
        return out
    for p in summary.get("months") or ():
        if not isinstance(p, dict):
            continue
        key = p.get("period")
        if isinstance(key, str) and len(key) == 7 and _parse_day(key + "-01") is not None:
            out[key] = p
    return out


def _all_time_periods(
    summary: Optional[dict],
    tracking_start: Optional[date],
    window_start: date,
) -> Tuple[List[Tuple[str, dict]], Optional[dict]]:
    """(bucketed periods for the monthly trend, period for the totals or None to sum buckets)."""
    months = _valid_months(summary)
    if tracking_start is None:
        all_time = summary.get("all_time") if isinstance(summary, dict) else None
        return sorted(months.items()), all_time if isinstance(all_time, dict) else None
    ts_month = tracking_start.isoformat()[:7]
    periods = [(k, p) for k, p in sorted(months.items()) if k > ts_month]
    if tracking_start >= window_start:
        # The daily window reaches back to tracking_start: count that month exactly.
        days = _valid_days(summary, tracking_start)
        first = [(d.isoformat()[:7], p) for d, p in sorted(days.items()) if d.isoformat()[:7] == ts_month]
        periods = first + periods
    elif ts_month in months:
        periods = [(ts_month, months[ts_month])] + periods
    return periods, None


def _sum_days(days: Dict[date, dict], start: date, end: date) -> _Acc:
    acc = _Acc()
    for d, p in days.items():
        if start <= d <= end:
            acc.add(p)
    return acc


def _change_pct(cur: int, prev: Optional[int]) -> Optional[float]:
    if prev is None or prev <= 0:
        return None
    return (cur - prev) / prev * 100.0


def _series_block(
    keys: List[str],
    per_bucket: Dict[str, Dict[str, int]],
    bucket_totals: List[int],
    labels: Dict[str, str],
) -> List[dict]:
    """Top series by total plus an "其他" series holding each bucket's remainder."""
    totals: Dict[str, int] = {}
    for vals in per_bucket.values():
        for k, v in vals.items():
            totals[k] = totals.get(k, 0) + v
    ranked = [k for k, v in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])) if v > 0]
    top = ranked[:CHART_SERIES_LIMIT]
    series = []
    for i, k in enumerate(top):
        series.append({
            "key": k,
            "label": labels.get(k, k),
            "color": SERIES_PALETTE[i % len(SERIES_PALETTE)],
            "values": [per_bucket.get(b, {}).get(k, 0) for b in keys],
        })
    rest = []
    for idx, b in enumerate(keys):
        listed = sum(per_bucket.get(b, {}).get(k, 0) for k in top)
        rest.append(max(0, bucket_totals[idx] - listed))
    if any(rest):
        series.append({"key": "__other__", "label": OTHER_LABEL, "color": OTHER_COLOR, "values": rest})
    return series


def build_ranges(
    members: List[dict],
    today: date,
    now: datetime,
    cycle: Tuple[date, date, date],
    tracking_start: Optional[date] = None,
    pool: Optional[dict] = None,
    tz: Optional[ZoneInfo] = None,
) -> dict:
    """Aggregate every range for the dashboard.

    ``members`` items: {"id", "name", "color", "summary": merged summary or None,
    "devices": [summary or None, ...]} (devices in display order).
    ``pool`` (optional): {"reset_start": aware datetime, "window_hours": float,
    "weekly_pct": float or None} for the Google AI Ultra pool.
    Returns {"ranges": {key: range dict or None}, "heatmap": {...}}.
    """
    window_start = today - timedelta(days=DAY_WINDOW - 1)
    reset_day = None
    if pool and pool.get("reset_start") is not None:
        rs = pool["reset_start"]
        reset_day = (rs.astimezone(tz) if tz is not None else rs).date()

    member_days = [_valid_days(m.get("summary"), tracking_start) for m in members]
    device_days = [[_valid_days(s, tracking_start) for s in (m.get("devices") or [])] for m in members]

    ranges: Dict[str, Optional[dict]] = {}
    for key in RANGE_ORDER:
        bounds = range_bounds(key, today, cycle, reset_day)
        if bounds is None:
            ranges[key] = None
            continue
        if bounds["bucket"] == "day":
            ranges[key] = _build_day_range(
                key, bounds, members, member_days, device_days, today, window_start, tracking_start, pool, now)
        else:
            ranges[key] = _build_all_range(members, today, window_start, tracking_start)

    heat_days = []
    for i in range(DAY_WINDOW):
        d = window_start + timedelta(days=i)
        tok = 0
        cost = 0.0
        for days in member_days:
            p = days.get(d)
            if p is not None:
                tok += _as_int((p.get("tokens") or {}).get("total") if isinstance(p.get("tokens"), dict) else 0)
                cost += _as_float(p.get("cost_usd"))
        heat_days.append({"date": d.isoformat(), "tokens": tok, "cost": round(cost, 2)})
    heatmap = {"days": heat_days, "max": max((h["tokens"] for h in heat_days), default=0)}
    return {"ranges": ranges, "heatmap": heatmap}


def _finish_range(
    key: str,
    bucket: str,
    buckets: List[str],
    member_accs: List[_Acc],
    member_series: List[Dict[str, _Acc]],
    device_accs: List[List[_Acc]],
    prev_tokens: Optional[List[int]],
    prev_costs: Optional[List[float]],
    members: List[dict],
    elapsed_days: int,
    meta: dict,
) -> dict:
    family = _Acc()
    model_users: Dict[str, int] = {}
    for acc in member_accs:
        family.merge(acc)
        for name, e in acc.models.items():
            if e["tokens"] > 0:
                model_users[name] = model_users.get(name, 0) + 1
    total_tokens = family.tokens["total"]

    member_rows = []
    for i, m in enumerate(members):
        acc = member_accs[i]
        tok = acc.tokens["total"]
        models = model_rows(acc)
        top_model = next((r["model"] for r in models if not r.get("other")), None)
        prev = prev_tokens[i] if prev_tokens is not None else None
        member_rows.append({
            "id": m["id"],
            "tokens": tok,
            "cost": round(acc.cost, 2),
            "share": (tok / total_tokens * 100.0) if total_tokens > 0 else 0.0,
            "prev_tokens": prev,
            "change_pct": _change_pct(tok, prev),
            "top_model": top_model,
            "models": models,
            "devices": [{"tokens": d.tokens["total"], "cost": round(d.cost, 2)} for d in device_accs[i]],
            "series": [member_series[i][b].tokens["total"] if b in member_series[i] else 0 for b in buckets],
        })
    member_rows.sort(key=lambda r: (-r["tokens"], -r["cost"], r["id"]))

    bucket_totals = []
    by_member: Dict[str, Dict[str, int]] = {}
    by_model: Dict[str, Dict[str, int]] = {}
    by_agent: Dict[str, Dict[str, int]] = {}
    agent_labels: Dict[str, str] = {}
    for b in buckets:
        t = 0
        bm: Dict[str, int] = {}
        bmod: Dict[str, int] = {}
        bag: Dict[str, int] = {}
        for i, m in enumerate(members):
            acc = member_series[i].get(b)
            if acc is None:
                continue
            t += acc.tokens["total"]
            bm[str(m["id"])] = acc.tokens["total"]
            for name, e in acc.models.items():
                bmod[name] = bmod.get(name, 0) + e["tokens"]
            for name, e in acc.agents.items():
                bag[name] = bag.get(name, 0) + e["tokens"]
                agent_labels.setdefault(name, e["label"])
        bucket_totals.append(t)
        by_member[b] = bm
        by_model[b] = bmod
        by_agent[b] = bag

    person_series = [
        {
            "key": str(m["id"]),
            "label": m["name"],
            "color": m["color"],
            "values": [by_member[b].get(str(m["id"]), 0) for b in buckets],
        }
        for m in members
    ]
    chart = {
        "buckets": buckets,
        "totals": bucket_totals,
        "person": [s for s in person_series if any(s["values"])],
        "model": _series_block(buckets, by_model, bucket_totals, {}),
        "agent": _series_block(buckets, by_agent, bucket_totals, agent_labels),
    }

    prev_total = sum(prev_tokens) if prev_tokens is not None else None
    peak = None
    for b, t in zip(buckets, bucket_totals):
        if t > 0 and (peak is None or t > peak["tokens"]):
            peak = {"key": b, "tokens": t}
    active = sum(1 for r in member_rows if r["tokens"] > 0)

    models = model_rows(family, model_users)
    meta = dict(meta, bucket_count=len(buckets))
    insights = _insights(key, bucket, family, models, member_rows, members, peak, meta)
    return {
        "key": key,
        "label": RANGE_LABELS[key],
        "bucket": bucket,
        "start": meta.get("start"),
        "end": meta.get("end"),
        "note": meta.get("note"),
        "compare_label": meta.get("compare_label") if prev_tokens is not None else None,
        "elapsed_days": elapsed_days,
        "total": {
            "tokens": family.tokens,
            "cost": round(family.cost, 2),
            "prev_tokens": prev_total,
            "prev_cost": round(sum(prev_costs), 2) if prev_costs is not None else None,
            "change_pct": _change_pct(total_tokens, prev_total),
        },
        "active_members": active,
        "member_count": len(members),
        "daily_avg": int(round(total_tokens / elapsed_days)) if elapsed_days > 0 else 0,
        "peak": peak,
        "members": member_rows,
        "chart": chart,
        "models": models,
        "providers": _group_rows(family.providers, total_tokens),
        "agents": _group_rows(family.agents, total_tokens),
        "insights": insights,
    }


def _build_day_range(
    key: str,
    bounds: dict,
    members: List[dict],
    member_days: List[Dict[date, dict]],
    device_days: List[List[Dict[date, dict]]],
    today: date,
    window_start: date,
    tracking_start: Optional[date],
    pool: Optional[dict],
    now: datetime,
) -> dict:
    start: date = bounds["start"]
    end: date = bounds["end"]
    buckets = []
    d = start
    while d <= end:
        buckets.append(d.isoformat())
        d += timedelta(days=1)

    member_accs = []
    member_series = []
    for days in member_days:
        acc = _Acc()
        series: Dict[str, _Acc] = {}
        for day, p in days.items():
            if start <= day <= end:
                acc.add(p)
                series.setdefault(day.isoformat(), _Acc()).add(p)
        member_accs.append(acc)
        member_series.append(series)
    device_accs = [[_sum_days(dd, start, end) for dd in devs] for devs in device_days]

    prev_tokens = prev_costs = None
    prev_start, prev_end = bounds["prev"]
    if prev_start >= window_start and (tracking_start is None or prev_start >= tracking_start):
        prev_accs = [_sum_days(days, prev_start, prev_end) for days in member_days]
        prev_tokens = [a.tokens["total"] for a in prev_accs]
        prev_costs = [a.cost for a in prev_accs]

    effective_start = max(start, tracking_start) if tracking_start is not None else start
    elapsed = (min(end, today) - effective_start).days + 1
    note = "按天近似：重置当天整天计入" if key == "since_reset" else None
    meta = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "note": note,
        "compare_label": bounds["compare_label"],
        "pool": pool,
        "now": now,
    }
    return _finish_range(key, "day", buckets, member_accs, member_series, device_accs,
                         prev_tokens, prev_costs, members, max(1, elapsed), meta)


def _build_all_range(
    members: List[dict],
    today: date,
    window_start: date,
    tracking_start: Optional[date],
) -> dict:
    member_accs = []
    member_series = []
    device_accs = []
    bucket_set = set()
    first_days: List[date] = []
    for m in members:
        periods, totals_period = _all_time_periods(m.get("summary"), tracking_start, window_start)
        series: Dict[str, _Acc] = {}
        summed = _Acc()
        for k, p in periods:
            series.setdefault(k, _Acc()).add(p)
            summed.add(p)
            bucket_set.add(k)
        if totals_period is not None:
            acc = _Acc()
            acc.add(totals_period)
            fd = _parse_day(totals_period.get("first_day"))
            if fd is not None and acc.tokens["total"] > 0:
                first_days.append(fd)
        else:
            acc = summed
            for k, p in periods:
                fd = _parse_day(p.get("first_day")) or _parse_day(p.get("period")) or _parse_day(k + "-01")
                if fd is not None:
                    first_days.append(max(fd, tracking_start) if tracking_start else fd)
        member_accs.append(acc)
        member_series.append(series)
        devs = []
        for s in m.get("devices") or []:
            dp, dt = _all_time_periods(s, tracking_start, window_start)
            dacc = _Acc()
            if dt is not None:
                dacc.add(dt)
            else:
                for _, p in dp:
                    dacc.add(p)
            devs.append(dacc)
        device_accs.append(devs)

    buckets = sorted(bucket_set)
    first = min(first_days) if first_days else today
    elapsed = max(1, (today - first).days + 1)
    note = f"自统计起始日 {tracking_start.isoformat()} 起" if tracking_start else None
    meta = {"start": first.isoformat() if first_days else None, "end": None, "note": note,
            "compare_label": None}
    return _finish_range("all", "month", buckets, member_accs, member_series, device_accs,
                         None, None, members, elapsed, meta)


def _insights(
    key: str,
    bucket: str,
    family: _Acc,
    models: List[dict],
    member_rows: List[dict],
    members: List[dict],
    peak: Optional[dict],
    meta: dict,
) -> List[dict]:
    """Insight cards; each appears only when its inputs exist."""
    out: List[dict] = []
    t = family.tokens
    denom = t["input"] + t["cache_read"]
    if denom > 0 and t["cache_read"] > 0:
        out.append({"key": "cache", "label": "缓存命中率", "value": f"{t['cache_read'] / denom * 100:.1f}%",
                    "detail": "缓存读取 ÷（输入 + 缓存读取）"})
    if t["total"] > 0 and t["output"] > 0:
        out.append({"key": "output", "label": "输出占比", "value": f"{t['output'] / t['total'] * 100:.1f}%",
                    "detail": "输出 token ÷ 总 token"})
    priced = [r for r in models if not r.get("other") and r["cost"] > 0]
    if priced:
        top = max(priced, key=lambda r: (r["cost"], r["tokens"]))
        out.append({"key": "priciest", "label": "最贵的模型", "value": top["model"],
                    "detail": f"${top['cost']:,.2f}", "cost": top["cost"]})
    if peak is not None and meta.get("bucket_count", 0) > 1:
        out.append({"key": "peak", "label": "用量最多的一天" if bucket == "day" else "用量最多的月份",
                    "value": peak["key"], "tokens": peak["tokens"]})
    if member_rows and member_rows[0]["tokens"] > 0:
        top = member_rows[0]
        name = next((m["name"] for m in members if m["id"] == top["id"]), "")
        out.append({"key": "top_member", "label": "用量最多的人", "value": name,
                    "detail": f"占 {top['share']:.1f}%", "member_id": top["id"]})
    pool = meta.get("pool")
    now = meta.get("now")
    if key in ("since_reset", "this_week") and pool and now is not None:
        pct = pool.get("weekly_pct")
        rs = pool.get("reset_start")
        hours = _as_float(pool.get("window_hours")) or 168.0
        if pct is not None and rs is not None:
            elapsed_h = (now - rs).total_seconds() / 3600.0
            if 1.0 <= elapsed_h < hours:
                projected = pct / elapsed_h * hours
                detail = "按当前速度，重置前会用完" if projected >= 100.0 else "按当前速度，到额度重置时"
                out.append({"key": "projection", "label": "额度池预计用量", "value": f"{projected:.0f}%",
                            "detail": detail})
    return out
