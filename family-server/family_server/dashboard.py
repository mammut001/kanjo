"""Public dashboard for Kanjo family usage behind Firebase Authentication."""

from datetime import datetime, timedelta, timezone
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import json
import logging
import math
import mimetypes
import os
from typing import Dict, List, Optional, Set, Tuple

from . import auth
from . import db
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


def load_firebase_config() -> dict:
    """Load Firebase web configuration from environment or local JSON file."""
    env_json = os.environ.get("FIREBASE_WEB_CONFIG_JSON")
    if env_json:
        try:
            return json.loads(env_json)
        except Exception as e:
            logger.warning("Failed to parse FIREBASE_WEB_CONFIG_JSON: %s", e)

    cfg_file = os.path.join(os.path.dirname(__file__), "firebase_config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load firebase_config.json: %s", e)
    return {}


def parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """Parse ISO timestamp with Python 3.9 compatibility."""
    if not ts:
        return None
    try:
        clean = ts.strip()
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        return datetime.fromisoformat(clean)
    except Exception:
        return None


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


def format_dt(dt: Optional[datetime]) -> str:
    """Format datetime for display in YYYY-MM-DD HH:MM format."""
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")


def render_svg_chart(dates: List[str], member_data: List[dict], max_tokens: int) -> str:
    """Render a handwritten, responsive SVG stacked bar chart."""
    width = 900
    height = 250
    margin_left = 65
    margin_right = 20
    margin_top = 25
    margin_bottom = 35

    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    n_days = max(1, len(dates))
    slot_width = plot_width / n_days
    bar_width = max(4.0, slot_width * 0.65)
    bar_offset = (slot_width - bar_width) / 2.0

    # Upper bound rounded nicely
    y_max = max_tokens if max_tokens > 0 else 1000
    magnitude = 10 ** max(0, len(str(int(y_max))) - 1)
    y_max = int(((y_max + magnitude - 1) // magnitude) * magnitude)

    lines = []
    lines.append(
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        'class="chart-svg" style="width: 100%; height: auto; display: block;" role="img" '
        'aria-label="近 30 天每日用量趋势图">'
    )

    # Grid lines and Y axis labels (0%, 50%, 100%)
    for frac in (0.0, 0.5, 1.0):
        y_pos = margin_top + plot_height * (1.0 - frac)
        token_val = int(y_max * frac)
        label_text = format_tokens(token_val)
        lines.append(
            f'<line x1="{margin_left}" y1="{y_pos:.1f}" x2="{width - margin_right}" y2="{y_pos:.1f}" '
            'class="grid-line" stroke="var(--bar-grid)" stroke-width="1" stroke-dasharray="3,3" />'
        )
        lines.append(
            f'<text x="{margin_left - 8}" y="{y_pos + 4:.1f}" class="axis-text" '
            f'text-anchor="end" fill="var(--text-muted)" font-size="11">{html.escape(label_text)}</text>'
        )

    # Bars
    for day_idx, d_str in enumerate(dates):
        x = margin_left + day_idx * slot_width + bar_offset
        y_cursor = margin_top + plot_height

        for m in member_data:
            tok = m["daily_tokens"].get(d_str, 0)
            if tok <= 0:
                continue
            bar_h = (tok / y_max) * plot_height
            y = y_cursor - bar_h
            escaped_mname = html.escape(m["name"])
            lines.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_h:.1f}" '
                f'fill="{m["color"]}" rx="2">'
                f'<title>{escaped_mname}: {tok:,} tokens ({d_str})</title>'
                '</rect>'
            )
            y_cursor = y

        # X-axis label every 3 days or for first/last
        if day_idx % 3 == 0 or day_idx == n_days - 1:
            label = d_str[5:]  # MM-DD
            lines.append(
                f'<text x="{x + bar_width / 2:.1f}" y="{height - 12}" class="axis-text" '
                f'text-anchor="middle" fill="var(--text-muted)" font-size="10">{html.escape(label)}</text>'
            )

    lines.append('</svg>')
    return "\n".join(lines)


def generate_dashboard_html(
    db_path: str,
    now: Optional[datetime] = None,
    user_email: Optional[str] = None,
) -> str:
    """Render the full single-page dashboard HTML."""
    if now is None:
        now = datetime.now(timezone.utc)

    with db.get_connection(db_path) as conn:
        records = db.get_all_latest_reports(conn)

    today_str = now.strftime("%Y-%m-%d")
    current_month_str = now.strftime("%Y-%m")
    dates_30 = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]

    # Process member data
    members_processed = []
    quota_pool_entries = []
    pool_weekly_users = []

    for idx, rec in enumerate(records):
        m = rec["member"]
        rep = rec["report"]
        color = PALETTE[idx % len(PALETTE)]

        member_info = {
            "id": m["id"],
            "name": m["name"],
            "color": color,
            "has_report": False,
            "label": None,
            "received_at": None,
            "is_stale": True,
            "today_tokens": 0,
            "today_cost": 0.0,
            "week7_tokens": 0,
            "week7_cost": 0.0,
            "month_tokens": 0,
            "month_cost": 0.0,
            "top_models": [],
            "daily_tokens": {},
            "antigravity_quota": None,
            "weekly_antigravity_tokens": 0,
        }

        if rep:
            member_info["has_report"] = True
            rec_dt = parse_iso(rep["received_at"])
            member_info["received_at"] = rec_dt
            if rec_dt:
                diff_sec = (now - rec_dt).total_seconds()
                member_info["is_stale"] = diff_sec > 86400.0

            try:
                payload = json.loads(rep["payload_json"])
            except Exception:
                payload = {}

            member_info["label"] = payload.get("member_label")

            # Quota windows
            qw = payload.get("quota_windows", {})
            plans = payload.get("plans", {})
            ag_qw = qw.get("antigravity")
            if ag_qw:
                pct = ag_qw.get("weekly_used_percent", 0.0)
                resets_at = ag_qw.get("weekly_resets_at")
                plan_name = plans.get("antigravity", "Google AI Ultra")
                member_info["antigravity_quota"] = {
                    "weekly_used_percent": pct,
                    "weekly_resets_at": resets_at,
                    "plan": plan_name,
                }
                quota_pool_entries.append({
                    "member_name": m["name"],
                    "member_label": member_info["label"],
                    "color": color,
                    "quota": member_info["antigravity_quota"],
                })

            # Summary metrics
            summary = payload.get("summary", {})

            # 1. Daily breakdown for 30-day chart and today
            days = summary.get("days", [])
            for d in days:
                p_str = d.get("period")
                tok_cnt = d.get("tokens", {}).get("total", 0)
                cost_val = d.get("cost_usd", 0.0)
                if p_str:
                    member_info["daily_tokens"][p_str] = tok_cnt
                if p_str == today_str:
                    member_info["today_tokens"] = tok_cnt
                    member_info["today_cost"] = cost_val

            # 2. Last 7 days metrics
            week_days_keys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
            day_map = {d.get("period"): d for d in days if isinstance(d, dict)}
            for wd in week_days_keys:
                if wd in day_map:
                    member_info["week7_tokens"] += day_map[wd].get("tokens", {}).get("total", 0)
                    member_info["week7_cost"] += day_map[wd].get("cost_usd", 0.0)

            # 3. Current month metrics
            months = summary.get("months", [])
            for mo in months:
                if mo.get("period") == current_month_str:
                    member_info["month_tokens"] = mo.get("tokens", {}).get("total", 0)
                    member_info["month_cost"] = mo.get("cost_usd", 0.0)
                    break

            # 4. Top models from all_time
            all_time = summary.get("all_time", {})
            top_m = all_time.get("top_models", [])
            member_info["top_models"] = top_m[:5]

            # 5. Antigravity weekly tokens
            weeks = summary.get("weeks", [])
            if weeks:
                curr_week = weeks[0]
                week_models = curr_week.get("models", {})
                ag_tokens = 0
                for mod_name, mod_info in week_models.items():
                    low_name = mod_name.lower()
                    if "gemini" in low_name or "antigravity" in low_name or "argon" in low_name:
                        ag_tokens += mod_info.get("tokens_total", 0)
                member_info["weekly_antigravity_tokens"] = ag_tokens

        members_processed.append(member_info)

    # Compute quota pool share
    total_weekly_pool_tokens = sum(m["weekly_antigravity_tokens"] for m in members_processed)
    for m in members_processed:
        t = m["weekly_antigravity_tokens"]
        pct = (t / total_weekly_pool_tokens * 100.0) if total_weekly_pool_tokens > 0 else 0.0
        pool_weekly_users.append({
            "name": m["name"],
            "label": m["label"],
            "color": m["color"],
            "tokens": t,
            "pct": pct,
        })
    pool_weekly_users.sort(key=lambda x: x["tokens"], reverse=True)

    # Max tokens on any day for chart scaling
    max_day_tokens = 0
    for d_str in dates_30:
        day_sum = sum(m["daily_tokens"].get(d_str, 0) for m in members_processed)
        if day_sum > max_day_tokens:
            max_day_tokens = day_sum

    svg_chart_html = render_svg_chart(dates_30, members_processed, max_day_tokens)

    # HTML building
    doc = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "  <title>家庭用量面板 · Kanjo</title>",
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
          --bar-grid: #e2e8f0;
          --badge-bg: #f1f5f9;
          --green: #10b981;
          --amber: #f59e0b;
          --red: #ef4444;
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
            --bar-grid: #334155;
            --badge-bg: #334155;
            --shadow: 0 1px 3px 0 rgb(0 0 0 / 0.3);
          }
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
          background: var(--bg);
          color: var(--text-primary);
          line-height: 1.5;
          padding: 1.5rem 1rem 3rem 1rem;
        }
        .container { max-width: 1100px; margin: 0 auto; }
        header { margin-bottom: 2rem; }
        .header-title-row { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem; }
        h1 { font-size: 1.75rem; font-weight: 700; margin-bottom: 0.25rem; }
        .meta-time { font-size: 0.82rem; color: var(--text-muted); }
        .cost-notice { font-size: 0.82rem; color: var(--text-muted); margin-top: 0.25rem; }
        .header-right { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
        .user-email { font-size: 0.82rem; color: var(--text-secondary); background: var(--badge-bg); padding: 0.2rem 0.5rem; border-radius: 4px; }
        .logout-btn { background: transparent; border: 1px solid var(--card-border); color: var(--text-secondary); padding: 0.25rem 0.6rem; border-radius: 6px; font-size: 0.8rem; cursor: pointer; transition: all 0.15s ease; }
        .logout-btn:hover { background: var(--badge-bg); color: var(--text-primary); }

        .card {
          background: var(--card-bg);
          border: 1px solid var(--card-border);
          border-radius: 12px;
          padding: 1.5rem;
          margin-bottom: 1.5rem;
          box-shadow: var(--shadow);
        }
        .section-title { font-size: 1.15rem; font-weight: 600; margin-bottom: 1rem; }

        /* Quota Grid */
        .quota-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }
        .quota-item {
          background: var(--bg);
          border: 1px solid var(--card-border);
          border-left-width: 4px;
          border-radius: 8px;
          padding: 1rem;
        }
        .quota-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.5rem; }
        .quota-user { font-weight: 600; font-size: 0.95rem; }
        .quota-plan { font-size: 0.75rem; color: var(--text-muted); background: var(--badge-bg); padding: 0.15rem 0.4rem; border-radius: 4px; }
        .progress-bar { width: 100%; height: 8px; background: var(--badge-bg); border-radius: 4px; overflow: hidden; margin-bottom: 0.5rem; }
        .progress-fill { height: 100%; border-radius: 4px; transition: width 0.3s ease; }
        .quota-footer { display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--text-secondary); }

        /* Members Grid */
        .members-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.25rem; }
        .member-card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem; }
        .member-name-row { display: flex; align-items: center; gap: 0.5rem; }
        .color-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
        .member-title { font-size: 1.1rem; font-weight: 600; }
        .member-label { font-size: 0.8rem; color: var(--text-muted); margin-top: 0.1rem; }
        .badge { font-size: 0.75rem; padding: 0.2rem 0.5rem; border-radius: 4px; font-weight: 500; }
        .badge-active { background: #dcfce7; color: #15803d; }
        .badge-stale { background: #fee2e2; color: #b91c1c; }
        @media (prefers-color-scheme: dark) {
          .badge-active { background: #14532d; color: #86efac; }
          .badge-stale { background: #7f1d1d; color: #fca5a5; }
        }

        .metrics-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; margin-bottom: 1.25rem; background: var(--bg); padding: 0.75rem; border-radius: 8px; }
        .metric-cell { text-align: center; }
        .metric-label { font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.2rem; }
        .metric-tokens { font-size: 1rem; font-weight: 600; }
        .metric-cost { font-size: 0.75rem; color: var(--text-secondary); }

        .models-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
        .models-table th, .models-table td { padding: 0.35rem 0.25rem; text-align: left; }
        .models-table th { color: var(--text-muted); font-weight: 500; border-bottom: 1px solid var(--card-border); }
        .models-table td { border-bottom: 1px dashed var(--card-border); }
        .models-table tr:last-child td { border-bottom: none; }
        .text-right { text-align: right !important; }

        /* Pool Share Bar */
        .share-list { display: flex; flex-direction: column; gap: 0.75rem; }
        .share-row { display: flex; flex-direction: column; gap: 0.25rem; }
        .share-info { display: flex; justify-content: space-between; font-size: 0.88rem; }
        .share-bar-bg { width: 100%; height: 8px; background: var(--badge-bg); border-radius: 4px; overflow: hidden; }
        .share-bar-fill { height: 100%; border-radius: 4px; }

        /* Legend */
        .chart-legend { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1rem; font-size: 0.82rem; }
        .legend-item { display: flex; align-items: center; gap: 0.4rem; }

        .empty-state { text-align: center; color: var(--text-muted); padding: 2rem 1rem; font-size: 0.9rem; }
        </style>
        """,
        "</head>",
        "<body>",
        '  <div class="container">',
        "    <header>",
        '      <div class="header-title-row">',
        "        <div>",
        "          <h1>家庭用量汇总</h1>",
        f'          <div class="cost-notice">注：{html.escape(COST_NOTE)}</div>',
        "        </div>",
        '        <div class="header-right">',
        f'          <span class="meta-time">刷新时间：{html.escape(format_dt(now))} UTC</span>',
    ]

    if user_email:
        doc.append(f'          <span class="user-email">{html.escape(user_email)}</span>')
        doc.append('          <form method="POST" action="/auth/logout" style="margin: 0; display: inline;">')
        doc.append('            <button type="submit" class="logout-btn">退出</button>')
        doc.append('          </form>')

    doc.extend([
        "        </div>",
        "      </div>",
        "    </header>",
    ])

    # 1. Quota Pool Card
    doc.append('    <section class="card">')
    doc.append('      <h2 class="section-title">Google AI Ultra 额度池</h2>')
    if not quota_pool_entries:
        doc.append('      <div class="empty-state">暂无成员上报 Google AI Ultra 额度数据</div>')
    else:
        doc.append('      <div class="quota-grid">')
        for q in quota_pool_entries:
            name = html.escape(q["member_name"])
            lbl = f" ({html.escape(q['member_label'])})" if q["member_label"] else ""
            plan = html.escape(q["quota"]["plan"])
            pct = q["quota"]["weekly_used_percent"]
            reset_dt = parse_iso(q["quota"]["weekly_resets_at"])
            reset_str = format_dt(reset_dt) if reset_dt else "—"

            if pct >= 95.0:
                bar_color = "var(--red)"
            elif pct >= 80.0:
                bar_color = "var(--amber)"
            else:
                bar_color = "var(--green)"

            doc.append('        <div class="quota-item" style="border-left-color: ' + q["color"] + ';">')
            doc.append('          <div class="quota-header">')
            doc.append(f'            <span class="quota-user">{name}{lbl}</span>')
            doc.append(f'            <span class="quota-plan">{plan}</span>')
            doc.append('          </div>')
            doc.append('          <div class="progress-bar">')
            doc.append(f'            <div class="progress-fill" style="width: {min(100.0, pct):.1f}%; background: {bar_color};"></div>')
            doc.append('          </div>')
            doc.append('          <div class="quota-footer">')
            doc.append(f'            <span>周额度已用：<strong>{pct:.1f}%</strong></span>')
            doc.append(f'            <span>重置时间：{html.escape(reset_str)}</span>')
            doc.append('          </div>')
            doc.append('        </div>')
        doc.append('      </div>')
    doc.append('    </section>')

    # 2. Who Used the Quota Pool This Week
    doc.append('    <section class="card">')
    doc.append('      <h2 class="section-title">本周谁用掉了额度池 (Google / Antigravity 模型)</h2>')
    if total_weekly_pool_tokens == 0:
        doc.append('      <div class="empty-state">本周暂无 Google 模型用量记录</div>')
    else:
        doc.append('      <div class="share-list">')
        for u in pool_weekly_users:
            if u["tokens"] <= 0:
                continue
            name = html.escape(u["name"])
            lbl = f" ({html.escape(u['label'])})" if u["label"] else ""
            tok_fmt = format_tokens(u["tokens"])
            doc.append('        <div class="share-row">')
            doc.append('          <div class="share-info">')
            doc.append(f'            <span><strong>{name}</strong>{lbl}</span>')
            doc.append(f'            <span>{tok_fmt} tokens ({u["pct"]:.1f}%)</span>')
            doc.append('          </div>')
            doc.append('          <div class="share-bar-bg">')
            doc.append(f'            <div class="share-bar-fill" style="width: {min(100.0, u["pct"]):.1f}%; background: {u["color"]};"></div>')
            doc.append('          </div>')
            doc.append('        </div>')
        doc.append('      </div>')
    doc.append('    </section>')

    # 3. 30-Day SVG Chart
    doc.append('    <section class="card">')
    doc.append('      <h2 class="section-title">近 30 天每日用量趋势 (按人分色)</h2>')
    doc.append('      <div class="chart-legend">')
    for m in members_processed:
        escaped_name = html.escape(m["name"])
        doc.append(
            f'        <div class="legend-item">'
            f'          <span class="color-dot" style="background: {m["color"]};"></span>'
            f'          <span>{escaped_name}</span>'
            '        </div>'
        )
    doc.append('      </div>')
    doc.append(svg_chart_html)
    doc.append('    </section>')

    # 4. Member Cards
    doc.append('    <section>')
    doc.append('      <h2 class="section-title">成员概览</h2>')
    if not members_processed:
        doc.append('      <div class="card"><div class="empty-state">尚未添加任何成员</div></div>')
    else:
        doc.append('      <div class="members-grid">')
        for m in members_processed:
            name = html.escape(m["name"])
            lbl = f" · {html.escape(m['label'])}" if m["label"] else ""
            rec_str = format_dt(m["received_at"]) if m["received_at"] else "从未上报"

            if not m["has_report"]:
                badge_html = '<span class="badge badge-stale">未上报</span>'
            elif m["is_stale"]:
                badge_html = '<span class="badge badge-stale">未更新</span>'
            else:
                badge_html = '<span class="badge badge-active">正常</span>'

            doc.append('        <div class="card" style="margin-bottom: 0;">')
            doc.append('          <div class="member-card-header">')
            doc.append('            <div>')
            doc.append('              <div class="member-name-row">')
            doc.append(f'                <span class="color-dot" style="background: {m["color"]};"></span>')
            doc.append(f'                <span class="member-title">{name}</span>')
            doc.append('              </div>')
            doc.append(f'              <div class="member-label">上次上报：{html.escape(rec_str)}{lbl}</div>')
            doc.append('            </div>')
            doc.append(f'            {badge_html}')
            doc.append('          </div>')

            # Metrics
            doc.append('          <div class="metrics-grid">')
            doc.append('            <div class="metric-cell">')
            doc.append('              <div class="metric-label">今天</div>')
            doc.append(f'              <div class="metric-tokens">{format_tokens(m["today_tokens"])}</div>')
            doc.append(f'              <div class="metric-cost">{format_cost(m["today_cost"])}</div>')
            doc.append('            </div>')
            doc.append('            <div class="metric-cell">')
            doc.append('              <div class="metric-label">近 7 天</div>')
            doc.append(f'              <div class="metric-tokens">{format_tokens(m["week7_tokens"])}</div>')
            doc.append(f'              <div class="metric-cost">{format_cost(m["week7_cost"])}</div>')
            doc.append('            </div>')
            doc.append('            <div class="metric-cell">')
            doc.append('              <div class="metric-label">本月</div>')
            doc.append(f'              <div class="metric-tokens">{format_tokens(m["month_tokens"])}</div>')
            doc.append(f'              <div class="metric-cost">{format_cost(m["month_cost"])}</div>')
            doc.append('            </div>')
            doc.append('          </div>')

            # Top Models Table
            if m["top_models"]:
                doc.append('          <table class="models-table">')
                doc.append('            <thead>')
                doc.append('              <tr><th>模型 (前 5)</th><th class="text-right">Token</th><th class="text-right">折算金额</th></tr>')
                doc.append('            </thead>')
                doc.append('            <tbody>')
                for tm in m["top_models"]:
                    mod_name = html.escape(str(tm.get("model", "—")))
                    t_tot = tm.get("tokens_total", 0)
                    c_tot = tm.get("cost_usd", 0.0)
                    doc.append('              <tr>')
                    doc.append(f'                <td>{mod_name}</td>')
                    doc.append(f'                <td class="text-right">{format_tokens(t_tot)}</td>')
                    doc.append(f'                <td class="text-right">{format_cost(c_tot)}</td>')
                    doc.append('              </tr>')
                doc.append('            </tbody>')
                doc.append('          </table>')
            else:
                doc.append('          <div class="empty-state" style="padding: 1rem 0 0.5rem 0;">暂无模型用量明细</div>')

            doc.append('        </div>')
        doc.append('      </div>')
    doc.append('    </section>')

    doc.append('  </div>')
    doc.append('</body>')
    doc.append('</html>')

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
    project_id: str = "kanjo-family-usage"
    admin_emails: Set[str] = set()
    public_origin: str = "https://usage.paytonpei.top"
    session_rate_limiter: Optional[RateLimiter] = None
    jwk_manager: Optional[auth.JWKManager] = None

    def log_message(self, format: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

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
            "default-src 'self'; "
            "script-src 'self' https://apis.google.com https://www.gstatic.com; "
            "connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://www.googleapis.com; "
            "frame-src https://kanjo-family-usage.firebaseapp.com; "
            "img-src 'self' data: https://lh3.googleusercontent.com; "
            "style-src 'self' 'unsafe-inline'; "
            "base-uri 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none'",
        )
        self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
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
            return db.get_session(conn, session_id)

    def _check_csrf(self) -> bool:
        """Verify CSRF protections on POST requests.
        
        Requires either:
        - Origin matching FAMILY_PUBLIC_ORIGIN
        - Sec-Fetch-Site: same-origin (when Origin is omitted by browser/client)
        """
        origin = self.headers.get("Origin")
        if origin:
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
            html_content = generate_dashboard_html(self.db_path, user_email=session["email"])
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
            logger.warning(
                "CSRF check failed on %s (Origin: %s, Sec-Fetch-Site: %s)",
                self.path,
                self.headers.get("Origin"),
                self.headers.get("Sec-Fetch-Site"),
            )
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
                if content_length > MAX_SESSION_BYTES:
                    self._send_response_with_headers(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        "application/json; charset=utf-8",
                        b'{"error":"Payload too large (max 64 KB)"}',
                    )
                    return
            else:
                content_length = None

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
                logger.warning("Session authentication rejected for IP %s: %s", client_ip, err_msg)
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

        # 4. Any other POST is 404
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
        project_id = os.environ.get("FIREBASE_PROJECT_ID") or firebase_config.get("projectId", "kanjo-family-usage")

    if admin_emails is None:
        raw_emails = os.environ.get("FAMILY_ADMIN_EMAILS", "")
        admin_emails = {e.strip().lower() for e in raw_emails.split(",") if e.strip()}

    if public_origin is None:
        public_origin = os.environ.get("FAMILY_PUBLIC_ORIGIN", "https://usage.paytonpei.top")

    if session_rate_limiter is None:
        session_rate_limiter = RateLimiter(window_seconds=60.0, max_requests=10)

    if jwk_manager is None:
        jwk_manager = auth.get_default_jwk_manager()

    class BoundDashboardHandler(DashboardHandler):
        pass

    BoundDashboardHandler.db_path = db_path
    BoundDashboardHandler.firebase_config = firebase_config
    BoundDashboardHandler.project_id = project_id
    BoundDashboardHandler.admin_emails = admin_emails
    BoundDashboardHandler.public_origin = public_origin
    BoundDashboardHandler.session_rate_limiter = session_rate_limiter
    BoundDashboardHandler.jwk_manager = jwk_manager
    return BoundDashboardHandler
