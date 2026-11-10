"""Tailscale dashboard for Kanjo family usage."""

from datetime import datetime, timedelta, timezone
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import json
import logging
from typing import Dict, List, Optional, Tuple

from . import db

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


def generate_dashboard_html(db_path: str, now: Optional[datetime] = None) -> str:
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
                plan_name = plans.get("antigravity") or "Google AI Ultra"
                member_info["antigravity_quota"] = {
                    "plan": plan_name,
                    "weekly_used_percent": float(ag_qw.get("weekly_used_percent", 0.0)),
                    "weekly_resets_at": ag_qw.get("weekly_resets_at"),
                    "weekly_window_hours": ag_qw.get("weekly_window_hours", 168),
                }
                quota_pool_entries.append({
                    "member_name": m["name"],
                    "member_label": member_info["label"],
                    "quota": member_info["antigravity_quota"],
                    "color": color,
                })

            # Summary processing
            summary = payload.get("summary", {})
            days_list = summary.get("days", [])
            months_list = summary.get("months", [])
            weeks_list = summary.get("weeks", [])

            # Daily mapping
            for d in days_list:
                d_period = d.get("period")
                if d_period:
                    tok = d.get("tokens", {}).get("total", 0)
                    member_info["daily_tokens"][d_period] = tok
                    if d_period == today_str:
                        member_info["today_tokens"] = tok
                        member_info["today_cost"] = float(d.get("cost_usd", 0.0))

            # Recent 7 days
            recent_7_dates = set(dates_30[-7:])
            for d in days_list:
                if d.get("period") in recent_7_dates:
                    member_info["week7_tokens"] += d.get("tokens", {}).get("total", 0)
                    member_info["week7_cost"] += float(d.get("cost_usd", 0.0))

            # Current month
            found_month = False
            for mo in months_list:
                if mo.get("period") == current_month_str:
                    member_info["month_tokens"] = mo.get("tokens", {}).get("total", 0)
                    member_info["month_cost"] = float(mo.get("cost_usd", 0.0))
                    found_month = True
                    break
            if not found_month and months_list:
                latest_mo = months_list[-1]
                member_info["month_tokens"] = latest_mo.get("tokens", {}).get("total", 0)
                member_info["month_cost"] = float(latest_mo.get("cost_usd", 0.0))

            # Top 5 models
            all_time = summary.get("all_time", {})
            member_info["top_models"] = all_time.get("top_models", [])[:5]

            # Weekly Antigravity / Google usage
            if weeks_list:
                curr_week = weeks_list[-1]
                ag_tok = 0
                for a in curr_week.get("by_agent", []):
                    if a.get("agent") == "antigravity":
                        ag_tok = max(ag_tok, a.get("tokens_total", 0))
                for p in curr_week.get("by_provider", []):
                    if p.get("provider") == "google":
                        ag_tok = max(ag_tok, p.get("tokens", {}).get("total", 0))
                member_info["weekly_antigravity_tokens"] = ag_tok

        members_processed.append(member_info)

        pool_weekly_users.append({
            "name": m["name"],
            "label": member_info["label"],
            "color": color,
            "tokens": member_info["weekly_antigravity_tokens"],
        })

    # Calculate weekly pool share
    total_weekly_pool_tokens = sum(u["tokens"] for u in pool_weekly_users)
    pool_weekly_users.sort(key=lambda u: u["tokens"], reverse=True)
    for u in pool_weekly_users:
        if total_weekly_pool_tokens > 0:
            u["share_percent"] = (u["tokens"] / total_weekly_pool_tokens) * 100.0
        else:
            u["share_percent"] = 0.0

    # Max tokens for chart
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
        .container { max-width: 1080px; margin: 0 auto; }
        header { margin-bottom: 2rem; }
        .header-title-row { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; }
        h1 { font-size: 1.75rem; font-weight: 700; }
        .meta-time { font-size: 0.85rem; color: var(--text-muted); }
        .cost-notice { font-size: 0.82rem; color: var(--text-muted); margin-top: 0.25rem; }

        .section-title { font-size: 1.15rem; font-weight: 600; margin-bottom: 0.85rem; display: flex; align-items: center; gap: 0.5rem; }
        .card {
          background: var(--card-bg);
          border: 1px solid var(--card-border);
          border-radius: 0.75rem;
          padding: 1.25rem;
          box-shadow: var(--shadow);
          margin-bottom: 1.5rem;
        }

        /* Quota Pool */
        .quota-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }
        .quota-item {
          background: var(--badge-bg);
          border-radius: 0.5rem;
          padding: 1rem;
          border-left: 4px solid var(--accent);
        }
        .quota-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
        .quota-user { font-weight: 600; font-size: 0.95rem; }
        .quota-plan { font-size: 0.78rem; color: var(--text-muted); }
        .progress-bar {
          width: 100%;
          height: 10px;
          background: var(--card-border);
          border-radius: 5px;
          overflow: hidden;
          margin-bottom: 0.5rem;
        }
        .progress-fill { height: 100%; border-radius: 5px; transition: width 0.3s ease; }
        .quota-footer { display: flex; justify-content: space-between; font-size: 0.82rem; color: var(--text-secondary); }

        /* Members cards */
        .members-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.25rem; }
        .member-card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem; }
        .member-name-row { display: flex; align-items: center; gap: 0.5rem; }
        .color-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
        .member-title { font-size: 1.1rem; font-weight: 600; }
        .member-label { font-size: 0.8rem; color: var(--text-muted); }
        .badge {
          display: inline-block;
          font-size: 0.75rem;
          padding: 0.15rem 0.5rem;
          border-radius: 0.375rem;
          font-weight: 500;
        }
        .badge-stale { background: #fef3c7; color: #92400e; }
        .badge-active { background: #dcfce7; color: #166534; }
        @media (prefers-color-scheme: dark) {
          .badge-stale { background: #78350f; color: #fef3c7; }
          .badge-active { background: #14532d; color: #dcfce7; }
        }

        .metrics-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; margin-bottom: 1rem; }
        .metric-cell { background: var(--badge-bg); padding: 0.6rem; border-radius: 0.5rem; text-align: center; }
        .metric-label { font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.2rem; }
        .metric-tokens { font-size: 0.95rem; font-weight: 600; }
        .metric-cost { font-size: 0.78rem; color: var(--text-secondary); }

        .models-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-top: 0.5rem; }
        .models-table th { text-align: left; padding: 0.3rem 0.4rem; color: var(--text-muted); font-weight: 500; border-bottom: 1px solid var(--card-border); }
        .models-table td { padding: 0.35rem 0.4rem; border-bottom: 1px solid var(--card-border); }
        .models-table tr:last-child td { border-bottom: none; }
        .text-right { text-align: right; }

        /* Pool share list */
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
        "        <h1>家庭用量汇总</h1>",
        f'        <span class="meta-time">刷新时间：{html.escape(format_dt(now))} UTC</span>',
        "      </div>",
        f'      <div class="cost-notice">注：{html.escape(COST_NOTE)}</div>',
        "    </header>",
    ]

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

            # Color by threshold
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
            doc.append(f'            <span>{tok_fmt} tokens ({u["share_percent"]:.1f}%)</span>')
            doc.append('          </div>')
            doc.append('          <div class="share-bar-bg">')
            doc.append(f'            <div class="share-bar-fill" style="width: {u["share_percent"]:.1f}%; background: {u["color"]};"></div>')
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


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler for the private tailnet dashboard listener (port 8787)."""

    server_version = "KanjoFamilyDashboard/0.1"

    db_path: str = ""

    def log_message(self, format: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            payload = b'{"status":"ok"}'
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path == "/" or self.path.startswith("/?"):
            html_content = generate_dashboard_html(self.db_path)
            payload = html_content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        # 404 for anything else
        not_found = b'<!DOCTYPE html><html><body><h1>404 Not Found</h1></body></html>'
        self.send_response(HTTPStatus.NOT_FOUND)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(not_found)))
        self.end_headers()
        self.wfile.write(not_found)


def make_dashboard_handler(db_path: str):
    """Factory to create a DashboardHandler bound to db_path."""
    class BoundDashboardHandler(DashboardHandler):
        pass

    BoundDashboardHandler.db_path = db_path
    return BoundDashboardHandler
