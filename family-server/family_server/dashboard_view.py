"""HTML for the family dashboard page (v2): range tabs, overview, pool, trend, ranking, analysis.

The range-dependent sections are rendered here for the requested range and again in the
browser by ``static/dashboard.js`` from the same range dicts (embedded as JSON), so the
two must produce the same markup. Every client-supplied string goes through
``html.escape`` here and ``textContent`` in the script.
"""

from datetime import datetime, timezone
import functools
import hashlib
import html
import json
import math
import os
from typing import List, Optional

from . import ranges
from .dashboard import COST_NOTE, format_cost, format_dt, format_os, format_tokens, parse_iso

STATUS_TEXT = {"ok": "正常", "stale": "超过 2 小时未上报", "never": "从未上报"}
STATUS_CLASS = {"ok": "badge badge-active", "stale": "badge badge-stale", "never": "badge badge-stale badge-never"}
TREND_MODES = (("person", "按人"), ("model", "按模型"), ("agent", "按代理"))

CSS = """
        :root {
          --bg: #f4f6fa;
          --card-bg: #ffffff;
          --card-border: #e2e8f0;
          --panel: #f8fafc;
          --text-primary: #0f172a;
          --text-secondary: #475569;
          --text-muted: #64748b;
          --accent: #2563eb;
          --accent-soft: #dbeafe;
          --bar-grid: #e2e8f0;
          --badge-bg: #f1f5f9;
          --green: #16a34a;
          --amber: #d97706;
          --red: #dc2626;
          --heat-0: #eef2f7;
          --heat-1: #bfdbfe;
          --heat-2: #60a5fa;
          --heat-3: #2563eb;
          --heat-4: #1e3a8a;
          --shadow: 0 1px 3px 0 rgb(0 0 0 / 0.08), 0 1px 2px -1px rgb(0 0 0 / 0.08);
        }
        @media (prefers-color-scheme: dark) {
          :root {
            --bg: #0b1120;
            --card-bg: #172033;
            --card-border: #2b3850;
            --panel: #1f2a40;
            --text-primary: #f1f5f9;
            --text-secondary: #cbd5e1;
            --text-muted: #8b9ab3;
            --accent: #60a5fa;
            --accent-soft: #1e3a5f;
            --bar-grid: #2b3850;
            --badge-bg: #26324a;
            --green: #22c55e;
            --amber: #f59e0b;
            --red: #f87171;
            --heat-0: #1f2a40;
            --heat-1: #1e3a8a;
            --heat-2: #2563eb;
            --heat-3: #60a5fa;
            --heat-4: #bfdbfe;
            --shadow: none;
          }
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html { -webkit-text-size-adjust: 100%; }
        body {
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
          background: var(--bg);
          color: var(--text-primary);
          line-height: 1.5;
          padding: 1.5rem 1rem 3rem 1rem;
          overflow-x: hidden;
        }
        .container { max-width: 1100px; margin: 0 auto; }
        header { margin-bottom: 1.25rem; }
        .header-title-row { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem; }
        h1 { font-size: 1.75rem; font-weight: 700; margin-bottom: 0.25rem; }
        .meta-time { font-size: 0.82rem; color: var(--text-muted); }
        .cost-notice, .scope-notice { font-size: 0.82rem; color: var(--text-muted); margin-top: 0.25rem; }
        .header-right { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
        .user-email { font-size: 0.82rem; color: var(--text-secondary); background: var(--badge-bg); padding: 0.2rem 0.5rem; border-radius: 4px; overflow-wrap: anywhere; }
        .logout-form { margin: 0; display: inline; }
        .logout-btn { background: transparent; border: 1px solid var(--card-border); color: var(--text-secondary); padding: 0.25rem 0.6rem; border-radius: 6px; font-size: 0.8rem; cursor: pointer; }
        .logout-btn:hover { background: var(--badge-bg); color: var(--text-primary); }
        .settings-btn {
          background: transparent; border: 1px solid var(--card-border); color: var(--text-secondary);
          padding: 0.25rem 0.6rem; border-radius: 6px; font-size: 0.8rem; text-decoration: none;
          display: inline-flex; align-items: center;
        }
        .settings-btn:hover { background: var(--badge-bg); color: var(--text-primary); }
        .cycle-pill {
          display: inline-block; font-size: 0.85rem; font-weight: 600; color: var(--accent);
          background: var(--badge-bg); padding: 0.2rem 0.6rem; border-radius: 6px; margin-top: 0.35rem;
          border: 1px solid var(--card-border);
        }
        .settings-prompt-banner {
          background: var(--card-bg); border: 1px solid var(--card-border); border-left: 4px solid var(--amber);
          border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 1rem;
          display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.75rem;
        }
        .settings-prompt-link {
          background: var(--accent); color: #ffffff; padding: 0.35rem 0.85rem; border-radius: 6px;
          font-size: 0.82rem; font-weight: 600; text-decoration: none; white-space: nowrap;
        }

        /* Range tabs */
        .range-tabs {
          position: sticky; top: 0; z-index: 5; background: var(--bg);
          display: flex; flex-wrap: wrap; gap: 0.35rem; padding: 0.5rem 0; margin-bottom: 0.75rem;
        }
        .range-tab {
          font-size: 0.85rem; text-decoration: none; color: var(--text-secondary);
          background: var(--card-bg); border: 1px solid var(--card-border);
          padding: 0.3rem 0.75rem; border-radius: 999px; white-space: nowrap;
        }
        .range-tab:hover { color: var(--text-primary); border-color: var(--accent); }
        .range-tab[aria-current="page"] { background: var(--accent); border-color: var(--accent); color: #ffffff; font-weight: 600; }

        .card {
          background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px;
          padding: 1.25rem 1.5rem; margin-bottom: 1.25rem; box-shadow: var(--shadow); min-width: 0;
        }
        .section-head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 0.5rem 1rem; margin-bottom: 1rem; }
        .section-title { font-size: 1.1rem; font-weight: 600; }
        .section-sub { font-size: 0.8rem; color: var(--text-muted); }
        .sub-title { font-size: 0.92rem; font-weight: 600; margin: 1.1rem 0 0.6rem 0; }
        .empty-state { text-align: center; color: var(--text-muted); padding: 1.5rem 1rem; font-size: 0.9rem; }
        .muted { color: var(--text-muted); }
        .num { font-variant-numeric: tabular-nums; }
        .color-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex-shrink: 0; }

        /* Overview */
        .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.75rem; }
        .stat { background: var(--panel); border: 1px solid var(--card-border); border-radius: 10px; padding: 0.75rem 0.9rem; min-width: 0; }
        .stat-label { font-size: 0.78rem; color: var(--text-muted); }
        .stat-value { font-size: 1.45rem; font-weight: 700; line-height: 1.25; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
        .stat-sub { font-size: 0.78rem; color: var(--text-secondary); overflow-wrap: anywhere; }
        .up { color: var(--red); }
        .down { color: var(--green); }
        .range-note { font-size: 0.78rem; color: var(--amber); }

        /* Pool */
        .pool-source { font-size: 0.8rem; color: var(--text-secondary); margin: -0.5rem 0 0.75rem 0; }
        .pool-windows { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 0.6rem; }
        .pool-window { padding: 0.65rem 0.75rem; background: var(--panel); border: 1px solid var(--card-border); border-radius: 8px; min-width: 0; }
        .quota-header { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.4rem; }
        .quota-user { font-weight: 600; font-size: 0.88rem; }
        .quota-plan { font-size: 0.78rem; color: var(--text-secondary); }
        .progress-bar { width: 100%; height: 8px; background: var(--badge-bg); border-radius: 4px; overflow: hidden; margin-bottom: 0.4rem; }
        .progress-fill { height: 100%; border-radius: 4px; }
        .quota-footer { display: flex; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap; font-size: 0.78rem; color: var(--text-secondary); }
        .seg-bar { display: flex; width: 100%; height: 14px; border-radius: 7px; overflow: hidden; background: var(--badge-bg); }
        .seg { height: 100%; min-width: 2px; }
        .seg + .seg { border-left: 2px solid var(--card-bg); }
        .seg-legend { display: flex; flex-wrap: wrap; gap: 0.35rem 1.1rem; margin-top: 0.55rem; font-size: 0.82rem; }
        .seg-legend span { display: inline-flex; align-items: center; gap: 0.35rem; }
        .pool-note { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.4rem; }
        .pool-disagree { margin-top: 0.85rem; font-size: 0.8rem; }
        .pool-disagree > summary { cursor: pointer; color: var(--amber); }
        .quota-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 0.6rem; margin-top: 0.6rem; }
        .quota-item { background: var(--panel); border: 1px solid var(--card-border); border-left-width: 4px; border-radius: 8px; padding: 0.65rem 0.75rem; }

        /* Trend */
        .mode-radio { position: absolute; opacity: 0; pointer-events: none; }
        .mode-switch { display: inline-flex; background: var(--badge-bg); border-radius: 8px; padding: 2px; }
        .mode-switch label { font-size: 0.8rem; padding: 0.2rem 0.65rem; border-radius: 6px; cursor: pointer; color: var(--text-secondary); }
        #tm-person:checked ~ .section-head label[for="tm-person"],
        #tm-model:checked ~ .section-head label[for="tm-model"],
        #tm-agent:checked ~ .section-head label[for="tm-agent"] { background: var(--card-bg); color: var(--text-primary); font-weight: 600; box-shadow: var(--shadow); }
        #tm-person:focus-visible ~ .section-head label[for="tm-person"],
        #tm-model:focus-visible ~ .section-head label[for="tm-model"],
        #tm-agent:focus-visible ~ .section-head label[for="tm-agent"] { outline: 2px solid var(--accent); }
        .trend-panel { display: none; }
        #tm-person:checked ~ .trend-person, #tm-model:checked ~ .trend-model, #tm-agent:checked ~ .trend-agent { display: block; }
        .chart-legend { display: flex; flex-wrap: wrap; gap: 0.3rem 1rem; margin-bottom: 0.6rem; font-size: 0.8rem; }
        .legend-item { display: inline-flex; align-items: center; gap: 0.35rem; min-width: 0; overflow-wrap: anywhere; }
        .chart-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
        .chart-svg { display: block; width: 100%; height: auto; }
        .chart-svg .hit { fill: transparent; cursor: pointer; }
        .chart-svg .hit:hover, .chart-svg .hit.on { fill: var(--text-muted); fill-opacity: 0.12; }
        .chart-readout { min-height: 1.4em; font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.4rem; overflow-wrap: anywhere; }

        /* Ranking */
        .rank-table { font-size: 0.86rem; }
        .rank-line, .rank-head {
          display: grid; align-items: center; gap: 0.5rem;
          grid-template-columns: minmax(120px, 1.4fr) 76px 76px minmax(118px, 1fr) 64px minmax(96px, 1.1fr) 112px 128px;
          padding: 0.55rem 0.5rem;
        }
        .rank-head { font-size: 0.75rem; color: var(--text-muted); border-bottom: 1px solid var(--card-border); padding-top: 0; }
        .sort-btn { all: unset; cursor: pointer; white-space: nowrap; }
        .sort-btn:hover, .sort-btn[aria-sort] { color: var(--text-primary); }
        .sort-btn:focus-visible { outline: 2px solid var(--accent); border-radius: 3px; }
        .sort-btn[aria-sort="descending"]::after { content: " ↓"; }
        .sort-btn[aria-sort="ascending"]::after { content: " ↑"; }
        .rank-row { border-bottom: 1px solid var(--card-border); }
        .rank-row > summary { list-style: none; cursor: pointer; }
        .rank-row > summary::-webkit-details-marker { display: none; }
        .rank-row > summary:hover, .rank-row[open] > summary { background: var(--panel); }
        .rank-row > summary:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
        .cell { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .cell.share-cell { overflow: visible; }
        .cell-name { display: flex; align-items: center; gap: 0.45rem; }
        .member-title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; }
        .member-label { font-size: 0.75rem; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; }
        .cell-num { text-align: right; font-variant-numeric: tabular-nums; }
        .share-cell { display: flex; align-items: center; gap: 0.4rem; }
        .share-bar-bg { flex: 1; height: 6px; background: var(--badge-bg); border-radius: 3px; overflow: hidden; min-width: 30px; }
        .share-bar-fill { height: 100%; border-radius: 3px; }
        .share-pct { font-size: 0.75rem; color: var(--text-secondary); min-width: 3.6em; flex-shrink: 0; white-space: nowrap; text-align: right; font-variant-numeric: tabular-nums; }
        .cell-small { font-size: 0.78rem; color: var(--text-secondary); }
        .badge { font-size: 0.72rem; padding: 0.15rem 0.45rem; border-radius: 4px; font-weight: 500; white-space: nowrap; }
        .badge-active { background: #dcfce7; color: #15803d; }
        .badge-stale { background: #fee2e2; color: #b91c1c; }
        .badge-never { background: var(--badge-bg); color: var(--text-muted); }
        @media (prefers-color-scheme: dark) {
          .badge-active { background: #14532d; color: #86efac; }
          .badge-stale { background: #7f1d1d; color: #fca5a5; }
          .badge-never { background: var(--badge-bg); color: var(--text-muted); }
        }
        .rank-zero { border-bottom: 1px solid var(--card-border); }
        .rank-zero > summary { cursor: pointer; padding: 0.6rem 0.5rem; font-size: 0.82rem; color: var(--text-muted); }
        .rank-zero .rank-row:last-child { border-bottom: none; }
        .rank-detail { padding: 0.25rem 0.75rem 1rem 1.6rem; }
        .detail-meta { display: flex; flex-wrap: wrap; gap: 0.25rem 1rem; font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.6rem; }
        .member-scope { overflow-wrap: anywhere; }
        .legacy-note { color: var(--amber); }
        .detail-grid { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 1rem; }
        .detail-block h4 { font-size: 0.78rem; font-weight: 600; color: var(--text-secondary); margin-bottom: 0.35rem; }
        .detail-wide { grid-column: 1 / -1; }
        .mini-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; table-layout: fixed; }
        .mini-table td, .mini-table th { padding: 0.25rem 0.25rem; text-align: left; border-bottom: 1px dashed var(--card-border); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .mini-table th { color: var(--text-muted); font-weight: 500; border-bottom-style: solid; }
        .mini-table tr:last-child td { border-bottom: none; }
        .mini-table .text-right { text-align: right; width: 5.5em; font-variant-numeric: tabular-nums; }
        .other-row td { color: var(--text-muted); }
        .device-list { display: flex; flex-direction: column; gap: 0.4rem; }
        .device-item { background: var(--panel); border: 1px solid var(--card-border); border-radius: 6px; padding: 0.45rem 0.6rem; font-size: 0.78rem; }
        .device-item-top { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
        .device-name { font-weight: 600; overflow-wrap: anywhere; }
        .device-totals { font-weight: 600; white-space: nowrap; font-variant-numeric: tabular-nums; }
        .device-item-meta { color: var(--text-muted); margin-top: 0.15rem; display: flex; flex-wrap: wrap; gap: 0.1rem 0.6rem; overflow-wrap: anywhere; }
        .mini-svg { display: block; width: 100%; height: 48px; }

        /* Analysis */
        .insight-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.6rem; margin-bottom: 0.4rem; }
        .insight { background: var(--panel); border: 1px solid var(--card-border); border-radius: 10px; padding: 0.65rem 0.8rem; min-width: 0; }
        .insight-label { font-size: 0.75rem; color: var(--text-muted); }
        .insight-value { font-size: 1.05rem; font-weight: 700; line-height: 1.3; overflow-wrap: anywhere; }
        .insight-detail { font-size: 0.75rem; color: var(--text-secondary); }
        .bar-list { display: flex; flex-direction: column; gap: 0.1rem; font-size: 0.84rem; }
        .bar-row {
          display: grid; align-items: center; gap: 0.5rem; padding: 0.3rem 0;
          grid-template-columns: minmax(120px, 1.6fr) 72px 72px minmax(90px, 1fr) 44px;
        }
        .bar-list.compact .bar-row { grid-template-columns: minmax(90px, 1fr) 70px minmax(80px, 1.2fr); }
        .bar-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .bar-name small { color: var(--text-muted); margin-left: 0.3rem; }
        .bar-row.other-row { color: var(--text-muted); }
        .split-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 0 1.5rem; }

        /* Heatmap */
        .heat { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 8px; }
        .heat-months { display: grid; gap: 4px; font-size: 0.72rem; color: var(--text-muted); }
        .heat-months span { white-space: nowrap; }
        .heat-days { display: grid; align-items: center; grid-template-rows: repeat(7, 26px); gap: 4px; font-size: 0.68rem; color: var(--text-muted); }
        .heat-grid { display: grid; grid-template-rows: repeat(7, 26px); grid-auto-flow: column; gap: 4px; }
        .heat-cell { border-radius: 4px; background: var(--heat-0); }
        .heat-cell.l1 { background: var(--heat-1); }
        .heat-cell.l2 { background: var(--heat-2); }
        .heat-cell.l3 { background: var(--heat-3); }
        .heat-cell.l4 { background: var(--heat-4); }
        .heat-cell.blank { background: transparent; }
        .heat-cell.today { outline: 2px solid var(--text-secondary); outline-offset: 1px; }
        .heat-foot { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.4rem 1rem; margin-top: 0.75rem; }
        .heat-legend { display: flex; align-items: center; gap: 4px; font-size: 0.72rem; color: var(--text-muted); }
        .heat-summary { font-size: 0.78rem; color: var(--text-secondary); }
        .heat-legend .heat-cell { width: 12px; height: 12px; display: inline-block; }

        @media (max-width: 760px) {
          body { padding: 1rem 0.75rem 2.5rem 0.75rem; }
          h1 { font-size: 1.4rem; }
          .range-tabs { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; margin-left: -0.75rem; margin-right: -0.75rem; padding-left: 0.75rem; padding-right: 0.75rem; }
          .range-tabs::-webkit-scrollbar { display: none; }
          .card { padding: 1rem; }
          .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.5rem; }
          .stat-value { font-size: 1.2rem; }
          .insight-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.5rem; }
          .insight-value { font-size: 0.95rem; }
          .heat-days, .heat-grid { grid-template-rows: repeat(7, 16px); gap: 3px; }
          .heat-months { gap: 3px; }
          .heat-cell { border-radius: 3px; }
          .rank-head { display: none; }
          .rank-line {
            grid-template-columns: minmax(0, 1fr) auto auto;
            grid-template-areas: "name tokens cost" "share change status";
            row-gap: 0.3rem; padding: 0.6rem 0.25rem;
          }
          .c-name { grid-area: name; }
          .c-tokens { grid-area: tokens; }
          .c-cost { grid-area: cost; }
          .c-share { grid-area: share; }
          .c-change { grid-area: change; }
          .c-status { grid-area: status; text-align: right; }
          .c-model, .c-last { display: none; }
          .rank-detail { padding: 0.25rem 0.25rem 0.9rem 0.25rem; }
          .detail-grid { grid-template-columns: minmax(0, 1fr); }
          .bar-row { grid-template-columns: minmax(0, 1fr) 64px minmax(60px, 0.8fr); }
          .bar-row .b-cost, .bar-row .b-users, .bar-name small { display: none; }
        }
"""


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _md(iso: Optional[str]) -> str:
    """'2026-11-20' -> '11/20'; '2026-11' -> '2026-11'."""
    if not iso:
        return ""
    if len(iso) == 10:
        return iso[5:7] + "/" + iso[8:10]
    return iso


def format_change(change_pct: Optional[float], cur: int, prev: Optional[int]) -> tuple:
    """(text, css class) for a ±% comparison."""
    if prev is None:
        return "—", ""
    if prev <= 0:
        return ("新增", "up") if cur > 0 else ("—", "")
    if change_pct is None or abs(change_pct) < 0.05:
        return "0.0%", ""
    return f"{change_pct:+.1f}%", "up" if change_pct > 0 else "down"


def range_title(rng: dict) -> str:
    label = rng["label"]
    if rng["key"] == "all":
        return label
    start, end = rng.get("start"), rng.get("end")
    if start == end:
        return f"{label} · {_md(start)}"
    return f"{label} · {_md(start)} – {_md(end)}"


@functools.lru_cache(maxsize=1)
def dashboard_js_version() -> str:
    """Content hash for the script URL, so a CDN never serves a stale or cached-404 copy."""
    path = os.path.join(os.path.dirname(__file__), "static", "dashboard.js")
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:12]
    except OSError:
        return "0"


def embed_json(obj) -> str:
    """JSON safe inside <script type="application/json">: no '<', '>' or '&' survive."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return (text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


# ---------------------------------------------------------------- range view

def render_overview(rng: Optional[dict], key: str) -> str:
    if rng is None:
        return ('<section class="card"><div class="section-head"><h2 class="section-title">'
                f'{_e(ranges.RANGE_LABELS[key])}</h2></div>'
                '<div class="empty-state">暂无 Google AI Ultra 额度重置时间，无法计算「重置以来」。</div></section>')
    tot = rng["total"]
    tokens = tot["tokens"]["total"]
    out = ['<section class="card">', '<div class="section-head">',
           f'<h2 class="section-title">{_e(range_title(rng))}</h2>']
    if rng.get("note"):
        out.append(f'<span class="range-note">{_e(rng["note"])}</span>')
    out.append('</div><div class="stat-grid">')

    def stat(label, value, sub, cls=""):
        cls_attr = f' {cls}' if cls else ""
        out.append(f'<div class="stat"><div class="stat-label">{_e(label)}</div>'
                   f'<div class="stat-value{cls_attr}">{_e(value)}</div>'
                   f'<div class="stat-sub">{_e(sub)}</div></div>')

    stat("总 token", format_tokens(tokens), "折算 " + format_cost(tot["cost"]))
    if rng.get("compare_label") and tot.get("prev_tokens") is not None:
        if rng.get("compare_mode") == "reference":
            stat(rng["compare_label"], format_tokens(tot["prev_tokens"]), "折算 " + format_cost(tot["prev_cost"] or 0.0))
        else:
            text, cls = format_change(tot["change_pct"], tokens, tot["prev_tokens"])
            stat(rng["compare_label"], text, f'{rng["compare_label"][1:]} {format_tokens(tot["prev_tokens"])}', cls)
    stat("活跃成员", f'{rng["active_members"]}/{rng["member_count"]}', "该时段有用量")
    if rng["elapsed_days"] > 1:
        stat("日均 token", format_tokens(rng["daily_avg"]), f'按 {rng["elapsed_days"]} 天')
    # The peak only says something when usage is spread over more than one day/month.
    if rng.get("peak") and rng["elapsed_days"] > 1 and rng["peak"]["tokens"] < tokens:
        peak = rng["peak"]
        stat("峰值日" if rng["bucket"] == "day" else "峰值月", format_tokens(peak["tokens"]), _md(peak["key"]))
    out.append('</div></section>')
    return "".join(out)


def _nice_max(value: int) -> int:
    if value <= 0:
        return 1000
    magnitude = 10 ** max(0, len(str(int(value))) - 1)
    return int(((value + magnitude - 1) // magnitude) * magnitude)


def render_trend_svg(chart: dict, series: List[dict], bucket: str) -> str:
    buckets = chart["buckets"]
    n = max(1, len(buckets))
    width = max(720, 70 + n * 24)
    height = 220
    ml, mr, mt, mb = 56, 12, 14, 28
    pw, ph = width - ml - mr, height - mt - mb
    slot = pw / n
    bw = min(slot * 0.7, 48.0)
    y_max = _nice_max(max(chart["totals"] or [0]))
    min_w = f' style="min-width: {n * 16 + 70}px;"' if n > 12 else ""
    out = [f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="用量趋势图"{min_w}>']
    for frac in (0.0, 0.5, 1.0):
        y = mt + ph * (1 - frac)
        out.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{width - mr}" y2="{y:.1f}" stroke="var(--bar-grid)" stroke-dasharray="3,3"/>')
        out.append(f'<text x="{ml - 8}" y="{y + 4:.1f}" text-anchor="end" fill="var(--text-muted)" font-size="11">{_e(format_tokens(int(y_max * frac)))}</text>')
    step = max(1, math.ceil(n / 12))
    for i, b in enumerate(buckets):
        x = ml + i * slot + (slot - bw) / 2
        y_cur = mt + ph
        for s in series:
            v = s["values"][i]
            if v <= 0:
                continue
            h = v / y_max * ph
            y_cur -= h
            out.append(f'<rect x="{x:.1f}" y="{y_cur:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{_e(s["color"])}" rx="2"/>')
        if i % step == 0 or i == n - 1:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{height - 9}" text-anchor="middle" fill="var(--text-muted)" font-size="10">{_e(_md(b))}</text>')
    for i, b in enumerate(buckets):
        lines = [f'{_md(b)} 合计 {format_tokens(chart["totals"][i])}']
        for s in series:
            if s["values"][i] > 0:
                lines.append(f'{s["label"]} {format_tokens(s["values"][i])}')
        out.append(f'<rect class="hit" data-i="{i}" x="{ml + i * slot:.1f}" y="{mt}" width="{slot:.1f}" height="{ph}">'
                   f'<title>{_e(chr(10).join(lines))}</title></rect>')
    out.append('</svg>')
    return "".join(out)


def render_trend(rng: dict, mode: str = "person") -> str:
    chart = rng["chart"]
    out = ['<section class="card trend">']
    for m, _ in TREND_MODES:
        checked = " checked" if m == mode else ""
        out.append(f'<input type="radio" class="mode-radio" name="trend-mode" id="tm-{m}" value="{m}"{checked}>')
    out.append('<div class="section-head"><h2 class="section-title">趋势'
               f'<span class="section-sub"> · {"每天" if rng["bucket"] == "day" else "每月"}一根</span></h2>'
               '<div class="mode-switch" role="radiogroup" aria-label="趋势分组">')
    for m, label in TREND_MODES:
        out.append(f'<label for="tm-{m}">{label}</label>')
    out.append('</div></div>')
    for m, _ in TREND_MODES:
        series = chart[m]
        out.append(f'<div class="trend-panel trend-{m}">')
        if not series:
            out.append('<div class="empty-state">该时段暂无用量</div></div>')
            continue
        out.append('<div class="chart-legend">')
        for s in series:
            out.append(f'<span class="legend-item"><span class="color-dot" style="background: {_e(s["color"])};"></span>{_e(s["label"])}</span>')
        out.append('</div><div class="chart-scroll">')
        out.append(render_trend_svg(chart, series, rng["bucket"]))
        out.append('</div></div>')
    out.append('<div class="chart-readout" aria-live="polite"></div></section>')
    return "".join(out)


def render_mini_svg(values: List[int], color: str) -> str:
    n = max(1, len(values))
    vmax = max(values or [0]) or 1
    w = n * 10
    out = [f'<svg class="mini-svg" viewBox="0 0 {w} 48" preserveAspectRatio="none" role="img" aria-label="每日用量">']
    for i, v in enumerate(values):
        if v <= 0:
            continue
        h = max(1.5, v / vmax * 46)
        out.append(f'<rect x="{i * 10 + 1}" y="{48 - h:.1f}" width="8" height="{h:.1f}" fill="{_e(color)}" rx="1"/>')
    out.append('</svg>')
    return "".join(out)


def _rank_row(row: dict, meta: dict, rng: dict) -> str:
    text, cls = format_change(row["change_pct"], row["tokens"], row["prev_tokens"])
    change_sort = row["change_pct"] if row["change_pct"] is not None else (1e12 if text == "新增" else -1e12)
    out = [f'<details class="rank-row" data-name="{_e(meta["name"])}" data-tokens="{row["tokens"]}" '
           f'data-cost="{row["cost"]}" data-change="{change_sort}" data-model="{_e(row["top_model"] or "")}" '
           f'data-last="{meta["received_ts"]}">',
           '<summary class="rank-line">',
           f'<div class="cell cell-name c-name"><span class="color-dot" style="background: {_e(meta["color"])};"></span>'
           f'<div class="cell"><div class="member-title">{_e(meta["name"])}</div>']
    if meta.get("label"):
        out.append(f'<div class="member-label">{_e(meta["label"])}</div>')
    out.append('</div></div>')
    out.append(f'<div class="cell cell-num c-tokens">{_e(format_tokens(row["tokens"]))}</div>')
    out.append(f'<div class="cell cell-num c-cost">{_e(format_cost(row["cost"]))}</div>')
    out.append(f'<div class="share-cell cell c-share"><div class="share-bar-bg"><div class="share-bar-fill" '
               f'style="width: {min(100.0, row["share"]):.1f}%; background: {_e(meta["color"])};"></div></div>'
               f'<span class="share-pct">{row["share"]:.1f}%</span></div>')
    cls_attr = f' {cls}' if cls else ""
    out.append(f'<div class="cell cell-num c-change{cls_attr}">{_e(text)}</div>')
    out.append(f'<div class="cell cell-small c-model">{_e(row["top_model"] or "—")}</div>')
    out.append(f'<div class="cell cell-small c-last">{_e(meta["received"])}</div>')
    out.append(f'<div class="cell c-status"><span class="{STATUS_CLASS[meta["status"]]}">{_e(STATUS_TEXT[meta["status"]])}</span></div>')
    out.append('</summary><div class="rank-detail"><div class="detail-meta">')
    out.append(f'<span>上次上报：{_e(meta["received"])}</span>')
    if meta.get("scope"):
        out.append(f'<span class="member-scope">{_e(meta["scope"])}</span>')
    if meta.get("legacy"):
        out.append(f'<span class="legacy-note">{meta["legacy"]} 台电脑使用旧版 Kanjo 未计入 — 请更新客户端以合并统计</span>')
    out.append('</div><div class="detail-grid"><div class="detail-block"><h4>模型明细</h4>')
    if row["models"]:
        out.append('<table class="mini-table"><thead><tr><th>模型</th><th class="text-right">Token</th>'
                   '<th class="text-right">折算金额</th></tr></thead><tbody>')
        for mr in row["models"]:
            other = ' class="other-row"' if mr.get("other") else ""
            out.append(f'<tr{other}><td title="{_e(mr["model"])}">{_e(mr["model"])}</td>'
                       f'<td class="text-right">{_e(format_tokens(mr["tokens"]))}</td>'
                       f'<td class="text-right">{_e(format_cost(mr["cost"]))}</td></tr>')
        out.append('</tbody></table>')
    else:
        out.append('<div class="muted">该时段暂无模型用量明细</div>')
    out.append('</div><div class="detail-block">')
    devices = meta.get("devices") or []
    if devices:
        out.append(f'<h4>{len(devices)} 台电脑</h4><div class="device-list">')
        for i, dev in enumerate(devices):
            dr = row["devices"][i] if i < len(row["devices"]) else {"tokens": 0, "cost": 0.0}
            out.append('<div class="device-item"><div class="device-item-top">'
                       f'<span class="device-name">{_e(dev["name"])}</span>'
                       f'<span class="device-totals">{_e(format_tokens(dr["tokens"]))} ({_e(format_cost(dr["cost"]))})</span>'
                       '</div><div class="device-item-meta">'
                       f'<span>{_e(dev["os"])}</span><span>{_e(dev["version"])}</span><span>{_e(dev["tz"])}</span>'
                       f'<span>上次上报：{_e(dev["received"])}</span>'
                       f'<span>累计 {_e(format_tokens(dev["all_tokens"]))} ({_e(format_cost(dev["all_cost"]))})</span>'
                       '</div></div>')
        out.append('</div>')
    else:
        out.append('<h4>电脑</h4><div class="muted">从未上报</div>')
    out.append('</div>')
    if rng["chart"]["buckets"]:
        out.append(f'<div class="detail-block detail-wide"><h4>{"每日" if rng["bucket"] == "day" else "每月"}用量</h4>')
        out.append(render_mini_svg(row["series"], meta["color"]))
        out.append('</div>')
    out.append('</div></div></details>')
    return "".join(out)


RANK_COLUMNS = (
    ("name", "成员", "c-name"),
    ("tokens", "Token", "c-tokens cell-num"),
    ("cost", "金额", "c-cost cell-num"),
    ("tokens", "占比", "c-share"),
    ("change", "变化", "c-change cell-num"),
    ("model", "常用模型", "c-model"),
    ("last", "最后上报", "c-last"),
    (None, "状态", "c-status"),
)


def render_ranking(rng: dict, member_meta: dict) -> str:
    out = ['<section class="card ranking"><div class="section-head"><h2 class="section-title">成员排行</h2>'
           '<span class="section-sub">点一行展开模型、电脑和每日用量</span></div>']
    rows = rng["members"]
    if not rows:
        out.append('<div class="empty-state">尚未添加任何成员</div></section>')
        return "".join(out)
    out.append('<div class="rank-table"><div class="rank-head">')
    for sort_key, label, cls in RANK_COLUMNS:
        if sort_key is None:
            out.append(f'<div class="{cls}">{label}</div>')
        else:
            current = ' aria-sort="descending"' if (sort_key == "tokens" and label == "Token") else ""
            out.append(f'<div class="{cls}"><button type="button" class="sort-btn" data-sort="{sort_key}"{current}>{label}</button></div>')
    out.append('</div><div class="rank-body">')
    zero = []
    for row in rows:
        meta = member_meta[row["id"]]
        if row["tokens"] <= 0 and row["cost"] <= 0:
            zero.append((row, meta))
            continue
        out.append(_rank_row(row, meta, rng))
    out.append('</div>')
    if zero:
        out.append(f'<details class="rank-zero"><summary>另有 {len(zero)} 人无用量</summary>')
        for row, meta in zero:
            out.append(_rank_row(row, meta, rng))
        out.append('</details>')
    out.append('</div></section>')
    return "".join(out)


def _bar_list(rows: List[dict], compact: bool, colors: Optional[List[str]] = None) -> str:
    out = [f'<div class="bar-list{" compact" if compact else ""}">']
    for i, r in enumerate(rows):
        other = r.get("other")
        color = "var(--text-muted)" if other else (colors[i] if colors and i < len(colors) else "var(--heat-2)")
        name = r.get("model") if "model" in r else r.get("label")
        out.append(f'<div class="bar-row{" other-row" if other else ""}">')
        sub = f'<small>{_e(r["provider"])}</small>' if r.get("provider") else ""
        out.append(f'<div class="bar-name" title="{_e(name)}">{_e(name)}{sub}</div>')
        out.append(f'<div class="cell-num">{_e(format_tokens(r["tokens"]))}</div>')
        if not compact:
            out.append(f'<div class="cell-num b-cost">{_e(format_cost(r["cost"]))}</div>')
        out.append(f'<div class="share-cell"><div class="share-bar-bg"><div class="share-bar-fill" '
                   f'style="width: {min(100.0, r["share"]):.1f}%; background: {color};"></div></div>'
                   f'<span class="share-pct">{r["share"]:.1f}%</span></div>')
        if not compact:
            users = "" if r.get("users") is None else f'{r["users"]} 人'
            out.append(f'<div class="cell-small b-users">{_e(users)}</div>')
        out.append('</div>')
    out.append('</div>')
    return "".join(out)


def _insight_value(ins: dict) -> tuple:
    if ins["key"] == "peak":
        return _md(ins["value"]), format_tokens(ins["tokens"])
    return ins["value"], ins.get("detail") or ""


def render_analysis(rng: dict) -> str:
    out = ['<section class="card analysis"><div class="section-head"><h2 class="section-title">分析</h2></div>']
    if rng["insights"]:
        out.append('<div class="insight-grid">')
        for ins in rng["insights"]:
            value, detail = _insight_value(ins)
            out.append(f'<div class="insight"><div class="insight-label">{_e(ins["label"])}</div>'
                       f'<div class="insight-value" title="{_e(value)}">{_e(value)}</div>'
                       f'<div class="insight-detail">{_e(detail)}</div></div>')
        out.append('</div>')
    out.append('<h3 class="sub-title">模型排行</h3>')
    if rng["models"]:
        out.append(_bar_list(rng["models"], compact=False, colors=ranges.SERIES_PALETTE))
    else:
        out.append('<div class="empty-state">该时段暂无模型用量明细</div>')
    out.append('<div class="split-grid"><div><h3 class="sub-title">按服务商</h3>')
    out.append(_bar_list(rng["providers"], compact=True, colors=ranges.SERIES_PALETTE) if rng["providers"]
               else '<div class="muted">—</div>')
    out.append('</div><div><h3 class="sub-title">按代理</h3>')
    out.append(_bar_list(rng["agents"], compact=True, colors=ranges.SERIES_PALETTE) if rng["agents"]
               else '<div class="muted">—</div>')
    out.append('</div></div></section>')
    return "".join(out)


def render_main(rng: Optional[dict], member_meta: dict, mode: str = "person") -> str:
    if rng is None:
        return ""
    return render_trend(rng, mode) + render_ranking(rng, member_meta) + render_analysis(rng)


# ---------------------------------------------------------------- static sections

def _countdown(target: datetime, now: datetime) -> str:
    secs = int((target - now).total_seconds())
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    if days > 0:
        return f"还剩 {days} 天 {hours} 小时"
    if hours > 0:
        return f"还剩 {hours} 小时 {rem // 60} 分"
    return f"还剩 {max(1, rem // 60)} 分钟"


def _pct_color(pct: Optional[float]) -> str:
    if pct is None:
        return "var(--text-muted)"
    if pct >= 95.0:
        return "var(--red)"
    if pct >= 80.0:
        return "var(--amber)"
    return "var(--green)"


def render_pool(ctx: dict) -> str:
    tz, now = ctx["tz"], ctx["now"]
    entries = ctx["pool_entries"]
    latest = ctx["pool_latest"]
    out = ['<section class="card pool"><div class="section-head">'
           '<h2 class="section-title">Google AI Ultra 额度池（全家共用）</h2></div>']
    if not entries:
        out.append('<div class="empty-state">暂无成员上报 Google AI Ultra 额度数据</div></section>')
        return "".join(out)
    src_dev = f"（{_e(latest['device_name'])}）" if latest.get("device_name") else ""
    src_time = format_dt(latest["received_at"], tz) if latest.get("received_at") else "—"
    out.append(f'<div class="pool-source">数据来自 {_e(latest["member_name"])} 的最新上报{src_dev} · {_e(src_time)}</div>')
    out.append('<div class="pool-windows">')
    for w in latest["windows"]:
        pct = max(0.0, min(100.0, w["used_percent"]))
        reset_dt = parse_iso(w.get("resets_at"))
        if reset_dt is not None and reset_dt.tzinfo is None:
            reset_dt = reset_dt.replace(tzinfo=timezone.utc)
        if reset_dt is None:
            reset_str, left = "重置时间未知", ""
        elif reset_dt <= now:
            reset_str, left = "已到重置时间，等待新的上报", ""
        else:
            reset_str, left = "重置：" + format_dt(reset_dt, tz), _countdown(reset_dt, now)
        out.append('<div class="pool-window"><div class="quota-header">'
                   f'<span class="quota-user">{_e(w["label"])}</span>'
                   f'<span class="quota-plan">已用 <strong>{pct:.1f}%</strong> · 剩余 {100.0 - pct:.1f}%</span></div>'
                   f'<div class="progress-bar"><div class="progress-fill" style="width: {pct:.1f}%; background: {_pct_color(pct)};"></div></div>'
                   f'<div class="quota-footer"><span>{_e(reset_str)}</span><span>{_e(left)}</span></div></div>')
    out.append('</div>')

    week_start = ctx["pool_week_start"]
    if week_start is not None:
        users, total = ctx["pool_week_users"], ctx["pool_week_total"]
        out.append(f'<h3 class="sub-title">重置以来谁用掉了额度池 <span class="section-sub">本额度周（{_e(week_start.strftime("%m/%d %H:%M"))} 起）</span></h3>')
        if not users:
            out.append('<div class="muted">本额度周暂无用量记录</div>')
        else:
            out.append('<div class="seg-bar" role="img" aria-label="各成员额度池用量占比">')
            for u in users:
                share = u["tokens"] / total * 100.0 if total > 0 else 0.0
                out.append(f'<div class="seg" style="width: {share:.2f}%; background: {_e(u["color"])};" '
                           f'title="{_e(u["name"])} {format_tokens(u["tokens"])} tokens ({share:.1f}%)"></div>')
            out.append('</div><div class="seg-legend">')
            for u in users:
                share = u["tokens"] / total * 100.0 if total > 0 else 0.0
                lbl = f" ({_e(u['label'])})" if u["label"] else ""
                out.append(f'<span><span class="color-dot" style="background: {_e(u["color"])};"></span>'
                           f'<strong>{_e(u["name"])}</strong>{lbl} {format_tokens(u["tokens"])} tokens ({share:.1f}%)</span>')
            out.append('</div><div class="pool-note">按天统计，额度周起始当天的用量整天计入。</div>')

    if ctx["show_per_member"]:
        out.append('<details class="pool-disagree"><summary>各台电脑上报的周额度数值不一致，额度可能并非共用 · 查看各台</summary>'
                   '<div class="quota-grid">')
        for q in entries:
            lbl = f" ({_e(q['member_label'])})" if q["member_label"] else ""
            pct = q["quota"]["weekly_used_percent"]
            reset_dt = parse_iso(q["quota"]["weekly_resets_at"])
            reset_str = format_dt(reset_dt, tz) if reset_dt else "—"
            out.append(f'<div class="quota-item" style="border-left-color: {_e(q["color"])};"><div class="quota-header">'
                       f'<span class="quota-user">{_e(q["member_name"])}{lbl}</span>'
                       f'<span class="quota-plan">{_e(q["quota"]["plan"])}</span></div>')
            if pct is not None:
                out.append(f'<div class="progress-bar"><div class="progress-fill" style="width: {min(100.0, pct):.1f}%; background: {_pct_color(pct)};"></div></div>')
            pct_str = "未知" if pct is None else f"{pct:.1f}%"
            out.append(f'<div class="quota-footer"><span>周额度已用：<strong>{pct_str}</strong></span>'
                       f'<span>重置时间：{_e(reset_str)}</span></div></div>')
        out.append('</div></details>')
    out.append('</section>')
    return "".join(out)


def render_heatmap(heatmap: dict, today_iso: str) -> str:
    """Week columns (Monday on top) stretched to the card width, month labels above."""
    from datetime import date as _date

    days = heatmap["days"]
    vmax = heatmap["max"]
    out = ['<section class="card"><div class="section-head"><h2 class="section-title">近 62 天热力日历</h2>'
           '<span class="section-sub">全家每日用量，颜色越深用得越多</span></div>']
    if not days:
        out.append('<div class="empty-state">暂无数据</div></section>')
        return "".join(out)
    first = _date.fromisoformat(days[0]["date"])
    lead = first.weekday()
    n_cols = (lead + len(days) + 6) // 7
    cols_style = f'grid-template-columns: repeat({n_cols}, minmax(0, 1fr));'

    months = []
    for i, d in enumerate(days):
        day = _date.fromisoformat(d["date"])
        col = (lead + i) // 7
        if i == 0 or day.day == 1:
            if months and months[-1][0] == col:
                months[-1] = (col, day.month)
            else:
                months.append((col, day.month))
    out.append('<div class="heat"><div></div>')
    out.append(f'<div class="heat-months" style="{cols_style}">')
    for col, month in months:
        out.append(f'<span style="grid-column: {col + 1};">{month}月</span>')
    out.append('</div><div class="heat-days"><span>一</span><span></span><span>三</span><span></span>'
               '<span>五</span><span></span><span>日</span></div>')
    out.append(f'<div class="heat-grid" style="{cols_style}">')
    for _ in range(lead):
        out.append('<div class="heat-cell blank"></div>')
    total = 0
    active = 0
    for d in days:
        total += d["tokens"]
        level = 0
        if vmax > 0 and d["tokens"] > 0:
            active += 1
            level = min(4, max(1, math.ceil(d["tokens"] / vmax * 4)))
        cls = f"heat-cell l{level}" + (" today" if d["date"] == today_iso else "")
        title = f'{d["date"]} · {format_tokens(d["tokens"])} tokens · {format_cost(d["cost"])}'
        out.append(f'<div class="{cls}" title="{_e(title)}"></div>')
    out.append('</div></div><div class="heat-foot"><div class="heat-legend">少')
    for lv in range(5):
        out.append(f'<span class="heat-cell l{lv}"></span>')
    out.append('多</div>')
    summary = f"合计 {format_tokens(total)} · {active} 天有用量"
    if vmax > 0:
        peak = max(days, key=lambda d: d["tokens"])
        summary += f' · 最高 {_md(peak["date"])} {format_tokens(peak["tokens"])}'
    out.append(f'<div class="heat-summary">{_e(summary)}</div></div></section>')
    return "".join(out)


def member_meta_for(members: List[dict], tz) -> dict:
    """Range-independent per-member info shared by the server render and the JSON block."""
    meta = {}
    for m in members:
        rec = m.get("received_at")
        meta[m["id"]] = {
            "id": m["id"],
            "name": m["name"],
            "label": m.get("label"),
            "color": m["color"],
            "status": m["status"],
            "received": format_dt(rec, tz) if rec else "从未上报",
            "received_ts": int(rec.timestamp()) if rec else 0,
            "scope": m.get("scope_str"),
            "legacy": m.get("legacy_excluded_count") or 0,
            "devices": [
                {
                    "name": str(d.get("device_name") or "—"),
                    "os": format_os(str(d.get("os") or "")),
                    "version": str(d.get("generated_by") or "—"),
                    "tz": str(d.get("timezone") or "—"),
                    "received": format_dt(d.get("received_at"), tz),
                    "all_tokens": int(d.get("all_time_tokens") or 0),
                    "all_cost": float(d.get("all_time_cost") or 0.0),
                }
                for d in (m.get("devices") or [])
            ],
        }
    return meta


def render_page(ctx: dict) -> str:
    key = ctx["range_key"]
    tz = ctx["tz"]
    member_meta = member_meta_for(ctx["members"], tz)
    rng = ctx["ranges"].get(key)

    doc = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        '  <meta name="color-scheme" content="light dark">',
        "  <title>家庭用量面板 · Kanjo</title>",
        "  <style>" + CSS + "  </style>",
        "</head>",
        "<body>",
        '  <div class="container">',
        "    <header>",
        '      <div class="header-title-row">',
        "        <div>",
        "          <h1>家庭用量汇总</h1>",
        f'          <div class="cycle-pill">{_e(ctx["cycle_range_str"])} · 剩余 {ctx["days_remaining"]} 天 · 至 {ctx["next_start"].strftime("%m/%d")} 重置</div>',
        f'          <div class="cost-notice">注：{_e(COST_NOTE)}</div>',
    ]
    if ctx["top_scope_str"]:
        doc.append(f'          <div class="scope-notice">{_e(ctx["top_scope_str"])}</div>')
    doc.extend([
        "        </div>",
        '        <div class="header-right">',
        f'          <span class="meta-time">刷新时间：{_e(format_dt(ctx["local_now"]))} ({_e(ctx["tz_name"])})</span>',
        '          <a href="/settings" class="settings-btn">设置</a>',
    ])
    if ctx["user_email"]:
        doc.append(f'          <span class="user-email">{_e(ctx["user_email"])}</span>')
        doc.append('          <form method="POST" action="/auth/logout" class="logout-form">')
        doc.append('            <button type="submit" class="logout-btn">退出</button>')
        doc.append('          </form>')
    doc.extend(["        </div>", "      </div>", "    </header>"])

    if not ctx["has_cycle_setting"]:
        doc.append('    <div class="settings-prompt-banner">')
        doc.append('      <div class="prompt-text"><strong>提示：</strong>尚未设置计费周期起始日，当前按自然月展示。请前往设置以匹配 Google AI Ultra 续费日。</div>')
        doc.append('      <a href="/settings" class="settings-prompt-link">设置周期起始日 →</a>')
        doc.append('    </div>')

    doc.append('    <nav class="range-tabs" aria-label="时间段">')
    for k in ranges.RANGE_ORDER:
        current = ' aria-current="page"' if k == key else ""
        doc.append(f'      <a class="range-tab" href="?range={k}" data-range="{k}"{current}>{_e(ranges.RANGE_LABELS[k])}</a>')
    doc.append('    </nav>')

    doc.append(f'    <div id="view-overview">{render_overview(rng, key)}</div>')
    doc.append(render_pool(ctx))
    doc.append(f'    <div id="view-main">{render_main(rng, member_meta)}</div>')
    doc.append(render_heatmap(ctx["heatmap"], ctx["today"].isoformat()))

    payload = {
        "range": key,
        "order": [[k, ranges.RANGE_LABELS[k]] for k in ranges.RANGE_ORDER],
        "members": [member_meta[m["id"]] for m in ctx["members"]],
        "ranges": ctx["ranges"],
        "palette": ranges.SERIES_PALETTE,
    }
    doc.append(f'    <script type="application/json" id="dash-data">{embed_json(payload)}</script>')
    doc.append('  </div>')
    doc.append(f'  <script src="/static/dashboard.js?v={dashboard_js_version()}" defer></script>')
    doc.append('</body>')
    doc.append('</html>')
    return "\n".join(doc)
