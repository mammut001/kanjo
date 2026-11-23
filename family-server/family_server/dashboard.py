"""Public dashboard for Kanjo family usage behind Firebase Authentication."""

import calendar
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import json
import logging
import math
import mimetypes
import os
from typing import Dict, List, Optional, Set, Tuple, Union
import urllib.parse
from zoneinfo import ZoneInfo

from . import auth
from . import db
from . import ranges
from .aggregate import merge_member_reports
from .rate_limit import RateLimiter

logger = logging.getLogger("family_server.dashboard")

PALETTE = [
    "#3b82f6",  # blue
    "#10b981",  # emerald
    "#f59e0b",  # amber
    "#8b5cf6",  # purple
    "#ec4899",  # pink
    "#06b6d4",  # cyan
    "#f97316",  # orange
    "#84cc16",  # lime
]

COST_NOTE = "按公开 API 价格折算，不是实际支出"

AGENT_LABELS = {
    "antigravity": "Antigravity",
    "claude": "Claude",
    "codex": "Codex",
    "grok": "Grok",
    "qwen": "Qwen",
    "commandcode": "CommandCode",
    "minimax": "MiniMax",
    "opencode": "OpenCode",
    "copilot": "Copilot",
    "pi": "Pi",
    "workbuddy": "WorkBuddy",
    "workbuddy_ai": "WorkBuddy AI",
    "qwenwork": "QwenWork",
    "grok_bot": "Grok Bot",
    "qoderwork": "QoderWork",
    "qodercli": "QoderCLI",
    "qodercli_cn": "QoderCLI CN",
    "zcode": "ZCode",
    "kimicode": "KimiCode",
    "musecode": "MuseCode",
    "codebuddy": "CodeBuddy",
    "qoder_ide": "Qoder IDE",
    "hermes": "Hermes",
    "openclaw": "OpenClaw",
    "devin": "Devin",
    "mimocode": "MimoCode",
    "prime_agent": "Prime Agent",
    "omp": "OMP",
    "deepseek_harness": "DeepSeek Harness",
}


def format_scope(scope: Optional[dict]) -> Optional[str]:
    """Format scope dict into a display string, e.g. '统计范围：Antigravity · 自 2026-11-09 起'."""
    if not isinstance(scope, dict):
        return None
    agents = scope.get("agents")
    since = scope.get("since")

    parts = []
    if agents is not None:
        if isinstance(agents, list):
            if not agents or "all" in agents:
                parts.append("全部 agent")
            else:
                agent_names = []
                for a in agents:
                    a_str = str(a)
                    label = AGENT_LABELS.get(a_str, a_str)
                    agent_names.append(label)
                parts.append(", ".join(agent_names))
        elif isinstance(agents, str):
            if agents == "all":
                parts.append("全部 agent")
            else:
                parts.append(AGENT_LABELS.get(agents, agents))

    if since:
        parts.append(f"自 {since} 起")

    if not parts:
        return None

    return f"统计范围：{' · '.join(parts)}"


def _shift_month(year: int, month: int, delta: int) -> Tuple[int, int]:
    """Shift (year, month) by delta months."""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _anchor_date_for_month(year: int, month: int, anchor: int) -> date:
    """Return anchor day clamped to the maximum days in the given month."""
    max_days = calendar.monthrange(year, month)[1]
    day = min(int(anchor), max_days)
    return date(year, month, day)


def compute_cycle_boundaries(
    anchor: Optional[int],
    ref_dt_or_date: Union[date, datetime],
    tz: Optional[ZoneInfo] = None,
) -> Tuple[date, date, date]:
    """Calculate (prev_start, current_start, next_start) as date objects.

    If anchor is None, falls back to calendar month (anchor=1).
    Clamping: anchor 31 in Feb is 28 (or 29 in leap year), 30 in April, etc.
    Current cycle interval is [current_start, next_start).
    Previous cycle interval is [prev_start, current_start).
    """
    if isinstance(ref_dt_or_date, datetime):
        if tz is not None and ref_dt_or_date.tzinfo is not None:
            local_date = ref_dt_or_date.astimezone(tz).date()
        else:
            local_date = ref_dt_or_date.date()
    else:
        local_date = ref_dt_or_date

    eff_anchor = int(anchor) if anchor is not None else 1
    y, m = local_date.year, local_date.month

    cand_start = _anchor_date_for_month(y, m, eff_anchor)
    if cand_start <= local_date:
        current_start = cand_start
    else:
        prev_y, prev_m = _shift_month(y, m, -1)
        current_start = _anchor_date_for_month(prev_y, prev_m, eff_anchor)

    next_y, next_m = _shift_month(current_start.year, current_start.month, 1)
    next_start = _anchor_date_for_month(next_y, next_m, eff_anchor)

    prev_y, prev_m = _shift_month(current_start.year, current_start.month, -1)
    prev_start = _anchor_date_for_month(prev_y, prev_m, eff_anchor)

    return prev_start, current_start, next_start


def load_firebase_config() -> dict:
    """Load Firebase web configuration from FIREBASE_WEB_CONFIG_JSON environment variable."""
    env_json = os.environ.get("FIREBASE_WEB_CONFIG_JSON")
    if env_json:
        try:
            return json.loads(env_json)
        except Exception as e:
            logger.warning("Failed to parse FIREBASE_WEB_CONFIG_JSON: %s", e)
    return {}


def parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """Parse ISO timestamp with Python 3.9 compatibility."""
    if not ts:
        return None
    try:
        clean = ts.strip()
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        parsed = datetime.fromisoformat(clean)
    except Exception:
        return None
    # Client-supplied: extreme years would overflow timezone conversion and date math.
    if not 2000 <= parsed.year <= 2100:
        return None
    return parsed


def format_tokens(n: int) -> str:
    """Format token count with human-readable suffixes."""
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def format_cost(cost: float) -> str:
    """Format cost as USD string."""
    return f"${cost:,.2f}"


def format_dt(dt: Optional[datetime], tz: Optional[ZoneInfo] = None) -> str:
    """Format datetime as YYYY-MM-DD HH:MM, converted to ``tz`` when given.

    Naive datetimes are treated as UTC (that is how the server stores them).
    """
    if not dt:
        return "—"
    if tz is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(tz)
    return dt.strftime("%Y-%m-%d %H:%M")


def _as_float(value) -> Optional[float]:
    """Number from a client-supplied value; None for anything else (incl. bool)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def pool_tokens_for_day(day: dict, fallback_total: int) -> int:
    """Tokens that count against the Google AI Ultra pool for one daily Period."""
    by_agent = day.get("by_agent")
    if isinstance(by_agent, list):
        ag = [a for a in by_agent if isinstance(a, dict) and a.get("agent") == "antigravity"]
        if ag:
            return int(sum(_as_float(a.get("tokens_total")) or 0 for a in ag))
    by_provider = day.get("by_provider")
    if isinstance(by_provider, list):
        gp = [p for p in by_provider if isinstance(p, dict) and p.get("provider") == "google"]
        if gp:
            return int(sum(_as_float((p.get("tokens") or {}).get("total")) or 0 for p in gp))
    if (isinstance(by_agent, list) and by_agent) or (isinstance(by_provider, list) and by_provider):
        return 0  # the day has a breakdown, and none of it is pool usage
    return int(fallback_total or 0)


# Antigravity reports Gemini limits in the standard weekly / 5-hour fields and the
# Claude/GPT ("3p") group as extra windows.
_EXTRA_WINDOW_LABELS = {
    "3p-weekly": "Claude / GPT 模型 · 本周",
    "3p-5h": "Claude / GPT 模型 · 5 小时",
}


def pool_windows_from_quota(qw: dict) -> List[dict]:
    """Rows {label, used_percent, resets_at} for every quota window Antigravity reported."""
    rows: List[dict] = []
    weekly = _as_float(qw.get("weekly_used_percent"))
    if weekly is not None:
        rows.append({"label": "Gemini 模型 · 本周", "used_percent": weekly,
                     "resets_at": qw.get("weekly_resets_at")})
    five = _as_float(qw.get("five_hour_used_percent"))
    if five is not None:
        rows.append({"label": "Gemini 模型 · 5 小时", "used_percent": five,
                     "resets_at": qw.get("five_hour_resets_at")})
    extra = qw.get("extra_windows")
    if isinstance(extra, list):
        for w in extra:
            if not isinstance(w, dict):
                continue
            pct = _as_float(w.get("used_percent"))
            if pct is None:
                continue
            wid = w.get("id") if isinstance(w.get("id"), str) else ""
            label = _EXTRA_WINDOW_LABELS.get(wid)
            if label is None:
                raw = w.get("label") if isinstance(w.get("label"), str) else wid
                label = (raw or "其他额度")[:60]
            rows.append({"label": label, "used_percent": pct, "resets_at": w.get("resets_at")})
    return rows


_OS_LABELS = {
    "macos": "macOS",
    "linux": "Linux",
    "windows": "Windows",
}


def format_os(os_name: str) -> str:
    """Format normalized OS name for display."""
    if not os_name:
        return "未知系统"
    return _OS_LABELS.get(os_name, os_name)


@lru_cache(maxsize=24)
def _cached_dashboard_merge(report_rows: tuple, member_names: tuple) -> Optional[dict]:
    """Cache private, read-only dashboard aggregates by their complete inputs.

    Including row contents and names makes updates, deletes, and database replacement
    invalidate naturally, without relying on process-local write notifications.
    """
    return merge_member_reports([dict(row) for row in report_rows], dict(member_names))


STALE_SECONDS = 2 * 3600.0


def generate_dashboard_html(
    db_path: str,
    now: Optional[datetime] = None,
    user_email: Optional[str] = None,
    range_key: Optional[str] = None,
) -> str:
    """Render the full single-page dashboard HTML (server-rendered for ``range_key``)."""
    with db.get_connection(db_path) as conn:
        records = db.get_all_latest_device_reports(conn)
        all_members = db.list_members(conn, include_merged=True)
        server_settings = db.get_all_settings(conn)
    member_names = {m["id"]: m["name"] for m in all_members}
    name_items = tuple(sorted(member_names.items()))

    tz_name = server_settings.get("timezone") or os.environ.get("FAMILY_TIMEZONE", "America/Toronto")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Toronto")
        tz_name = "America/Toronto"

    if now is None:
        now = datetime.now(timezone.utc)

    local_now = now.astimezone(tz)
    local_today = local_now.date()

    cycle_anchor_day_raw = server_settings.get("cycle_anchor_day")
    cycle_anchor_day = None
    has_cycle_setting = False
    if cycle_anchor_day_raw is not None and cycle_anchor_day_raw.strip():
        try:
            val = int(cycle_anchor_day_raw.strip())
            if 1 <= val <= 31:
                cycle_anchor_day = val
                has_cycle_setting = True
        except ValueError:
            pass

    tracking_start_str = (server_settings.get("tracking_start") or "").strip() or None
    tracking_start = None
    if tracking_start_str:
        try:
            tracking_start = date.fromisoformat(tracking_start_str)
        except ValueError:
            tracking_start = None

    cycle = compute_cycle_boundaries(cycle_anchor_day, local_today, tz)
    prev_start, current_start, next_start = cycle
    cycle_last_day = next_start - timedelta(days=1)
    cycle_range_str = f"本周期 {current_start.strftime('%m/%d')} – {cycle_last_day.strftime('%m/%d')}"
    days_remaining = max(0, (next_start - local_today).days)

    # Process member data
    members_processed = []
    quota_pool_entries = []

    for idx, rec in enumerate(records):
        m = rec["member"]
        reports = rec["reports"]
        color = PALETTE[idx % len(PALETTE)]

        member_info = {
            "id": m["id"],
            "name": m["name"],
            "color": color,
            "has_report": False,
            "label": None,
            "received_at": None,
            "status": "never",
            "daily_pool_tokens": {},
            "scope_str": None,
            "devices": [],
            "device_summaries": [],
            "summary": None,
            "legacy_excluded_count": 0,
        }

        merged = _cached_dashboard_merge(
            tuple(tuple(report.items()) for report in reports),
            name_items,
        )
        if merged is not None:
            meta = merged["_meta"]
            member_info["has_report"] = True
            rec_dt = meta.get("latest_received_at")
            member_info["received_at"] = rec_dt
            member_info["status"] = "stale"
            if rec_dt and (now - rec_dt).total_seconds() <= STALE_SECONDS:
                member_info["status"] = "ok"

            member_info["label"] = merged.get("member_label")
            member_info["scope_str"] = format_scope(merged.get("scope"))
            member_info["devices"] = meta.get("devices", [])
            member_info["legacy_excluded_count"] = int(
                meta.get("legacy_excluded_count") or (1 if meta.get("legacy_excluded") else 0)
            )
            summary = merged.get("summary", {})
            member_info["summary"] = summary

            # Per-device summaries for the expanded ranking row; one device is the merge itself.
            if len(member_info["devices"]) == 1:
                member_info["device_summaries"] = [summary]
            else:
                by_id = {str(r.get("device_id") or ""): r for r in reports}
                for dev in member_info["devices"]:
                    row = by_id.get(str(dev.get("device_id") or ""))
                    single = None
                    if row is not None:
                        single = _cached_dashboard_merge((tuple(row.items()),), name_items)
                    member_info["device_summaries"].append(single.get("summary") if single else None)

            # Quota windows: feed per-device entries into the pool logic
            for dev in member_info["devices"]:
                qw = dev.get("quota_windows") or {}
                dev_plans = dev.get("plans") or merged.get("plans") or {}
                ag_qw = qw.get("antigravity")
                if isinstance(ag_qw, dict):
                    pct = _as_float(ag_qw.get("weekly_used_percent"))  # None = unknown
                    resets_at = ag_qw.get("weekly_resets_at")
                    plan_name = dev_plans.get("antigravity", "Google AI Ultra") if isinstance(dev_plans, dict) else "Google AI Ultra"
                    dev_quota = {
                        "weekly_used_percent": pct,
                        "weekly_resets_at": resets_at,
                        "plan": plan_name,
                    }

                    dev_label = member_info["label"]
                    if len(member_info["devices"]) > 1 and dev.get("device_name"):
                        dev_label = dev["device_name"] if not dev_label else f"{dev_label} · {dev['device_name']}"

                    quota_pool_entries.append({
                        "member_name": m["name"],
                        "member_label": dev_label,
                        "device_name": dev.get("device_name") if not dev.get("is_legacy") else None,
                        "color": color,
                        "quota": dev_quota,
                        "windows": pool_windows_from_quota(ag_qw),
                        "weekly_resets_at": resets_at,
                        "weekly_window_hours": ag_qw.get("weekly_window_hours"),
                        "received_at": dev.get("received_at") or rec_dt,
                    })

            for d in summary.get("days", []):
                if not isinstance(d, dict):
                    continue
                p_str = d.get("period")
                if not p_str or not isinstance(p_str, str):
                    continue
                # Tracking start filtering: usage before tracking_start is ignored everywhere on the dashboard
                if tracking_start_str and p_str < tracking_start_str:
                    continue
                tok_cnt = (d.get("tokens") or {}).get("total", 0)
                member_info["daily_pool_tokens"][p_str] = pool_tokens_for_day(d, tok_cnt)

        members_processed.append(member_info)

    # Pool status: the most recent member report decides (all members of a shared
    # pool see the same numbers; the freshest one is the most accurate).
    pool_latest = None
    for q in quota_pool_entries:
        if q.get("received_at") is None:
            continue
        if pool_latest is None or q["received_at"] > pool_latest["received_at"]:
            pool_latest = q
    if pool_latest is None and quota_pool_entries:
        pool_latest = quota_pool_entries[0]

    # This quota week = [last weekly reset, next reset), counted per local day.
    pool_info = None
    pool_week_start = None
    pool_week_users = []
    pool_week_total = 0
    if pool_latest is not None:
        week_reset = parse_iso(pool_latest.get("weekly_resets_at"))
        reset_start = ranges.last_reset_start(week_reset, pool_latest.get("weekly_window_hours"), now)
        if reset_start is not None:
            pool_week_start = reset_start.astimezone(tz)
            pool_info = {
                "reset_start": reset_start,
                "window_hours": _as_float(pool_latest.get("weekly_window_hours")) or 168.0,
                "weekly_pct": pool_latest["quota"]["weekly_used_percent"],
            }
            week_start_str = pool_week_start.date().isoformat()
            today_str = local_today.isoformat()
            for m in members_processed:
                # Same days as the "since reset" range, so both read the same totals.
                t = sum(v for k, v in m["daily_pool_tokens"].items() if week_start_str <= k <= today_str)
                pool_week_total += t
                pool_week_users.append({"name": m["name"], "label": m["label"], "color": m["color"], "tokens": t})
            pool_week_users = [u for u in pool_week_users if u["tokens"] > 0]
            pool_week_users.sort(key=lambda u: u["tokens"], reverse=True)

    # Per-member view only when members disagree (pool may not actually be shared).
    weekly_vals = [q["quota"]["weekly_used_percent"] for q in quota_pool_entries
                   if q["quota"]["weekly_used_percent"] is not None]
    show_per_member = len(weekly_vals) > 1 and (max(weekly_vals) - min(weekly_vals)) > 2.0

    range_data = ranges.build_ranges(
        [
            {
                "id": m["id"],
                "name": m["name"],
                "color": m["color"],
                "summary": m["summary"],
                "devices": m["device_summaries"],
            }
            for m in members_processed
        ],
        today=local_today,
        now=now,
        cycle=cycle,
        tracking_start=tracking_start,
        pool=pool_info,
        tz=tz,
    )

    unique_scopes = []
    for m in members_processed:
        s = m.get("scope_str")
        if s and s not in unique_scopes:
            unique_scopes.append(s)

    from . import dashboard_view

    return dashboard_view.render_page({
        "range_key": ranges.parse_range_key(range_key),
        "ranges": range_data["ranges"],
        "heatmap": range_data["heatmap"],
        "members": members_processed,
        "tz": tz,
        "tz_name": tz_name,
        "now": now,
        "local_now": local_now,
        "today": local_today,
        "user_email": user_email,
        "has_cycle_setting": has_cycle_setting,
        "cycle_range_str": cycle_range_str,
        "days_remaining": days_remaining,
        "next_start": next_start,
        "top_scope_str": " · ".join(unique_scopes) if unique_scopes else None,
        "pool_entries": quota_pool_entries,
        "pool_latest": pool_latest,
        "pool_week_start": pool_week_start,
        "pool_week_users": pool_week_users,
        "pool_week_total": pool_week_total,
        "show_per_member": show_per_member,
    })


def render_settings_html(
    settings: Dict[str, str],
    user_email: Optional[str] = None,
    error: Optional[str] = None,
    saved: bool = False,
    form_data: Optional[Dict[str, str]] = None,
) -> str:
    """Render the admin settings page HTML."""
    if form_data:
        cycle_anchor_day = form_data.get("cycle_anchor_day", "")
        tracking_start = form_data.get("tracking_start", "")
        tz_name = form_data.get("timezone", "")
    else:
        cycle_anchor_day = settings.get("cycle_anchor_day", "")
        tracking_start = settings.get("tracking_start", "")
        tz_name = settings.get("timezone") or os.environ.get("FAMILY_TIMEZONE", "America/Toronto")

    escaped_day = html.escape(str(cycle_anchor_day or ""), quote=True)
    escaped_start = html.escape(str(tracking_start or ""), quote=True)
    escaped_tz = html.escape(str(tz_name or ""), quote=True)

    doc = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "  <title>计费周期与管理设置 · Kanjo</title>",
        "  <style>",
        """
        :root {
          --bg: #f8fafc;
          --card-bg: #ffffff;
          --card-border: #e2e8f0;
          --text-primary: #0f172a;
          --text-secondary: #475569;
          --text-muted: #94a3b8;
          --accent: #2563eb;
          --accent-hover: #1d4ed8;
          --badge-bg: #f1f5f9;
          --green: #10b981;
          --green-bg: #dcfce7;
          --green-text: #15803d;
          --red: #ef4444;
          --red-bg: #fee2e2;
          --red-text: #b91c1c;
          --shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1);
        }
        @media (prefers-color-scheme: dark) {
          :root {
            --bg: #0f172a;
            --card-bg: #1e293b;
            --card-border: #334155;
            --text-primary: #f8fafc;
            --text-secondary: #cbd5e1;
            --text-muted: #64748b;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --badge-bg: #334155;
            --green-bg: #14532d;
            --green-text: #86efac;
            --red-bg: #7f1d1d;
            --red-text: #fca5a5;
            --shadow: 0 1px 3px 0 rgb(0 0 0 / 0.3);
          }
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
          background: var(--bg);
          color: var(--text-primary);
          line-height: 1.5;
          padding: 2rem 1rem 3rem 1rem;
        }
        .container { max-width: 640px; margin: 0 auto; }
        .back-link {
          display: inline-flex;
          align-items: center;
          gap: 0.25rem;
          color: var(--accent);
          text-decoration: none;
          font-size: 0.88rem;
          margin-bottom: 1.25rem;
          transition: opacity 0.15s;
        }
        .back-link:hover { text-decoration: underline; }
        .card {
          background: var(--card-bg);
          border: 1px solid var(--card-border);
          border-radius: 12px;
          padding: 2rem;
          box-shadow: var(--shadow);
        }
        h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 0.4rem; }
        .page-desc { font-size: 0.88rem; color: var(--text-secondary); margin-bottom: 1.75rem; }
        .alert {
          padding: 0.75rem 1rem;
          border-radius: 8px;
          font-size: 0.88rem;
          margin-bottom: 1.5rem;
        }
        .alert-success { background: var(--green-bg); color: var(--green-text); }
        .alert-error { background: var(--red-bg); color: var(--red-text); }
        .form-group { margin-bottom: 1.5rem; }
        label {
          display: block;
          font-size: 0.9rem;
          font-weight: 600;
          margin-bottom: 0.35rem;
        }
        .field-desc { font-size: 0.8rem; color: var(--text-muted); margin-top: 0.25rem; }
        .input-text {
          width: 100%;
          padding: 0.6rem 0.75rem;
          border: 1px solid var(--card-border);
          border-radius: 8px;
          background: var(--bg);
          color: var(--text-primary);
          font-size: 0.95rem;
        }
        .input-text:focus {
          outline: none;
          border-color: var(--accent);
          box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
        }
        .btn-row { display: flex; align-items: center; gap: 0.75rem; margin-top: 2rem; }
        .btn-submit {
          background: var(--accent);
          color: #fff;
          border: none;
          padding: 0.65rem 1.25rem;
          border-radius: 8px;
          font-size: 0.95rem;
          font-weight: 600;
          cursor: pointer;
          transition: background 0.15s;
        }
        .btn-submit:hover { background: var(--accent-hover); }
        .btn-cancel {
          background: transparent;
          color: var(--text-secondary);
          border: 1px solid var(--card-border);
          padding: 0.65rem 1.25rem;
          border-radius: 8px;
          font-size: 0.95rem;
          text-decoration: none;
        }
        .btn-cancel:hover { background: var(--badge-bg); }
        </style>
        """,
        "</head>",
        "<body>",
        '  <div class="container">',
        '    <a href="/" class="back-link">← 返回看板</a>',
        '    <div class="card">',
        '      <h1>计费周期与管理设置</h1>',
        '      <p class="page-desc">由家庭管理员设定计费周期起始日与统计范围，整个家庭看板将按该周期呈现用量。</p>',
    ]

    if saved:
        doc.append('      <div class="alert alert-success">✓ 设置已成功保存生效</div>')
    if error:
        doc.append(f'      <div class="alert alert-error">{html.escape(error)}</div>')

    doc.extend([
        '      <form method="POST" action="/settings">',
        '        <div class="form-group">',
        '          <label for="cycle_anchor_day">计费周期起始日 (1–31)</label>',
        f'          <input type="number" id="cycle_anchor_day" name="cycle_anchor_day" min="1" max="31" value="{escaped_day}" required class="input-text" placeholder="例如 9">',
        '          <div class="field-desc">Google AI Ultra 订阅每月续费日（1–31）。若遇较短月份（如 2 月遇 31 日），系统将自动使用该月最后一天。</div>',
        '        </div>',
        '        <div class="form-group">',
        '          <label for="tracking_start">统计起始日期 (可选)</label>',
        f'          <input type="text" id="tracking_start" name="tracking_start" value="{escaped_start}" class="input-text" placeholder="YYYY-MM-DD，如 2026-11-09">',
        '          <div class="field-desc">早于该日期的历史用量在看板各处均被完全忽略。留空则统计历史全部可用数据。</div>',
        '        </div>',
        '        <div class="form-group">',
        '          <label for="timezone">统计时区 (IANA 时区名称)</label>',
        f'          <input type="text" id="timezone" name="timezone" value="{escaped_tz}" required class="input-text" placeholder="America/Toronto">',
        '          <div class="field-desc">面板计算计费周期边界所采用的时区，默认从环境变量 FAMILY_TIMEZONE 读取，或 America/Toronto。</div>',
        '        </div>',
        '        <div class="btn-row">',
        '          <button type="submit" class="btn-submit">保存设置</button>',
        '          <a href="/" class="btn-cancel">取消</a>',
        '        </div>',
        '      </form>',
        '    </div>',
        '  </div>',
        '</body>',
        '</html>',
    ])
    return "\n".join(doc)


def render_login_html(firebase_config: dict) -> str:
    """Render the Firebase Google sign-in page."""
    cfg_json = json.dumps(firebase_config)
    escaped_cfg = html.escape(cfg_json)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Kanjo 家庭用量 - 登录</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --danger-bg: #451a1a;
      --danger-text: #fca5a5;
      --danger-border: #7f1d1d;
    }}
    @media (prefers-color-scheme: light) {{
      :root {{
        --bg: #f8fafc;
        --card-bg: #ffffff;
        --border: #e2e8f0;
        --text: #0f172a;
        --text-muted: #64748b;
        --primary: #2563eb;
        --primary-hover: #1d4ed8;
        --danger-bg: #fef2f2;
        --danger-text: #991b1b;
        --danger-border: #fecaca;
      }}
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.5rem;
    }}
    .login-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 2.5rem 2rem;
      width: 100%;
      max-width: 420px;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.2);
      text-align: center;
    }}
    .brand-icon {{
      width: 48px;
      height: 48px;
      margin: 0 auto 1.25rem;
      background: linear-gradient(135deg, #3b82f6, #8b5cf6);
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      font-weight: 700;
      font-size: 24px;
    }}
    h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 0.5rem; }}
    p.subtitle {{ color: var(--text-muted); font-size: 0.875rem; margin-bottom: 2rem; }}
    .btn-google {{
      width: 100%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.75rem;
      background: #ffffff;
      color: #1f2937;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      padding: 0.75rem 1rem;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      transition: background-color 0.15s, border-color 0.15s, box-shadow 0.15s;
    }}
    .btn-google:hover:not(:disabled) {{
      background: #f9fafb;
      border-color: #9ca3af;
      box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
    }}
    .btn-google:disabled {{
      opacity: 0.6;
      cursor: not-allowed;
    }}
    .error-box {{
      margin-top: 1.25rem;
      padding: 0.75rem 1rem;
      border-radius: 8px;
      background: var(--danger-bg);
      color: var(--danger-text);
      border: 1px solid var(--danger-border);
      font-size: 0.875rem;
      text-align: left;
    }}
    .footer-note {{
      margin-top: 2rem;
      font-size: 0.75rem;
      color: var(--text-muted);
    }}
  </style>
</head>
<body>
  <div class="login-card">
    <div class="brand-icon">K</div>
    <h1>Kanjo 家庭用量</h1>
    <p class="subtitle">请使用授权的 Google 账号登录查看面板</p>
    <div id="firebase-config" data-config="{escaped_cfg}"></div>
    <button id="login-btn" class="btn-google" type="button">
      <svg width="18" height="18" viewBox="0 0 24 24">
        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
      </svg>
      <span id="login-btn-text">使用 Google 账号登录</span>
      <span id="login-btn-spinner" style="display:none;">⏳</span>
    </button>
    <div id="error-box" class="error-box" style="display:none;" role="alert"></div>
    <div class="footer-note">仅限预先登记的家庭成员及管理员访问</div>
  </div>
  <script type="module" src="/static/login.js"></script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler for the public dashboard listener (port 8787)."""

    server_version = "KanjoFamilyDashboard/0.2"

    db_path: str = ""
    firebase_config: dict = {}
    project_id: str = ""
    admin_emails: Set[str] = set()
    public_origin: str = ""
    csp_header: str = ""
    session_rate_limiter: Optional[RateLimiter] = None
    jwk_manager: Optional[auth.JWKManager] = None

    def log_message(self, format: str, *args) -> None:
        logger.info("%s - request handled", self.address_string())

    def _send_response_with_headers(
        self,
        status: int,
        content_type: str,
        body: bytes,
        headers: Optional[Dict[str, str]] = None,
        is_authenticated: bool = False,
    ) -> None:
        """Send HTTP response with required security headers and optional custom headers."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Content-Security-Policy",
            self.csp_header or (
                "default-src 'self'; "
                "script-src 'self' https://apis.google.com https://www.gstatic.com; "
                "connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://www.googleapis.com; "
                "frame-src 'none'; "
                "img-src 'self' data: https://lh3.googleusercontent.com; "
                "style-src 'self' 'unsafe-inline'; "
                "base-uri 'none'; "
                "form-action 'self'; "
                "frame-ancestors 'none'"
            ),
        )
        self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.send_header("X-Content-Type-Options", "nosniff")
        # same-origin (not no-referrer): with no-referrer, browsers send
        # "Origin: null" on same-origin form POSTs, which breaks the CSRF check.
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
        if is_authenticated:
            self.send_header("Cache-Control", "no-store")
        if headers:
            for k, v in headers.items():
                self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    def _get_session_id_from_cookie(self) -> Optional[str]:
        """Extract __Host-family_session value from Cookie header."""
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("__Host-family_session="):
                return part[len("__Host-family_session="):].strip()
        return None

    def _get_current_session(self) -> Optional[Dict]:
        """Lookup active session in SQLite DB."""
        session_id = self._get_session_id_from_cookie()
        if not session_id:
            return None
        with db.get_connection(self.db_path) as conn:
            session = db.get_session(conn, session_id)
            if session and self.admin_emails:
                email = (session.get("email") or "").lower().strip()
                if email not in self.admin_emails:
                    # Email was removed from FAMILY_ADMIN_EMAILS: revoke the session.
                    db.delete_session(conn, session_id)
                    return None
            return session

    def _check_csrf(self) -> bool:
        """Verify CSRF protections on POST requests.
        
        Requires either:
        - Origin matching FAMILY_PUBLIC_ORIGIN
        - Sec-Fetch-Site: same-origin (when Origin is omitted, or is the opaque
          "null" that browsers send under a no-referrer policy)
        """
        origin = self.headers.get("Origin")
        if origin and origin != "null":
            return origin.rstrip("/") == self.public_origin.rstrip("/")
        sec_fetch_site = self.headers.get("Sec-Fetch-Site")
        return sec_fetch_site == "same-origin"

    def _get_client_ip(self) -> str:
        """Get client IP for rate limiting.
        
        CF-Connecting-IP is trustworthy only because the listener is reachable
        strictly via Cloudflare Tunnel on the internal Docker bridge network.
        """
        cf_ip = self.headers.get("CF-Connecting-IP")
        if cf_ip and cf_ip.strip():
            return cf_ip.strip()
        return self.client_address[0]

    def do_GET(self) -> None:
        # 1. Health check
        if self.path == "/healthz":
            payload = b'{"status":"ok"}'
            self._send_response_with_headers(HTTPStatus.OK, "application/json; charset=utf-8", payload)
            return

        # 2. Public Firebase web config
        if self.path == "/auth/config":
            payload = json.dumps(self.firebase_config).encode("utf-8")
            self._send_response_with_headers(HTTPStatus.OK, "application/json; charset=utf-8", payload)
            return

        # 3. Static assets (/static/...)
        if self.path.startswith("/static/"):
            rel_path = self.path[len("/static/"):].split("?")[0]
            static_dir = os.path.join(os.path.dirname(__file__), "static")
            safe_target = os.path.normpath(os.path.join(static_dir, rel_path))

            # Prevent directory traversal
            if safe_target.startswith(static_dir) and os.path.isfile(safe_target):
                if safe_target.endswith(".js"):
                    mime = "application/javascript; charset=utf-8"
                else:
                    mime, _ = mimetypes.guess_type(safe_target)
                    if not mime:
                        mime = "application/octet-stream"
                    if mime.startswith("text/") or mime in ("application/javascript", "application/json"):
                        mime += "; charset=utf-8"
                with open(safe_target, "rb") as f:
                    content = f.read()
                self._send_response_with_headers(HTTPStatus.OK, mime, content)
                return
            else:
                self._send_response_with_headers(
                    HTTPStatus.NOT_FOUND,
                    "text/plain; charset=utf-8",
                    b"Static file not found",
                )
                return

        # 4. Login page (/login)
        if self.path == "/login" or self.path.startswith("/login?"):
            # If user already has a valid session, redirect to dashboard
            session = self._get_current_session()
            if session:
                self._send_response_with_headers(
                    HTTPStatus.FOUND,
                    "text/html; charset=utf-8",
                    b'<!DOCTYPE html><html><body>Redirecting to <a href="/">/</a>...</body></html>',
                    headers={"Location": "/"},
                )
                return

            html_body = render_login_html(self.firebase_config).encode("utf-8")
            self._send_response_with_headers(HTTPStatus.OK, "text/html; charset=utf-8", html_body)
            return

        # 5. Protected routes (requires valid session)
        session = self._get_current_session()
        if not session:
            accept = self.headers.get("Accept", "")
            content_type = self.headers.get("Content-Type", "")
            if "application/json" in accept or "application/json" in content_type:
                self._send_response_with_headers(
                    HTTPStatus.UNAUTHORIZED,
                    "application/json; charset=utf-8",
                    b'{"error":"Unauthorized"}',
                )
            else:
                self._send_response_with_headers(
                    HTTPStatus.FOUND,
                    "text/html; charset=utf-8",
                    b'<!DOCTYPE html><html><body>Redirecting to <a href="/login">/login</a>...</body></html>',
                    headers={"Location": "/login"},
                )
            return

        if self.path == "/" or self.path.startswith("/?"):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            html_content = generate_dashboard_html(
                self.db_path,
                user_email=session["email"],
                range_key=(query.get("range") or [None])[0],
            )
            self._send_response_with_headers(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                html_content.encode("utf-8"),
                is_authenticated=True,
            )
            return

        if self.path == "/settings" or self.path.startswith("/settings?"):
            user_email = session.get("email", "").lower().strip()
            if self.admin_emails and user_email not in self.admin_emails:
                self._send_response_with_headers(
                    HTTPStatus.FORBIDDEN,
                    "text/html; charset=utf-8",
                    b'<!DOCTYPE html><html><body><h1>403 Forbidden: Admin access required</h1></body></html>',
                    is_authenticated=True,
                )
                return

            with db.get_connection(self.db_path) as conn:
                current_settings = db.get_all_settings(conn)

            saved = "saved=1" in self.path
            html_content = render_settings_html(current_settings, user_email=user_email, saved=saved)
            self._send_response_with_headers(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                html_content.encode("utf-8"),
                is_authenticated=True,
            )
            return

        # 404 for unknown authenticated paths
        not_found = b'<!DOCTYPE html><html><body><h1>404 Not Found</h1></body></html>'
        self._send_response_with_headers(
            HTTPStatus.NOT_FOUND,
            "text/html; charset=utf-8",
            not_found,
            is_authenticated=True,
        )

    def do_POST(self) -> None:
        # 1. CSRF validation on all dashboard POSTs
        if not self._check_csrf():
            logger.warning("CSRF check failed on dashboard POST")
            self._send_response_with_headers(
                HTTPStatus.FORBIDDEN,
                "application/json; charset=utf-8",
                b'{"error":"Forbidden: CSRF verification failed"}',
            )
            return

        # 2. Logout (/auth/logout)
        if self.path == "/auth/logout":
            cookie_id = self._get_session_id_from_cookie()
            if cookie_id:
                with db.get_connection(self.db_path) as conn:
                    db.delete_session(conn, cookie_id)

            clear_cookie = (
                "__Host-family_session=; Path=/; Secure; HttpOnly; SameSite=Strict; "
                "Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            )
            accept = self.headers.get("Accept", "")
            if "application/json" in accept:
                self._send_response_with_headers(
                    HTTPStatus.OK,
                    "application/json; charset=utf-8",
                    b'{"status":"ok"}',
                    headers={"Set-Cookie": clear_cookie},
                )
            else:
                self._send_response_with_headers(
                    HTTPStatus.SEE_OTHER,
                    "text/html; charset=utf-8",
                    b'<!DOCTYPE html><html><body>Logged out. <a href="/login">Login</a></body></html>',
                    headers={"Location": "/login", "Set-Cookie": clear_cookie},
                )
            return

        # 3. Session creation (/auth/session)
        if self.path == "/auth/session":
            MAX_SESSION_BYTES = 64 * 1024  # 64 KB limit
            cl_header = self.headers.get("Content-Length")
            if cl_header:
                try:
                    content_length = int(cl_header)
                except ValueError:
                    self._send_response_with_headers(
                        HTTPStatus.BAD_REQUEST,
                        "application/json; charset=utf-8",
                        b'{"error":"Invalid Content-Length"}',
                    )
                    return
                if content_length < 0:
                    self._send_response_with_headers(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Invalid Content-Length"}')
                    return
                if content_length > MAX_SESSION_BYTES:
                    self._send_response_with_headers(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        "application/json; charset=utf-8",
                        b'{"error":"Payload too large (max 64 KB)"}',
                    )
                    return
            else:
                self._send_response_with_headers(HTTPStatus.LENGTH_REQUIRED, "application/json; charset=utf-8", b'{"error":"Content-Length required"}')
                return

            if content_length is not None:
                body_bytes = self.rfile.read(content_length)
            else:
                body_bytes = self.rfile.read(MAX_SESSION_BYTES + 1)

            if len(body_bytes) > MAX_SESSION_BYTES:
                self._send_response_with_headers(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "application/json; charset=utf-8",
                    b'{"error":"Payload too large (max 64 KB)"}',
                )
                return

            # Rate limit check (10 per minute per client IP)
            client_ip = self._get_client_ip()
            if self.session_rate_limiter:
                allowed, retry_after = self.session_rate_limiter.check_and_record(client_ip)
                if not allowed:
                    logger.warning(
                        "Rate limit exceeded for /auth/session from IP %s (retry after %.1fs)",
                        client_ip,
                        retry_after,
                    )
                    retry_secs = max(1, int(math.ceil(retry_after)))
                    self._send_response_with_headers(
                        HTTPStatus.TOO_MANY_REQUESTS,
                        "application/json; charset=utf-8",
                        b'{"error":"Too many authentication attempts. Please try again later."}',
                        headers={"Retry-After": str(retry_secs)},
                    )
                    return

            # Parse JSON body
            try:
                data = json.loads(body_bytes.decode("utf-8"))
                id_token = data.get("idToken")
                if not id_token or not isinstance(id_token, str):
                    raise ValueError("Missing or invalid idToken")
            except Exception:
                self._send_response_with_headers(
                    HTTPStatus.BAD_REQUEST,
                    "application/json; charset=utf-8",
                    b'{"error":"Invalid request payload"}',
                )
                return

            # Verify Firebase ID token
            ok, err_msg, claims = auth.verify_firebase_id_token(
                id_token=id_token,
                project_id=self.project_id,
                admin_emails=self.admin_emails,
                jwk_manager=self.jwk_manager,
            )
            if not ok:
                # Log reason without the token
                logger.warning("Session authentication rejected for IP %s", client_ip)
                if claims and "not in authorized admin emails" in err_msg:
                    status_code = HTTPStatus.FORBIDDEN
                    resp_body = b'{"error":"Forbidden: Email not in admin allowlist"}'
                else:
                    status_code = HTTPStatus.UNAUTHORIZED
                    resp_body = b'{"error":"Unauthorized: Invalid token"}'

                self._send_response_with_headers(status_code, "application/json; charset=utf-8", resp_body)
                return

            # Success: create server session in SQLite
            email = claims.get("email", "").lower().strip()
            with db.get_connection(self.db_path) as conn:
                session_id = db.create_session(conn, email)

            cookie_header = (
                f"__Host-family_session={session_id}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=604800"
            )
            logger.info("Session established for '%s' from IP %s", email, client_ip)
            self._send_response_with_headers(
                HTTPStatus.OK,
                "application/json; charset=utf-8",
                b'{"status":"ok"}',
                headers={"Set-Cookie": cookie_header},
            )
            return

        # 4. Settings update (/settings)
        if self.path == "/settings":
            session = self._get_current_session()
            accept = self.headers.get("Accept", "")
            content_type = self.headers.get("Content-Type", "")
            is_json_req = "application/json" in accept or "application/json" in content_type

            if not session:
                if is_json_req:
                    self._send_response_with_headers(
                        HTTPStatus.UNAUTHORIZED,
                        "application/json; charset=utf-8",
                        b'{"error":"Unauthorized"}',
                    )
                else:
                    self._send_response_with_headers(
                        HTTPStatus.FOUND,
                        "text/html; charset=utf-8",
                        b'<!DOCTYPE html><html><body>Redirecting to <a href="/login">/login</a>...</body></html>',
                        headers={"Location": "/login"},
                    )
                return

            user_email = session.get("email", "").lower().strip()
            if self.admin_emails and user_email not in self.admin_emails:
                if is_json_req:
                    self._send_response_with_headers(
                        HTTPStatus.FORBIDDEN,
                        "application/json; charset=utf-8",
                        b'{"error":"Forbidden: Admin access required"}',
                    )
                else:
                    self._send_response_with_headers(
                        HTTPStatus.FORBIDDEN,
                        "text/html; charset=utf-8",
                        b'<!DOCTYPE html><html><body><h1>403 Forbidden: Admin access required</h1></body></html>',
                    )
                return

            MAX_SETTINGS_BYTES = 64 * 1024
            cl_header = self.headers.get("Content-Length")
            try:
                cl = int(cl_header) if cl_header else 0
            except ValueError:
                cl = 0
            if cl > MAX_SETTINGS_BYTES:
                self._send_response_with_headers(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "application/json; charset=utf-8" if is_json_req else "text/plain; charset=utf-8",
                    b'{"error":"Payload too large"}' if is_json_req else b"Payload too large",
                )
                return

            body_bytes = self.rfile.read(cl) if cl > 0 else b""
            body_str = body_bytes.decode("utf-8", errors="replace")

            day_raw = ""
            start_raw = ""
            tz_raw = ""

            if "application/json" in content_type:
                try:
                    payload = json.loads(body_str) if body_str else {}
                    day_raw = str(payload.get("cycle_anchor_day", "")).strip()
                    start_raw = str(payload.get("tracking_start", "") or "").strip()
                    tz_raw = str(payload.get("timezone", "") or "").strip()
                except Exception:
                    self._send_response_with_headers(
                        HTTPStatus.BAD_REQUEST,
                        "application/json; charset=utf-8",
                        b'{"error":"Invalid JSON"}',
                    )
                    return
            else:
                qs = urllib.parse.parse_qs(body_str)
                day_raw = qs.get("cycle_anchor_day", [""])[0].strip()
                start_raw = qs.get("tracking_start", [""])[0].strip()
                tz_raw = qs.get("timezone", [""])[0].strip()

            form_data = {
                "cycle_anchor_day": day_raw,
                "tracking_start": start_raw,
                "timezone": tz_raw,
            }

            # Validation
            val_err = None
            day_val = None
            try:
                day_val = int(day_raw)
                if not (1 <= day_val <= 31):
                    val_err = "计费周期起始日必须在 1 至 31 之间"
            except (ValueError, TypeError):
                val_err = "计费周期起始日必须为 1 至 31 之间的整数"

            start_val = None
            if not val_err and start_raw:
                try:
                    parsed_dt = datetime.strptime(start_raw, "%Y-%m-%d")
                    if parsed_dt.strftime("%Y-%m-%d") != start_raw:
                        val_err = "统计起始日期格式无效，必须为 YYYY-MM-DD"
                    else:
                        start_val = start_raw
                except ValueError:
                    val_err = "统计起始日期格式无效，必须为 YYYY-MM-DD"

            tz_val = tz_raw or os.environ.get("FAMILY_TIMEZONE") or "America/Toronto"
            if not val_err:
                try:
                    ZoneInfo(tz_val)
                except Exception:
                    val_err = "时区名称无效，必须为有效的 IANA 时区（如 America/Toronto）"

            if val_err:
                if is_json_req:
                    self._send_response_with_headers(
                        HTTPStatus.BAD_REQUEST,
                        "application/json; charset=utf-8",
                        json.dumps({"error": val_err}, ensure_ascii=False).encode("utf-8"),
                    )
                else:
                    with db.get_connection(self.db_path) as conn:
                        current_settings = db.get_all_settings(conn)
                    html_content = render_settings_html(
                        current_settings,
                        user_email=user_email,
                        error=val_err,
                        form_data=form_data,
                    )
                    self._send_response_with_headers(
                        HTTPStatus.BAD_REQUEST,
                        "text/html; charset=utf-8",
                        html_content.encode("utf-8"),
                        is_authenticated=True,
                    )
                return

            # Save settings
            with db.get_connection(self.db_path) as conn:
                db.set_setting(conn, "cycle_anchor_day", str(day_val))
                db.set_setting(conn, "tracking_start", start_val)
                db.set_setting(conn, "timezone", tz_val)

            # Log changes without PII
            logger.info(
                "Settings updated: cycle_anchor_day=%d, tracking_start=%s, timezone=%s",
                day_val,
                start_val or "(none)",
                tz_val,
            )

            if is_json_req:
                resp_payload = {
                    "status": "ok",
                    "cycle_anchor_day": day_val,
                    "tracking_start": start_val,
                    "timezone": tz_val,
                }
                self._send_response_with_headers(
                    HTTPStatus.OK,
                    "application/json; charset=utf-8",
                    json.dumps(resp_payload, ensure_ascii=False).encode("utf-8"),
                )
            else:
                self._send_response_with_headers(
                    HTTPStatus.SEE_OTHER,
                    "text/html; charset=utf-8",
                    b'<!DOCTYPE html><html><body>Redirecting to /settings?saved=1...</body></html>',
                    headers={"Location": "/settings?saved=1"},
                    is_authenticated=True,
                )
            return

        # 5. Any other POST is 404
        self._send_response_with_headers(
            HTTPStatus.NOT_FOUND,
            "application/json; charset=utf-8",
            b'{"error":"Not Found"}',
        )


def make_dashboard_handler(
    db_path: str,
    firebase_config: Optional[dict] = None,
    project_id: Optional[str] = None,
    admin_emails: Optional[Set[str]] = None,
    public_origin: Optional[str] = None,
    session_rate_limiter: Optional[RateLimiter] = None,
    jwk_manager: Optional[auth.JWKManager] = None,
):
    """Factory to create a DashboardHandler bound to configuration and db_path."""
    if firebase_config is None:
        firebase_config = load_firebase_config()

    if project_id is None:
        project_id = os.environ.get("FIREBASE_PROJECT_ID") or (firebase_config.get("projectId") if firebase_config else "") or ""

    if admin_emails is None:
        raw_emails = os.environ.get("FAMILY_ADMIN_EMAILS", "")
        admin_emails = {e.strip().lower() for e in raw_emails.split(",") if e.strip()}

    if public_origin is None:
        public_origin = os.environ.get("FAMILY_PUBLIC_ORIGIN", "")

    if session_rate_limiter is None:
        session_rate_limiter = RateLimiter(window_seconds=60.0, max_requests=10)

    if jwk_manager is None:
        jwk_manager = auth.get_default_jwk_manager()

    auth_domain = (firebase_config.get("authDomain") or "") if firebase_config else ""
    if auth_domain:
        from .validation import validate_auth_domain
        if not validate_auth_domain(auth_domain):
            raise ValueError(f"Invalid authDomain in firebase_config: {auth_domain!r}")
        frame_src = f"https://{auth_domain}"
    else:
        frame_src = "'none'"

    csp_header = (
        "default-src 'self'; "
        "script-src 'self' https://apis.google.com https://www.gstatic.com; "
        "connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://www.googleapis.com; "
        f"frame-src {frame_src}; "
        "img-src 'self' data: https://lh3.googleusercontent.com; "
        "style-src 'self' 'unsafe-inline'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )

    class BoundDashboardHandler(DashboardHandler):
        pass

    BoundDashboardHandler.db_path = db_path
    BoundDashboardHandler.firebase_config = firebase_config
    BoundDashboardHandler.project_id = project_id
    BoundDashboardHandler.admin_emails = admin_emails
    BoundDashboardHandler.public_origin = public_origin
    BoundDashboardHandler.csp_header = csp_header
    BoundDashboardHandler.session_rate_limiter = session_rate_limiter
    BoundDashboardHandler.jwk_manager = jwk_manager
    return BoundDashboardHandler
