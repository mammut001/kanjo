"""Unit tests for Kanjo TUI (`kanjo usage` / `kanjo top`)."""

try:
    import curses
except ImportError:  # Windows has no _curses; guard so the module still imports.
    curses = None
from datetime import datetime, timezone, timedelta
import io
import json
import os
import tempfile
import time
import unittest
import unicodedata
from typing import List
from unittest import mock
from zoneinfo import ZoneInfo

from kanjo.tui.model import (
    AntigravityAccountRow, AntigravityAccountsSection, FilteredData,
    QuotaLevel, RANGE_TABS, TimeRange, VIEW_MODES, ViewMode,
    agent_color, available_view_modes, build_agent_rows,
    build_antigravity_accounts_section, build_day_rows, build_model_rows,
    build_project_detail, build_project_footer_rows, build_project_rows,
    build_subscription_meters, build_total_view_model, compute_30d_sparkline,
    compute_8w_strip, ensure_aware, filter_report, format_money,
    format_month_day_time, format_reset_countdown, format_tokens,
    get_accounts_window, get_tz, heat_level, parse_iso_dt, parse_tokens_str,
    quota_level
)
from kanjo.tui.render import (
    Canvas, Cell, SELECTED_ROW_BG, Style, TUIState, render_ui,
    char_width, hit_box_at, str_width, truncate_str, wrap_display
)
from kanjo.tui.static import canvas_to_ansi, render_static_snapshot
from kanjo.tui.term import (
    BUTTON1_BITS, MOUSE_WHEEL_ROWS, WHEEL_DOWN_BITS, WHEEL_UP_BITS,
    apply_mouse_event, mouse_click_key, mouse_event_kind, run_curses_tui,
    visible_row_count
)
from kanjo.tui.i18n import resolve_lang, t
from kanjo.antigravity_accounts import compute_antigravity_accounts_window
from kanjo.sources.base import Message, Session
from kanjo import cli

MOUSE_KEY = getattr(curses, "KEY_MOUSE", 409)


def load_fixture_doc() -> dict:
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "export_sample.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_sample_fixture() -> dict:
    fixture_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ui", "fixtures", "sample.json"))
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


class FakeStdscr:
    """Mock curses stdscr for headless testing."""
    def __init__(self, width: int = 80, height: int = 24, keys=None):
        self.w = width
        self.h = height
        self.keys = list(keys or [ord("q")])
        self.captured = []
        self.frames = [0]

    def getmaxyx(self):
        return (self.h, self.w)

    def timeout(self, ms):
        pass

    def keypad(self, flag):
        pass

    def erase(self):
        # Frame boundary: the TUI clears the screen before every redraw.
        self.frames.append(len(self.captured))

    def addstr(self, *args):
        self.captured.append(args)

    def insch(self, *args):
        pass

    def noutrefresh(self):
        pass

    def getch(self):
        if self.keys:
            return self.keys.pop(0)
        return ord("q")


class FakeMouseStdscr(FakeStdscr):
    """FakeStdscr that also reports curses mouse events.

    ``events`` holds ``(x, y, bstate)`` tuples. Each ``getch`` that reports
    ``KEY_MOUSE`` hands the next event to the reader, whether or not the TUI
    asks for it, so a disabled mouse never spins the loop.
    """

    def __init__(self, width: int = 80, height: int = 24, events=None, keys=None):
        super().__init__(width=width, height=height, keys=keys)
        self.events = list(events or [])
        self.pending = None

    def getch(self):
        if self.events:
            self.pending = self.events.pop(0)
            return MOUSE_KEY
        self.pending = None
        return super().getch()

    def read_mouse(self):
        event = self.pending
        self.pending = None
        return event


def mouse_reader(scr):
    """Read the mouse events of a :class:`FakeMouseStdscr`."""
    return scr.read_mouse


def screen_grid(scr) -> dict:
    """``(y, x) -> (char, attrs)`` of the last frame a fake stdscr drew."""
    grid = {}
    start = scr.frames[-1] if getattr(scr, "frames", None) else 0
    for call in scr.captured[start:]:
        if len(call) < 3:
            continue
        y, x, text = call[0], call[1], call[2]
        attrs = call[3] if len(call) > 3 else 0
        for offset, ch in enumerate(text):
            grid[(y, x + offset)] = (ch, attrs)
    return grid


def screen_text(scr) -> str:
    """Rebuild the text of the last frame a fake stdscr drew."""
    grid = screen_grid(scr)
    if not grid:
        return ""
    width = max(x for _y, x in grid) + 1
    height = max(y for y, _x in grid) + 1
    lines = []
    for y in range(height):
        lines.append("".join(grid.get((y, x), (" ", 0))[0] for x in range(width)).rstrip())
    return "\n".join(lines)


def screen_frames(scr) -> List[str]:
    """Text of every frame a fake stdscr drew, oldest first."""
    bounds = list(getattr(scr, "frames", None) or [0]) + [len(scr.captured)]
    texts = []
    for start, end in zip(bounds, bounds[1:]):
        grid = {}
        for call in scr.captured[start:end]:
            if len(call) < 3:
                continue
            y, x, text = call[0], call[1], call[2]
            for offset, ch in enumerate(text):
                grid[(y, x + offset)] = ch
        if not grid:
            continue
        width = max(x for _y, x in grid) + 1
        height = max(y for y, _x in grid) + 1
        texts.append("\n".join(
            "".join(grid.get((y, x), " ") for x in range(width)).rstrip()
            for y in range(height)))
    return texts


def reverse_cells(scr) -> set:
    """Coordinates the last frame drew in reverse video (the selected row)."""
    return {pos for pos, (_ch, attrs) in screen_grid(scr).items()
            if attrs & curses.A_REVERSE}


class TUIModelTest(unittest.TestCase):
    def test_agent_colours_readable_on_black(self):
        """Every agent colour must stay visible on a dark terminal, both in the
        256-colour mapping and in the 8-colour fallback (not dark blue)."""
        from kanjo.tui.model import AGENT_COLORS
        from kanjo.tui.static import rgb_to_256

        levels = [0, 95, 135, 175, 215, 255]

        def contrast_on_black(rgb):
            idx = rgb_to_256(*rgb) - 16
            cube = (levels[idx // 36], levels[(idx // 6) % 6], levels[idx % 6])

            def lin(v):
                v = v / 255
                return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
            lum = 0.2126 * lin(cube[0]) + 0.7152 * lin(cube[1]) + 0.0722 * lin(cube[2])
            return (lum + 0.05) / 0.05

        for name, rgb in AGENT_COLORS.items():
            # devin and openclaw sit right at ~3:1; the floor catches the rest.
            self.assertGreaterEqual(contrast_on_black(rgb), 2.9, name)

        # 8-colour fallback: the bitmask of the RGB channels; blue-only (4) is dark.
        cc = AGENT_COLORS["commandcode"]
        self.assertNotEqual(sum(1 << k for k, v in enumerate(cc) if v > 128), 4)

    def test_compact_number_formats(self):
        # format_tokens
        self.assertEqual(format_tokens(0), "0")
        self.assertEqual(format_tokens(500), "500")
        self.assertEqual(format_tokens(4500), "4.5k")
        self.assertEqual(format_tokens(50000), "50k")
        self.assertEqual(format_tokens(266200000), "266.2M")
        self.assertEqual(format_tokens(1210000000), "1.21B")
        self.assertEqual(format_tokens(10500000000), "10.5B")
        self.assertEqual(format_tokens(-2500), "-2.5k")

        # format_money
        self.assertEqual(format_money(275.99), "$275.99")
        self.assertEqual(format_money(1244.2), "$1,244.20")
        self.assertEqual(format_money(0.0), "$0.00")
        self.assertEqual(format_money(-15.5), "-$15.50")

    def test_quota_level_thresholds(self):
        self.assertIsNone(quota_level(None))
        self.assertEqual(quota_level(0.0), QuotaLevel.NORMAL)
        self.assertEqual(quota_level(50.0), QuotaLevel.NORMAL)
        self.assertEqual(quota_level(79.9), QuotaLevel.NORMAL)
        self.assertEqual(quota_level(80.0), QuotaLevel.WARNING)
        self.assertEqual(quota_level(94.9), QuotaLevel.WARNING)
        self.assertEqual(quota_level(95.0), QuotaLevel.CRITICAL)
        self.assertEqual(quota_level(100.0), QuotaLevel.CRITICAL)

    def test_reset_countdown_text(self):
        tz = timezone.utc
        now = datetime(2026, 11, 13, 12, 0, 0, tzinfo=tz)

        # None
        self.assertEqual(format_reset_countdown(None, now, tz), "—")

        # Past
        past = now - timedelta(minutes=5)
        self.assertEqual(format_reset_countdown(past, now, tz), "window ended")

        # Under 60m
        future_35m = now + timedelta(minutes=35)
        self.assertEqual(format_reset_countdown(future_35m, now, tz), "resets in 35m")

        # Same day (>60m, <24h)
        future_same_day = now + timedelta(hours=6, minutes=40)
        self.assertEqual(format_reset_countdown(future_same_day, now, tz), "resets 18:40")

        # Over 24 hours
        future_2d4h = now + timedelta(days=2, hours=4)
        self.assertEqual(format_reset_countdown(future_2d4h, now, tz), "resets in 2d 4h")

    def test_accounts_window_selection(self):
        now = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Antigravity quota window
        qw = {
            "antigravity": {
                "weekly_resets_at": "2026-11-15T16:55:00Z",
                "weekly_window_hours": 168
            }
        }
        start, kind, label = get_accounts_window(qw, {}, now=now, tz_name="UTC")
        self.assertEqual(kind, "quota_week")
        self.assertIn("this quota week", label)
        self.assertIn("since Nov 8 16:55", label)

        # 2. Antigravity billing cycle
        subs = {
            "antigravity": {
                "cycle_start": "2026-11-01T00:00:00Z"
            }
        }
        start, kind, label = get_accounts_window({}, subs, now=now, tz_name="UTC")
        self.assertEqual(kind, "billing_cycle")
        self.assertIn("this billing cycle", label)
        self.assertIn("since Nov 1 00:00", label)

        # 3. Fallback: last 7 days
        start, kind, label = get_accounts_window({}, {}, now=now, tz_name="UTC")
        self.assertEqual(kind, "last_7d")
        self.assertIn("last 7 days", label)
        self.assertIn("since Nov 6 12:00", label)

    def test_range_filtering_on_fixture_doc(self):
        doc = load_fixture_doc()
        now = parse_iso_dt(doc["generated_at"])

        # Range: ALL
        f_all = filter_report(doc, TimeRange.ALL, now=now)
        self.assertAlmostEqual(f_all.total_cost, doc["totals"]["cost"], places=2)
        self.assertEqual(f_all.total_sessions, doc["totals"]["sessions"])
        self.assertEqual(f_all.projects_count, len(doc["projects"]))

        # Range: TODAY
        f_today = filter_report(doc, TimeRange.TODAY, now=now)
        self.assertGreater(f_today.total_cost, 0)
        self.assertLessEqual(f_today.total_cost, f_all.total_cost)

        # Range: 7d
        f_7d = filter_report(doc, TimeRange.DAYS_7, now=now)
        self.assertGreater(f_7d.total_cost, f_today.total_cost)
        self.assertLessEqual(f_7d.total_cost, f_all.total_cost)

        # Range: 30d
        f_30d = filter_report(doc, TimeRange.DAYS_30, now=now)
        self.assertGreater(f_30d.total_cost, f_7d.total_cost)
        self.assertLessEqual(f_30d.total_cost, f_all.total_cost)

        # Range: RESET
        f_reset = filter_report(doc, TimeRange.RESET, now=now)
        self.assertGreater(f_reset.total_cost, 0)

        # Range: CYCLE
        f_cycle = filter_report(doc, TimeRange.CYCLE, now=now)
        self.assertGreater(f_cycle.total_cost, 0)

    def test_filter_and_sort_orders(self):
        doc = load_fixture_doc()
        now = parse_iso_dt(doc["generated_at"])
        tz = get_tz(doc)
        filtered = filter_report(doc, TimeRange.ALL, now=now)

        # Build project rows without query
        rows = build_project_rows(filtered, now, tz)
        self.assertEqual(len(rows), len(doc["projects"]))

        # Filter query: case-insensitive
        filtered_rows = build_project_rows(filtered, now, tz, filter_query="focusapp")
        self.assertEqual(len(filtered_rows), 1)
        self.assertIn("FocusApp", filtered_rows[0].name)

        # Empty match
        no_match = build_project_rows(filtered, now, tz, filter_query="nonexistent_xyz")
        self.assertEqual(len(no_match), 0)

    def test_heat_strip_and_sparkline(self):
        doc = load_fixture_doc()
        now = parse_iso_dt(doc["generated_at"])
        tz = get_tz(doc)
        p0 = doc["projects"][0]

        # 8W Heat Strip
        strip = compute_8w_strip(p0.get("by_day", []), now, tz)
        self.assertEqual(len(strip), 8)
        for char, ag in strip:
            self.assertEqual(len(char), 1)

        # 30-day sparkline
        spark, peak = compute_30d_sparkline(p0.get("by_day", []), now, tz)
        self.assertEqual(len(spark), 30)
        self.assertGreater(peak, 0.0)

    def test_antigravity_accounts_builder(self):
        doc = load_fixture_doc()
        now = parse_iso_dt(doc["generated_at"])
        acc_data = [
            {"account": "alice@gmail.com", "tokens": 1210000000, "cost": 45.20},
            {"account": "bob@gmail.com", "tokens": 340000000, "cost": 12.10},
            {"account": "unknown", "tokens": 15000000, "cost": 0.55},
        ]
        sec = build_antigravity_accounts_section(
            doc, now=now, antigravity_data=acc_data, current_account="alice@gmail.com"
        )
        self.assertIsNotNone(sec)
        self.assertIn("Antigravity accounts", sec.header_label)
        self.assertEqual(len(sec.rows), 3)
        # Alice is current
        self.assertTrue(sec.rows[0].is_current)
        self.assertEqual(sec.rows[0].tokens_str, "1.21B")
        self.assertEqual(sec.rows[0].cost_str, "$45.20")
        # Bob is second
        self.assertFalse(sec.rows[1].is_current)
        # Unattributed is last
        self.assertTrue(sec.rows[2].is_unattributed)
        self.assertEqual(sec.rows[2].email, "unattributed")

    def test_sample_fixture_timezone_awareness_and_crash_fix(self):
        """Item 1: Ensure ui/fixtures/sample.json does not crash across all ranges."""
        doc = load_sample_fixture()
        tz = get_tz(doc)
        now_aware = parse_iso_dt(doc.get("generated_at"), default_tz=tz)
        now_naive = datetime(2026, 11, 13, 12, 0, 0)

        # Test both offset-aware and offset-naive now across all 6 ranges
        for now in (now_aware, now_naive):
            for tr in [TimeRange.ALL, TimeRange.TODAY, TimeRange.DAYS_7, TimeRange.DAYS_30, TimeRange.RESET, TimeRange.CYCLE]:
                # filter_report
                filtered = filter_report(doc, tr, now=now)
                self.assertIsNotNone(filtered)
                self.assertGreaterEqual(filtered.total_cost, 0.0)

                # build_subscription_meters (which triggered the supervisor crash on TimeRange.CYCLE)
                meters = build_subscription_meters(doc, now=now)
                self.assertIsInstance(meters, list)

                # static snapshot
                snapshot = render_static_snapshot(doc, width=80, time_range=tr, now=now, no_color=True)
                self.assertIn("Kanjo", snapshot)
                self.assertIn("Total", snapshot)

    def test_model_tolerance_missing_and_corrupt_fields(self):
        """Ensure no exception escapes model or render for empty or partially missing docs."""
        test_docs = [
            {},
            {"timezone": None},
            {"timezone": "Invalid/Timezone/Name_123"},
            {"projects": None, "totals": None, "subscriptions": None, "quota_windows": None},
            {"projects": [{"name": None, "cost": None, "tokens": None, "by_day": None, "by_agent": None}]},
            {"totals": {"cost": None, "tokens": None, "sessions": None}, "projects": []},
            {"subscriptions": {"antigravity": None, "claude": {"monthly_price_usd": "invalid", "cycle_start": None}}},
            {"quota_windows": {"antigravity": {"weekly_resets_at": "bad-date", "weekly_window_hours": None}}},
        ]
        for doc in test_docs:
            tz = get_tz(doc)
            now = datetime.now(tz)
            for tr in [TimeRange.ALL, TimeRange.TODAY, TimeRange.CYCLE]:
                filtered = filter_report(doc, tr, now=now)
                total_vm = build_total_view_model(filtered)
                meters = build_subscription_meters(doc, now=now)
                acc_sec = build_antigravity_accounts_section(doc, now=now)
                p_rows = build_project_rows(filtered, now, tz)
                p_footers = build_project_footer_rows(filtered, now, tz)
                m_rows = build_model_rows(filtered)
                a_rows = build_agent_rows(filtered)
                d_rows = build_day_rows(filtered)

                canvas = Canvas(80, 24)
                state = TUIState(version="0.9.0", time_range=tr)
                render_ui(
                    canvas, state=state, filtered=filtered, total_vm=total_vm,
                    meters=meters, accounts_section=acc_sec, project_rows=p_rows,
                    project_footers=p_footers, model_rows=m_rows, agent_rows=a_rows,
                    day_rows=d_rows, static_mode=True
                )
                self.assertGreater(len(canvas.get_line_text(0)), 0)

    def test_antigravity_accounts_quota_week_paths(self):
        """Item 5: Antigravity accounts panel reflects quota week / billing cycle / last 7 days."""
        # Path 1: Top-level antigravity_accounts object in export doc
        doc_qw = {
            "antigravity_accounts": {
                "window_start": "2026-11-08T16:55:00Z",
                "window_kind": "quota_week",
                "current": "current@example.com",
                "accounts": [
                    {"email": "current@example.com", "tokens": 5000000, "cost_usd": 25.0, "messages": 10},
                    {"email": "other@example.com", "tokens": 1000000, "cost_usd": 5.0, "messages": 2},
                ],
                "unknown": {"tokens": 20000, "cost_usd": 0.10}
            }
        }
        sec_qw = build_antigravity_accounts_section(doc_qw)
        self.assertIsNotNone(sec_qw)
        self.assertIn("this quota week", sec_qw.header_label)
        self.assertEqual(len(sec_qw.rows), 3)  # current, other, unattributed
        self.assertTrue(sec_qw.rows[0].is_current)
        self.assertEqual(sec_qw.rows[0].email, "current@example.com")
        self.assertEqual(sec_qw.rows[0].tokens_str, "5M")
        self.assertEqual(sec_qw.rows[0].cost_str, "$25.00")
        self.assertTrue(sec_qw.rows[2].is_unattributed)
        self.assertEqual(sec_qw.rows[2].tokens_str, "20k")

        # Test billing_cycle title
        doc_bc = {
            "antigravity_accounts": {
                "window_start": "2026-11-01T00:00:00Z",
                "window_kind": "billing_cycle",
                "current": None,
                "accounts": [{"email": "user@example.com", "tokens": 1000, "cost_usd": 0.05}],
                "unknown": {"tokens": 0, "cost_usd": 0.0}
            }
        }
        sec_bc = build_antigravity_accounts_section(doc_bc)
        self.assertIn("this billing cycle", sec_bc.header_label)

        # Test last_7_days title
        doc_7d = {
            "antigravity_accounts": {
                "window_start": "2026-11-06T12:00:00Z",
                "window_kind": "last_7_days",
                "current": None,
                "accounts": [{"email": "user@example.com", "tokens": 1000, "cost_usd": 0.05}],
                "unknown": {"tokens": 0, "cost_usd": 0.0}
            }
        }
        sec_7d = build_antigravity_accounts_section(doc_7d)
        self.assertIn("last 7 days", sec_7d.header_label)

        # Path 2: Locally computed via compute_antigravity_accounts_window
        now = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
        doc_calc = {
            "quota_windows": {
                "antigravity": {
                    "weekly_resets_at": "2026-11-15T16:55:00Z",
                    "weekly_window_hours": 168
                }
            }
        }
        # window_start is Nov 8 16:55:00 UTC (1794156900 ts)
        # Message before window: 2026-11-07 12:00:00 (1794052800) -> excluded
        # Message inside window: 2026-11-09 12:00:00 (1794225600) -> included
        # Message inside window unattributed: 2026-11-10 12:00:00 (1794312000) -> included in unknown
        ts_before = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        ts_inside = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        ts_unatt = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc).timestamp()

        m_old = Message(ts=ts_before, model="gemini-2.5-pro", input=500000, output=100000, account="alice@gmail.com")
        m_new = Message(ts=ts_inside, model="gemini-2.5-pro", input=200000, output=50000, account="alice@gmail.com")
        m_unk = Message(ts=ts_unatt, model="gemini-2.5-pro", input=10000, output=2000, account=None)
        s = Session(id="s1", agent="antigravity", file="f.log", messages=[m_old, m_new, m_unk])

        computed = compute_antigravity_accounts_window([s], doc_calc, now=now, current_account="alice@gmail.com")
        self.assertEqual(computed["window_kind"], "quota_week")
        self.assertEqual(computed["current"], "alice@gmail.com")
        # Alice should have 250k tokens (from m_new only, excluding m_old)
        self.assertEqual(len(computed["accounts"]), 1)
        self.assertEqual(computed["accounts"][0]["tokens"], 250000)
        self.assertEqual(computed["unknown"]["tokens"], 12000)

        # Build section with computed dict
        sec_computed = build_antigravity_accounts_section(doc_calc, now=now, antigravity_data=computed)
        self.assertIsNotNone(sec_computed)
        self.assertIn("this quota week", sec_computed.header_label)
        self.assertEqual(len(sec_computed.rows), 2)
        self.assertTrue(sec_computed.rows[0].is_current)
        self.assertEqual(sec_computed.rows[0].tokens_str, "250k")


class TUIRenderTest(unittest.TestCase):
    def setUp(self):
        self.doc = load_fixture_doc()
        self.now = parse_iso_dt(self.doc["generated_at"])
        self.tz = get_tz(self.doc)
        self.filtered = filter_report(self.doc, TimeRange.ALL, now=self.now)
        self.total_vm = build_total_view_model(self.filtered)
        self.meters = build_subscription_meters(self.doc, now=self.now)
        self.accounts_sec = build_antigravity_accounts_section(self.doc, now=self.now)
        self.proj_rows = build_project_rows(self.filtered, self.now, self.tz)
        self.proj_footers = build_project_footer_rows(self.filtered, self.now, self.tz)
        self.model_rows = build_model_rows(self.filtered)
        self.agent_rows = build_agent_rows(self.filtered)
        self.day_rows = build_day_rows(self.filtered)
        self.state = TUIState(version="0.9.0", last_refresh_time="14:54:29")

    def test_render_canvas_80x24(self):
        w, h = 80, 24
        canvas = Canvas(w, h)
        render_ui(
            canvas, self.state, self.filtered, self.total_vm, self.meters,
            self.accounts_sec, self.proj_rows, self.proj_footers,
            self.model_rows, self.agent_rows, self.day_rows
        )

        # 1. No line longer than width
        for y in range(h):
            line = canvas.get_line_text(y)
            width = str_width(line)
            self.assertLessEqual(width, w, f"Line {y} width {width} exceeds {w}: {repr(line)}")

        # 2. Header tabs on line 0
        line0 = canvas.get_line_text(0)
        self.assertIn("Kanjo 0.9.0", line0)
        self.assertIn("All", line0)
        self.assertIn("Today", line0)
        self.assertIn("7d", line0)
        self.assertIn("30d", line0)
        self.assertIn("Since reset", line0)
        self.assertIn("Cycle", line0)

        # 3. Quota meter row with percentage
        all_text = "\n".join(canvas.get_line_text(y) for y in range(h))
        self.assertIn("57%", all_text)

        # 4. F-key bar on the last line (y = 23)
        last_line = canvas.get_line_text(h - 1)
        self.assertIn("F1", last_line)
        self.assertIn("Help", last_line)
        self.assertIn("F2", last_line)
        self.assertIn("Range", last_line)
        self.assertIn("F3", last_line)
        self.assertIn("View", last_line)
        self.assertIn("F4", last_line)
        self.assertIn("Filter", last_line)
        self.assertIn("F5", last_line)
        self.assertIn("Refresh", last_line)
        self.assertIn("F6", last_line)
        self.assertIn("Sort", last_line)
        self.assertIn("F10", last_line)
        self.assertIn("Quit", last_line)

    def test_render_canvas_140x40(self):
        w, h = 140, 40
        canvas = Canvas(w, h)
        render_ui(
            canvas, self.state, self.filtered, self.total_vm, self.meters,
            self.accounts_sec, self.proj_rows, self.proj_footers,
            self.model_rows, self.agent_rows, self.day_rows
        )

        for y in range(h):
            line = canvas.get_line_text(y)
            width = str_width(line)
            self.assertLessEqual(width, w, f"Line {y} width {width} exceeds {w}: {repr(line)}")

        line0 = canvas.get_line_text(0)
        self.assertIn("Kanjo 0.9.0", line0)
        last_line = canvas.get_line_text(h - 1)
        self.assertIn("F10", last_line)

    def _render_sample_canvas(self, w, h, show_help=False):
        doc = load_sample_fixture()
        tz = get_tz(doc)
        now = parse_iso_dt(doc.get("generated_at"), default_tz=tz)
        filtered = filter_report(doc, TimeRange.ALL, now=now)
        p_rows = build_project_rows(filtered, now, tz)
        state = TUIState(version="0.5.4", show_help=show_help)
        canvas = Canvas(w, h)
        render_ui(
            canvas, state, filtered, build_total_view_model(filtered),
            build_subscription_meters(doc, now=now),
            build_antigravity_accounts_section(doc, now=now),
            p_rows, build_project_footer_rows(filtered, now, tz),
            build_model_rows(filtered), build_agent_rows(filtered),
            build_day_rows(filtered)
        )
        return canvas, p_rows

    def test_layout_round_sample_sizes(self):
        for w, h in ((80, 24), (100, 30), (120, 40), (200, 50)):
            canvas, p_rows = self._render_sample_canvas(w, h)
            lines = [canvas.get_line_text(y) for y in range(h)]

            for y, line in enumerate(lines):
                self.assertLessEqual(str_width(line), w,
                                     f"Line {y} wider than {w} at {w}x{h}: {line!r}")

            header_y = next(y for y, line in enumerate(lines) if "PROJECT" in line)
            names = {r.name for r in p_rows}
            row_count = sum(
                1 for line in lines[header_y + 1:]
                if any(line.startswith(name) for name in names)
            )
            if (w, h) == (80, 24):
                self.assertGreaterEqual(
                    row_count, 5,
                    f"Expected >=5 project rows at 80x24, got {row_count}"
                )

            for line in lines:
                for idx, ch in enumerate(line):
                    if ch == "[" and idx > 0:
                        self.assertEqual(
                            line[idx - 1], " ",
                            f"Meter label touches '[' at {w}x{h}: {line!r}"
                        )

            if w >= 110:
                self.assertTrue(
                    any(line.count("●") >= 2 or line.count("[") >= 2 for line in lines),
                    f"Expected two-column meter layout at {w}x{h}"
                )

    def test_help_overlay_fits_sample_sizes(self):
        for w, h in ((80, 24), (100, 30), (120, 40), (200, 50)):
            canvas, _ = self._render_sample_canvas(w, h, show_help=True)
            lines = [canvas.get_line_text(y) for y in range(h)]

            for y, line in enumerate(lines):
                self.assertLessEqual(str_width(line), w,
                                     f"Help line {y} wider than {w} at {w}x{h}: {line!r}")

            top = next(y for y, line in enumerate(lines) if "Help & Shortcuts" in line)
            left = lines[top].index("┌")
            right = lines[top].rindex("┐")
            bottom = next(y for y in range(top, h) if lines[y][left] == "└")

            for y in range(top, bottom + 1):
                stripped = lines[y].rstrip()
                if y in (top, bottom):
                    self.assertIn(stripped[-1], "┐┘", f"Bad help border at {w}x{h}: {stripped!r}")
                else:
                    self.assertEqual(
                        lines[y][right], "│",
                        f"Help content overflowed border at {w}x{h} line {y}: {lines[y]!r}"
                    )
                    self.assertTrue(stripped.endswith("│"),
                                    f"Help line does not end with border at {w}x{h}: {stripped!r}")

    def test_wide_cjk_characters(self):
        self.assertEqual(char_width("中"), 2)
        self.assertEqual(char_width("文"), 2)
        self.assertEqual(char_width("a"), 1)
        self.assertEqual(char_width("1"), 1)
        self.assertEqual(str_width("中文字符"), 8)
        self.assertEqual(str_width("Hello中文"), 9)

        # Truncation with CJK
        s = "测试项目名称 FocusApp"
        trunc = truncate_str(s, 10)
        self.assertLessEqual(str_width(trunc), 10)

        # Canvas writing with CJK
        canvas = Canvas(20, 2)
        canvas.draw_text(0, 0, "测试中文字符")
        self.assertEqual(str_width(canvas.get_line_text(0).strip()), 12)

    def test_tiny_terminal_message(self):
        canvas = Canvas(40, 10)  # Too small (< 60x15)
        render_ui(
            canvas, self.state, self.filtered, self.total_vm, self.meters,
            self.accounts_sec, self.proj_rows, self.proj_footers,
            self.model_rows, self.agent_rows, self.day_rows
        )
        line0 = canvas.get_line_text(0)
        self.assertIn("Terminal too small", line0)
        self.assertIn("60x15", line0)

    def test_detail_pane_rendering(self):
        state = TUIState(version="0.9.0", detail_open=True)
        p0 = self.filtered.projects[0]
        detail_vm = build_project_detail(p0, self.now, self.tz)

        canvas = Canvas(100, 30)
        render_ui(
            canvas, state, self.filtered, self.total_vm, self.meters,
            self.accounts_sec, self.proj_rows, self.proj_footers,
            self.model_rows, self.agent_rows, self.day_rows,
            detail_vm=detail_vm
        )
        all_text = "\n".join(canvas.get_line_text(y) for y in range(30))
        self.assertIn(f"Project: {detail_vm.name}", all_text)
        self.assertIn("By Agent:", all_text)
        self.assertIn("By Model:", all_text)
        self.assertIn("Close", all_text)

    def test_detail_pane_background_is_solid_inside_border(self):
        from kanjo.tui.render import DETAIL_PANE_BG
        state = TUIState(version="0.9.0", detail_open=True)
        p0 = self.filtered.projects[0]
        detail_vm = build_project_detail(p0, self.now, self.tz)

        canvas = Canvas(100, 30)
        render_ui(
            canvas, state, self.filtered, self.total_vm, self.meters,
            self.accounts_sec, self.proj_rows, self.proj_footers,
            self.model_rows, self.agent_rows, self.day_rows,
            detail_vm=detail_vm
        )
        # Locate the box by its top-left and bottom-right corners.
        top_y = next(y for y in range(canvas.height) if "┌" in canvas.get_line_text(y))
        x0 = canvas.get_line_text(top_y).index("┌")
        x1 = canvas.get_line_text(top_y).index("┐", x0)
        bottom_y = next(y for y in range(top_y + 1, canvas.height)
                        if canvas.get_line_text(y)[x0] == "└")
        self.assertGreater(x1 - x0, 10)
        self.assertGreater(bottom_y - top_y, 5)

        # Every cell inside the border (text, gaps, blank and header rows)
        # carries the same pane background.
        for y in range(top_y + 1, bottom_y):
            for x in range(x0 + 1, x1):
                cell = canvas.grid[y][x]
                self.assertEqual(
                    cell.style.bg, DETAIL_PANE_BG,
                    f"cell ({x},{y}) {cell.char!r} has bg {cell.style.bg!r}",
                )

    def test_help_overlay_rendering(self):
        state = TUIState(version="0.9.0", show_help=True)
        canvas = Canvas(100, 30)
        render_ui(
            canvas, state, self.filtered, self.total_vm, self.meters,
            self.accounts_sec, self.proj_rows, self.proj_footers,
            self.model_rows, self.agent_rows, self.day_rows
        )
        all_text = "\n".join(canvas.get_line_text(y) for y in range(30))
        self.assertIn("Help & Shortcuts", all_text)
        self.assertIn("Time Range", all_text)
        self.assertIn("Navigation", all_text)

    def test_start_fast_loading_state(self):
        """Item 4: Fast start shows Loading… immediately without blocking."""
        canvas = Canvas(80, 24)
        state = TUIState(version="0.9.0", is_scanning=True)
        render_ui(canvas, state=state, filtered=None, static_mode=False)

        all_text = "\n".join(canvas.get_line_text(y) for y in range(24))
        self.assertIn("Loading…", all_text)

        last_line = canvas.get_line_text(23)
        self.assertIn("F1", last_line)
        self.assertIn("F10", last_line)

    def _render_projects(self, w=120, h=40, selected_index=0, no_color=False):
        state = TUIState(
            version="0.9.0", selected_index=selected_index, no_color=no_color
        )
        canvas = Canvas(w, h)
        render_ui(
            canvas, state, self.filtered, self.total_vm, self.meters,
            self.accounts_sec, self.proj_rows, self.proj_footers,
            self.model_rows, self.agent_rows, self.day_rows,
            static_mode=False,
        )
        return canvas, state

    def _project_row_y(self, canvas, name):
        header_y = next(
            y for y in range(canvas.height)
            if "PROJECT" in canvas.get_line_text(y)
        )
        return next(
            y for y in range(header_y + 1, canvas.height)
            if canvas.get_line_text(y).startswith(name)
        )

    def test_style_model_never_combines_colour_with_reverse(self):
        normalized = Style(inverse=True, fg="red").normalized()
        self.assertFalse(normalized.inverse)
        self.assertIsNone(normalized.fg)

        for no_color in (False, True):
            canvas, _ = self._render_projects(no_color=no_color)
            for y in range(canvas.height):
                for x in range(canvas.width):
                    style = canvas.grid[y][x].style
                    self.assertFalse(
                        style.inverse and (style.fg is not None or style.bg is not None),
                        f"cell ({x},{y}) combines colour and reverse: {style!r}",
                    )

    def test_fkey_bar_uses_explicit_colours(self):
        canvas, _ = self._render_projects()
        y = canvas.height - 1
        f_items = [
            ("F1", "Help"), ("F2", "Range"), ("F3", "View"),
            ("F4", "Filter"), ("F5", "Refresh"), ("F6", "Sort"),
            ("F7", "Meters"), ("F10", "Quit"),
        ]
        x = 0
        for key_lbl, name_lbl in f_items:
            key_style = canvas.grid[y][x].style
            self.assertFalse(key_style.inverse)
            self.assertIsNone(key_style.bg)
            for i in range(len(name_lbl) + 1):
                style = canvas.grid[y][x + len(key_lbl) + i].style
                self.assertFalse(style.inverse)
                self.assertEqual(style.fg, "black")
                self.assertEqual(style.bg, "cyan")
            x += len(key_lbl) + len(name_lbl) + 1

    def test_heat_strip_keeps_agent_colours_without_reverse(self):
        w = 120
        canvas, _ = self._render_projects(w=w, selected_index=1)
        proj_w = max(16, w - 59)
        heat_x = proj_w + 51
        for index in (0, 1):
            row = self.proj_rows[index]
            y = self._project_row_y(canvas, row.name)
            for i, (_ch, dom_ag) in enumerate(row.heat_strip):
                style = canvas.grid[y][heat_x + i].style
                self.assertFalse(style.inverse)
                if dom_ag:
                    self.assertEqual(style.fg, agent_color(dom_ag))
                if index == 1:
                    self.assertEqual(style.bg, SELECTED_ROW_BG)
                else:
                    self.assertIsNone(style.bg)

    def test_selected_row_agent_dots_keep_agent_colour(self):
        w = 120
        canvas, _ = self._render_projects(w=w, selected_index=1)
        proj_w = max(16, w - 59)
        dots_x = proj_w + 30
        row = self.proj_rows[1]
        y = self._project_row_y(canvas, row.name)

        row_style = canvas.grid[y][0].style
        self.assertFalse(row_style.inverse)
        self.assertEqual(row_style.bg, SELECTED_ROW_BG)

        for i, ag in enumerate(row.agents[:6]):
            style = canvas.grid[y][dots_x + i].style
            self.assertFalse(style.inverse)
            self.assertEqual(style.fg, agent_color(ag))
            self.assertEqual(style.bg, SELECTED_ROW_BG)

    def test_matrix_static_and_curses_canvas_robustness(self):
        """Item 3: Matrix test for BOTH sample.json and export_sample.json:
        every range × every view × widths (60, 80, 120, 200) × heights (15, 24, 50).
        Asserts no exception, no line wider than width (str_width), F-key bar on last line of curses canvas."""
        f_sample = load_sample_fixture()
        f_export = load_fixture_doc()

        for doc in (f_sample, f_export):
            tz = get_tz(doc)
            now = parse_iso_dt(doc.get("generated_at"), default_tz=tz)
            for tr in [TimeRange.ALL, TimeRange.TODAY, TimeRange.DAYS_7, TimeRange.DAYS_30, TimeRange.RESET, TimeRange.CYCLE]:
                filtered = filter_report(doc, tr, now=now)
                total_vm = build_total_view_model(filtered)
                meters = build_subscription_meters(doc, now=now)
                acc_sec = build_antigravity_accounts_section(doc, now=now)
                p_rows = build_project_rows(filtered, now, tz)
                p_footers = build_project_footer_rows(filtered, now, tz)
                m_rows = build_model_rows(filtered)
                a_rows = build_agent_rows(filtered)
                d_rows = build_day_rows(filtered)

                for vm in [ViewMode.PROJECTS, ViewMode.MODELS, ViewMode.AGENTS, ViewMode.DAYS]:
                    for w in (60, 80, 120, 200):
                        for h in (15, 24, 50):
                            # 1. Static snapshot
                            out = render_static_snapshot(
                                doc, width=w, height=h, no_color=True, now=now,
                                time_range=tr, view_mode=vm
                            )
                            for line in out.splitlines():
                                self.assertLessEqual(
                                    str_width(line), w,
                                    f"Static line {repr(line)} width {str_width(line)} > {w} (range={tr}, view={vm}, h={h})"
                                )

                            # 2. Curses canvas render
                            canvas = Canvas(w, h)
                            state = TUIState(version="0.9.0", time_range=tr, view_mode=vm)
                            render_ui(
                                canvas, state=state, filtered=filtered, total_vm=total_vm,
                                meters=meters, accounts_section=acc_sec, project_rows=p_rows,
                                project_footers=p_footers, model_rows=m_rows, agent_rows=a_rows,
                                day_rows=d_rows, static_mode=False
                            )
                            for y in range(h):
                                line = canvas.get_line_text(y)
                                self.assertLessEqual(
                                    str_width(line), w,
                                    f"Canvas line {y} {repr(line)} width {str_width(line)} > {w} (range={tr}, view={vm}, h={h})"
                                )
                            last_line = canvas.get_line_text(h - 1)
                            self.assertIn("F1", last_line, f"F1 missing on line {h-1} for {w}x{h}")
                            self.assertIn("F10", last_line, f"F10 missing on line {h-1} for {w}x{h}")

    @unittest.skipIf(curses is None, "requires curses")
    def test_interactive_curses_tui_fake_stdscr(self):
        """Item 3 & 4: Drive run_curses_tui with fake stdscr across all views and interactive key sequences."""
        doc = load_sample_fixture()
        # Exercise each view mode
        for vm in [ViewMode.PROJECTS, ViewMode.MODELS, ViewMode.AGENTS, ViewMode.DAYS]:
            scr = FakeStdscr(width=80, height=24, keys=[ord('q')])
            rc = run_curses_tui(scr, initial_doc=doc, data_path="fake.json", view_mode=vm, no_color=True)
            self.assertEqual(rc, 0)
            self.assertGreater(len(scr.captured), 0)

        # Exercise fast start with initial_doc=None
        scr_loading = FakeStdscr(width=80, height=24, keys=[ord('q')])
        rc = run_curses_tui(scr_loading, initial_doc=None, data_path="fake.json", view_mode=ViewMode.PROJECTS, no_color=True)
        self.assertEqual(rc, 0)
        captured_text = "".join(str(c[2]) for c in scr_loading.captured if len(c) > 2)
        self.assertIn("Loading", captured_text)

        # Exercise scripted key sequences: range switch, tab view switch, help toggle, filter open/cancel, quit
        scripted_keys = [
            ord('2'),       # Range: Today
            ord('M'),       # Toggle expanded meters
            ord('M'),       # Restore normal meters
            ord('\t'),      # Next view: Models
            ord('?'),       # Open help
            ord('?'),       # Close help
            ord('/'),       # Open filter
            ord('a'), ord('b'), # Filter text
            27,             # Esc (cancel filter)
            ord('q'),       # Quit
        ]
        scr_keys = FakeStdscr(width=100, height=30, keys=scripted_keys)
        rc = run_curses_tui(scr_keys, initial_doc=doc, data_path="fake.json", view_mode=ViewMode.PROJECTS, no_color=True)
        self.assertEqual(rc, 0)


class TUIStaticTest(unittest.TestCase):
    def test_static_output_color_and_nocolor(self):
        doc = load_fixture_doc()
        now = parse_iso_dt(doc["generated_at"])

        # With color
        out_color = render_static_snapshot(doc, width=100, no_color=False, now=now)
        self.assertIn("\033[", out_color)

        # With NO_COLOR
        out_nocolor = render_static_snapshot(doc, width=100, no_color=True, now=now)
        self.assertNotIn("\033[", out_nocolor)

        # Key elements present in static snapshot
        self.assertIn("Kanjo", out_nocolor)
        self.assertIn("Total", out_nocolor)
        # Static mode has no interactive chrome
        self.assertNotIn("F1", out_nocolor)
        self.assertNotIn("Help", out_nocolor)
        self.assertEqual(out_nocolor.splitlines()[-1].strip()[:5], "Total")

    def test_static_colored_highlighting(self):
        doc = load_sample_fixture()
        tz = get_tz(doc)
        now = parse_iso_dt(doc.get("generated_at"), default_tz=tz)
        out = render_static_snapshot(doc, width=120, no_color=False, now=now)
        self.assertIn("\033[1;30;46m", out)  # active range tab: black on cyan
        self.assertNotIn("\033[7m", out)
        self.assertNotIn(";7;", out)

        filtered = filter_report(doc, TimeRange.ALL, now=now)
        p_rows = build_project_rows(filtered, now, tz)
        row_line = next(line for line in out.splitlines() if p_rows[0].name in line)
        # Static snapshots have no selected-row highlight.
        self.assertNotIn("\033[1;37;100m", row_line)
        self.assertNotIn("\033[48;5;8m", row_line)

    def test_cli_usage_lang_flag_isolated(self):
        tmp_dir = tempfile.mkdtemp(prefix="kanjo-tui-lang-test-")
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        try:
            env = dict(os.environ)
            env["KANJO_DATA_DIR"] = os.path.join(tmp_dir, "data")
            env["KANJO_CACHE_DIR"] = os.path.join(tmp_dir, "cache")
            env["KANJO_CLAUDE_DIR"] = os.path.join(fixtures_dir, "claude")
            env["KANJO_CODEX_DIR"] = os.path.join(fixtures_dir, "codex")
            env["KANJO_ANTIGRAVITY_DIR"] = os.path.join(fixtures_dir, "antigravity")
            env["KANJO_TOKEI_DIR"] = fixtures_dir
            env["COLUMNS"] = "120"
            env["NO_COLOR"] = "1"

            with mock.patch.dict(os.environ, env):
                parser = cli.build_parser()
                args = parser.parse_args(["usage", "--once", "--no-color", "--no-cache", "--lang", "zh"])
                out = io.StringIO()
                with mock.patch("sys.stdout", out):
                    rc = cli.cmd_usage(args)
                self.assertEqual(rc, 0)
                output = out.getvalue()
                self.assertIn("项目", output)
                self.assertIn("总计", output)
                self.assertNotIn("PROJECT", output)
                self.assertNotIn("\033[", output)
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_cli_usage_data_flag_isolated(self):
        """Item 2: --data PATH loads an export JSON without scanning or cache writes."""
        sample_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ui", "fixtures", "sample.json"))
        tmp_dir = tempfile.mkdtemp(prefix="kanjo-data-test-")
        try:
            cache_dir = os.path.join(tmp_dir, "cache")
            data_dir = os.path.join(tmp_dir, "data")
            os.makedirs(cache_dir, exist_ok=True)
            os.makedirs(data_dir, exist_ok=True)

            env = dict(os.environ)
            env["KANJO_DATA_DIR"] = data_dir
            env["KANJO_CACHE_DIR"] = cache_dir
            env["KANJO_NO_NETWORK"] = "1"
            env["COLUMNS"] = "120"
            env["NO_COLOR"] = "1"

            with mock.patch.dict(os.environ, env):
                parser = cli.build_parser()
                args = parser.parse_args(["usage", "--data", sample_path, "--once", "--no-color",
                                          "--range", "7d", "--lang", "en"])
                out = io.StringIO()
                with mock.patch("sys.stdout", out):
                    rc = cli.cmd_usage(args)
                self.assertEqual(rc, 0)
                output = out.getvalue()
                self.assertIn("Kanjo", output)
                self.assertIn("weather-cli", output)
                self.assertIn("PocketTimer", output)
                # Verify no cache writes
                self.assertEqual(os.listdir(cache_dir), [])
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_cli_usage_once_isolated(self):
        # Run kanjo usage --once --no-color against test fixtures with clean isolation env vars
        doc = load_fixture_doc()
        tmp_dir = tempfile.mkdtemp(prefix="kanjo-tui-test-")
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        try:
            env = dict(os.environ)
            env["KANJO_DATA_DIR"] = os.path.join(tmp_dir, "data")
            env["KANJO_CACHE_DIR"] = os.path.join(tmp_dir, "cache")
            env["KANJO_CLAUDE_DIR"] = os.path.join(fixtures_dir, "claude")
            env["KANJO_CODEX_DIR"] = os.path.join(fixtures_dir, "codex")
            env["KANJO_ANTIGRAVITY_DIR"] = os.path.join(fixtures_dir, "antigravity")
            env["KANJO_TOKEI_DIR"] = fixtures_dir
            env["COLUMNS"] = "120"
            env["NO_COLOR"] = "1"

            with mock.patch.dict(os.environ, env):
                parser = cli.build_parser()
                args = parser.parse_args(["usage", "--once", "--no-color", "--no-cache", "--lang", "en"])
                out = io.StringIO()
                with mock.patch("sys.stdout", out):
                    rc = cli.cmd_usage(args)
                self.assertEqual(rc, 0)
                output = out.getvalue()
                self.assertIn("Kanjo", output)
                self.assertIn("PROJECT", output)
                self.assertNotIn("\033[", output)
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _display_col(line, needle):
    idx = line.find(needle)
    if idx < 0:
        return None
    return str_width(line[:idx])


class FakeSwitch:
    def __init__(self, result=(0, {"status": "ok"})):
        self.result = result
        self.calls = []

    def __call__(self, email):
        self.calls.append(email)
        return self.result


class TUIMouseCliTest(unittest.TestCase):
    """``--no-mouse`` reaches the interactive loop."""

    def test_no_mouse_flag_defaults_to_enabled(self):
        parser = cli.build_parser()
        self.assertFalse(parser.parse_args(["usage"]).no_mouse)
        self.assertFalse(parser.parse_args(["top"]).no_mouse)
        self.assertTrue(parser.parse_args(["usage", "--no-mouse"]).no_mouse)

    @unittest.skipIf(curses is None, "requires curses")
    def test_no_mouse_flag_reaches_the_loop(self):
        doc = load_sample_fixture()
        seen = {}

        def fake_run(stdscr, **kwargs):
            seen.update(kwargs)
            return 0

        class Tty(io.StringIO):
            def isatty(self):
                return True

        tmp_dir = tempfile.mkdtemp(prefix="kanjo-tui-mouse-")
        try:
            data_path = os.path.join(tmp_dir, "doc.json")
            with open(data_path, "w", encoding="utf-8") as handle:
                json.dump(doc, handle)
            env = dict(os.environ)
            env["KANJO_DATA_DIR"] = os.path.join(tmp_dir, "data")
            env["KANJO_CACHE_DIR"] = os.path.join(tmp_dir, "cache")
            env["KANJO_NO_NETWORK"] = "1"
            with mock.patch.dict(os.environ, env), \
                    mock.patch("kanjo.tui.term.run_curses_tui", fake_run), \
                    mock.patch("curses.wrapper", lambda fn, *a, **k: fn(None, **k)), \
                    mock.patch("sys.stdout", Tty()):
                parser = cli.build_parser()
                args = parser.parse_args(["usage", "--data", data_path, "--no-mouse"])
                rc = cli.cmd_usage(args)
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        self.assertEqual(rc, 0)
        self.assertIn("mouse", seen)
        self.assertFalse(seen["mouse"])


class TUIi18nTest(unittest.TestCase):
    def test_chinese_compact_tokens(self):
        self.assertEqual(format_tokens(9999, "zh"), "9999")
        self.assertEqual(format_tokens(10000, "zh"), "1万")
        self.assertEqual(format_tokens(5584000, "zh"), "558.4万")
        self.assertEqual(format_tokens(864000000, "zh"), "8.6亿")
        self.assertEqual(format_tokens(1234567890, "zh"), "12.3亿")
        self.assertEqual(format_tokens(10 ** 12, "zh"), "1万亿")
        self.assertEqual(format_tokens(-2500, "zh"), "-2500")
        # English stays as before
        self.assertEqual(format_tokens(864000000, "en"), "864M")
        # Money is always $
        self.assertEqual(format_money(1244.2), "$1,244.20")

    def test_chinese_table_strings(self):
        self.assertEqual(t("range.all", "zh"), "全部")
        self.assertEqual(t("range.today", "zh"), "今天")
        self.assertEqual(t("range.7d", "zh"), "7 天")
        self.assertEqual(t("range.30d", "zh"), "30 天")
        self.assertEqual(t("range.reset", "zh"), "自上次重置")
        self.assertEqual(t("range.cycle", "zh"), "本账期")
        self.assertIn("本额度周", t("accounts.title.quota_week", "zh", when="Nov 8 16:55"))
        self.assertEqual(t("row.unattributed", "zh"), "未归属")
        self.assertEqual(t("row.total", "zh"), "总计")
        self.assertEqual(t("fkey.help", "zh"), "帮助")
        self.assertEqual(t("fkey.quit", "zh"), "退出")
        self.assertEqual(t("meter.weekly", "zh"), "每周")
        self.assertEqual(t("meter.five_hour", "zh"), "5 小时")
        self.assertEqual(t("meter.no_live_data", "zh"), "（暂无实时数据）")
        self.assertEqual(t("accounts.current", "zh"), "● 当前")
        self.assertIn("正在加载", t("loading", "zh"))
        self.assertEqual(t("detail.close", "zh"), "[Esc / Backspace] 关闭")
        # Every English key also has a Chinese translation
        from kanjo.tui import i18n
        self.assertEqual(set(i18n._STRINGS["en"]), set(i18n._STRINGS["zh"]))

    def test_resolve_lang_precedence(self):
        # Explicit option wins over everything.
        self.assertEqual(resolve_lang("en", environ={"LANG": "zh_CN.UTF-8"},
                                      app_language_value="zh-Hans"), "en")
        self.assertEqual(resolve_lang("zh", environ={"LANG": "C"},
                                      app_language_value="en"), "zh")
        # App setting wins over the environment.
        self.assertEqual(resolve_lang("auto", environ={"LANG": "en_US.UTF-8"},
                                      app_language_value="zh-Hans"), "zh")
        self.assertEqual(resolve_lang("auto", environ={"LANG": "zh_CN.UTF-8"},
                                      app_language_value="en"), "en")
        # "system" follows the environment.
        self.assertEqual(resolve_lang("auto", environ={"LC_ALL": "zh_CN.UTF-8"},
                                      app_language_value="system"), "zh")
        # No readable app setting -> environment.
        self.assertEqual(resolve_lang("auto", environ={"LC_MESSAGES": "zh_CN"},
                                      app_language_value=""), "zh")
        self.assertEqual(resolve_lang("auto", environ={"LANG": "en_US.UTF-8"},
                                      app_language_value=""), "en")
        self.assertEqual(resolve_lang("auto", environ={}, app_language_value=""), "en")


class TUIChineseDatesTest(unittest.TestCase):
    """Chinese dates: ``10月14日 00:00``, ``今天 13:00``; ISO columns stay ISO."""

    def test_month_day_time_is_chinese(self):
        tz = timezone.utc
        dt = datetime(2026, 10, 14, 0, 0, 0, tzinfo=tz)
        self.assertEqual(format_month_day_time(dt, tz, "zh"), "10月14日 00:00")
        self.assertEqual(format_month_day_time(dt, tz, "en"), "Oct 14 00:00")
        self.assertEqual(format_month_day_time(datetime(2026, 11, 3, 9, 5, tzinfo=tz),
                                               tz, "zh"), "11月3日 09:05")

    def test_today_uses_chinese_relative_word(self):
        tz = timezone.utc
        now = datetime(2026, 11, 13, 13, 0, 0, tzinfo=tz)
        self.assertEqual(format_month_day_time(now, tz, "zh", now), "今天 13:00")
        self.assertEqual(format_month_day_time(now, tz, "en", now), "Nov 13 13:00")
        self.assertEqual(format_month_day_time(datetime(2026, 11, 12, 13, 0, tzinfo=tz),
                                               tz, "zh", now), "11月12日 13:00")

    def test_reset_time_today_is_chinese(self):
        tz = timezone.utc
        now = datetime(2026, 11, 13, 12, 0, 0, tzinfo=tz)
        later_today = now + timedelta(hours=6, minutes=40)
        self.assertEqual(format_reset_countdown(later_today, now, tz, "zh"), "今天 18:40 重置")
        self.assertEqual(format_reset_countdown(later_today, now, tz, "en"), "resets 18:40")
        tomorrow = now + timedelta(hours=30)
        self.assertIn("小时后重置", format_reset_countdown(tomorrow, now, tz, "zh"))
        self.assertIn("resets in", format_reset_countdown(tomorrow, now, tz, "en"))

    def test_accounts_window_label_is_chinese(self):
        now = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
        quota_windows = {"antigravity": {"weekly_resets_at": "2026-11-08T16:55:00Z",
                                         "weekly_window_hours": 168}}
        _start, kind, label = get_accounts_window(quota_windows, {}, now=now,
                                                  tz_name="UTC", lang="zh")
        self.assertEqual(kind, "quota_week")
        self.assertIn("11月8日 16:55 起", label)
        self.assertNotIn("Nov", label)

    def test_accounts_last_seen_is_chinese(self):
        doc = load_sample_fixture()
        tz = get_tz(doc)
        now = parse_iso_dt(doc.get("generated_at"), default_tz=tz)
        section = build_antigravity_accounts_section(doc, now=now, lang="zh")
        self.assertIsNotNone(section)
        alex = next(r for r in section.rows if r.email == "alex@example.com")
        # 2026-10-27T18:25:07Z is 2026-10-28 02:25 in Asia/Shanghai.
        self.assertEqual(alex.last_seen_str, "10月28日 02:25")
        backup = next(r for r in section.rows if r.email == "backup@gmail.com")
        self.assertEqual(backup.last_seen_str, "10月16日 02:40")
        en = build_antigravity_accounts_section(doc, now=now, lang="en")
        alex_en = next(r for r in en.rows if r.email == "alex@example.com")
        self.assertEqual(alex_en.last_seen_str, "Oct 28 02:25")

    def test_iso_last_active_columns_stay_iso(self):
        doc = load_sample_fixture()
        tz = get_tz(doc)
        now = parse_iso_dt(doc.get("generated_at"), default_tz=tz)
        filtered = filter_report(doc, TimeRange.ALL, now=now)
        for lang in ("en", "zh"):
            rows = build_project_rows(filtered, now, tz, lang=lang)
            self.assertTrue(rows)
            for row in rows:
                if row.last_active_str != "—":
                    self.assertRegex(row.last_active_str, r"^\d{4}-\d{2}-\d{2}$")
            footers = build_project_footer_rows(filtered, now, tz, lang=lang)
            total = next(r for r in footers if r.is_total)
            self.assertEqual(total.last_active_str, "2026-10-23")

    def _render_text(self, lang):
        doc = load_sample_fixture()
        tz = get_tz(doc)
        now = parse_iso_dt(doc.get("generated_at"), default_tz=tz)
        filtered = filter_report(doc, TimeRange.ALL, now=now)
        canvas = Canvas(140, 40)
        state = TUIState(version="0.9.0", lang=lang)
        render_ui(canvas, state, filtered, build_total_view_model(filtered, lang),
                  build_subscription_meters(doc, now=now, lang=lang),
                  build_antigravity_accounts_section(doc, now=now, lang=lang),
                  build_project_rows(filtered, now, tz, lang=lang),
                  build_project_footer_rows(filtered, now, tz, lang=lang),
                  build_model_rows(filtered, lang=lang),
                  build_agent_rows(filtered, lang=lang),
                  build_day_rows(filtered, lang=lang))
        return "\n".join(canvas.get_line_text(y) for y in range(canvas.height))

    def test_token_wording_in_totals_and_headers(self):
        zh = self._render_text("zh")
        self.assertIn("2.7亿 Token", zh)
        self.assertNotIn("TOKEN", zh)
        header = next(line for line in zh.splitlines() if "项目" in line and "花费" in line)
        self.assertIn("Token", header)
        en = self._render_text("en")
        self.assertIn("266.2M tokens", en)
        self.assertIn("TOKENS", next(line for line in en.splitlines() if "PROJECT" in line))


class TUIChineseLayoutTest(unittest.TestCase):
    def setUp(self):
        self.doc = load_sample_fixture()
        self.tz = get_tz(self.doc)
        self.now = parse_iso_dt(self.doc.get("generated_at"), default_tz=self.tz)
        self.filtered = filter_report(self.doc, TimeRange.ALL, now=self.now)
        self.total_vm = build_total_view_model(self.filtered, "zh")
        self.meters = build_subscription_meters(self.doc, now=self.now, lang="zh")
        self.accounts_sec = build_antigravity_accounts_section(self.doc, now=self.now, lang="zh")
        self.proj_rows = build_project_rows(self.filtered, self.now, self.tz, lang="zh")
        self.proj_footers = build_project_footer_rows(self.filtered, self.now, self.tz, lang="zh")
        self.model_rows = build_model_rows(self.filtered, lang="zh")
        self.agent_rows = build_agent_rows(self.filtered, lang="zh")
        self.day_rows = build_day_rows(self.filtered, lang="zh")

    def _render(self, w, h, view_mode=ViewMode.PROJECTS):
        state = TUIState(version="0.9.0", lang="zh", view_mode=view_mode)
        canvas = Canvas(w, h)
        render_ui(
            canvas, state, self.filtered, self.total_vm, self.meters,
            self.accounts_sec, self.proj_rows, self.proj_footers,
            self.model_rows, self.agent_rows, self.day_rows,
        )
        return canvas

    def test_chinese_layout_fits_and_aligns(self):
        for w, h in ((80, 24), (140, 40)):
            canvas = self._render(w, h)
            lines = [canvas.get_line_text(y) for y in range(h)]
            for y, line in enumerate(lines):
                self.assertLessEqual(str_width(line), w,
                                     f"zh line {y} wider than {w} at {w}x{h}: {line!r}")

            header = next(line for line in lines if "项目" in line and "花费" in line)
            self.assertIn("Token", header)
            self.assertNotIn("TOKEN", header)
            self.assertIn("会话", header)
            self.assertIn("最后活跃", header)

            # Cost column: all "$" start at the same display column.
            cols = set()
            for row in self.proj_rows:
                line = next((ln for ln in lines if ln.startswith(row.name)), None)
                if line is not None:
                    start = _display_col(line, "$")
                    cols.add(None if start is None else start + str_width(row.cost_str))
            self.assertEqual(len(cols), 1, f"zh cost column misaligned at {w}x{h}: {cols}")

            # Accounts view headers and login column alignment.
            accounts = self._render(w, h, ViewMode.ACCOUNTS)
            alines = [accounts.get_line_text(y) for y in range(h)]
            for y, line in enumerate(alines):
                self.assertLessEqual(str_width(line), w,
                                     f"zh accounts line {y} wider than {w}: {line!r}")
            aheader = next(line for line in alines if "账号" in line and "登录" in line)
            self.assertIn("消息", aheader)
            login_cols = set()
            for row in self.accounts_sec.rows:
                if row.is_unattributed:
                    continue
                line = next((ln for ln in alines if ln.startswith(row.email)), None)
                if line is None:
                    continue
                needle = "是" if row.saved_login else "否"
                login_cols.add(_display_col(line, needle))
            self.assertEqual(len(login_cols), 1, f"zh login column misaligned at {w}x{h}: {login_cols}")

    def test_chinese_terminal_too_small(self):
        canvas = Canvas(40, 10)
        state = TUIState(version="0.9.0", lang="zh")
        render_ui(canvas, state, self.filtered, self.total_vm, self.meters)
        self.assertIn("终端窗口太小", canvas.get_line_text(0))


class TUIAntigravityAccountsViewTest(unittest.TestCase):
    def setUp(self):
        self.doc = load_sample_fixture()
        self.tz = get_tz(self.doc)
        self.now = parse_iso_dt(self.doc.get("generated_at"), default_tz=self.tz)

    def _drive(self, keys, switch_fn=None, doc=None, view_mode=ViewMode.ACCOUNTS,
               width=100, height=30):
        doc = doc if doc is not None else self.doc
        scr = FakeStdscr(width=width, height=height, keys=keys)
        rc = run_curses_tui(
            scr, initial_doc=doc, data_path="fake.json", view_mode=view_mode,
            no_color=True, lang="en", switch_login=switch_fn,
        )
        self.assertEqual(rc, 0)
        text = "".join(str(c[2]) for c in scr.captured if len(c) > 2)
        return text

    def test_extra_quota_window_titles_localized(self):
        doc = {
            "timezone": "UTC",
            "generated_at": "2026-11-13T12:00:00Z",
            "subscriptions": {
                "antigravity": {"plan_label": "Google AI Pro", "monthly_price_usd": 19.99},
            },
            "quota_windows": {
                "antigravity": {
                    "extra_windows": [
                        # 3p buckets: localized by id, regardless of the raw title.
                        {"id": "3p-weekly", "title": "Claude/GPT weekly",
                         "used_percent": 26.0, "resets_at": "2026-11-20T12:00:00Z"},
                        {"id": "3p-5h", "title": "Claude/GPT 5-hour",
                         "used_percent": 50.0, "resets_at": "2026-11-13T18:00:00Z"},
                        # Any other id keeps the (localized) supplied title.
                        {"id": "something-else", "title": "Weekly Limit Remaining",
                         "used_percent": 12.0, "resets_at": "2026-11-20T12:00:00Z"},
                    ],
                },
            },
        }
        now = parse_iso_dt(doc["generated_at"])
        names = [w.name for m in build_subscription_meters(doc, now=now, lang="zh")
                 for w in m.windows]
        self.assertIn("Claude/GPT 每周", names)
        self.assertIn("Claude/GPT 5 小时", names)
        self.assertTrue(all("Week" not in n and "5h" not in n for n in names))
        en_names = [w.name for m in build_subscription_meters(doc, now=now, lang="en")
                    for w in m.windows]
        self.assertIn("Claude/GPT weekly", en_names)
        self.assertIn("Claude/GPT 5-hour", en_names)
        # The non-3p id keeps its (localized) title rather than being remapped.
        self.assertIn("Weekly Limit Remaining", en_names)

    def test_account_rows_carry_login_metadata(self):
        sec = build_antigravity_accounts_section(self.doc, now=self.now, lang="en")
        self.assertIsNotNone(sec)
        alex = next(r for r in sec.rows if r.email == "alex@example.com")
        self.assertTrue(alex.is_current)
        self.assertTrue(alex.saved_login)
        self.assertEqual(alex.messages_str, "142")
        self.assertNotEqual(alex.last_seen_str, "—")
        backup = next(r for r in sec.rows if r.email == "backup@gmail.com")
        self.assertFalse(backup.saved_login)

    def test_accounts_view_absent_without_data(self):
        self.assertNotIn(ViewMode.ACCOUNTS, [v for v, _ in available_view_modes(False)])
        self.assertIn(ViewMode.ACCOUNTS, [v for v, _ in available_view_modes(True)])
        self.assertIsNone(build_antigravity_accounts_section({}, now=self.now))
        canvas = Canvas(80, 24)
        state = TUIState(version="0.9.0", view_mode=ViewMode.ACCOUNTS)
        render_ui(canvas, state)  # no crash, no rows
        self.assertNotIn("ACCOUNT", "\n".join(canvas.get_line_text(y) for y in range(24)))

    @unittest.skipIf(curses is None, "requires curses")
    def test_confirm_box_appears_and_cancel_does_not_switch(self):
        fake = FakeSwitch()
        text = self._drive([curses.KEY_DOWN, 10, ord("n"), ord("q")], fake)
        self.assertIn("Switch login", text)
        self.assertIn("work@company.com", text)
        self.assertIn("write their own login back at their next token refresh", text)
        self.assertEqual(fake.calls, [])

        # Esc also cancels without calling.
        fake2 = FakeSwitch()
        self._drive([curses.KEY_DOWN, 10, 27, ord("q")], fake2)
        self.assertEqual(fake2.calls, [])

    @unittest.skipIf(curses is None, "requires curses")
    def test_y_calls_switch_with_selected_email(self):
        fake = FakeSwitch()
        self._drive([curses.KEY_DOWN, 10, ord("y")] + [-1] * 25 + [ord("q")], fake)
        self.assertEqual(fake.calls, ["work@company.com"])

    @unittest.skipIf(curses is None, "requires curses")
    def test_switch_error_messages(self):
        fake = FakeSwitch((1, {"status": "error", "error": "unsaved_login"}))
        text = self._drive([curses.KEY_DOWN, 10, ord("y")] + [-1] * 25 + [ord("q")], fake)
        self.assertEqual(fake.calls, ["work@company.com"])
        self.assertIn("Current login is not saved yet", text)

        fake_no = FakeSwitch((1, {"status": "error", "error": "no_saved_login"}))
        text = self._drive([curses.KEY_DOWN, 10, ord("y")] + [-1] * 25 + [ord("q")], fake_no)
        self.assertIn("No saved login found", text)

    @unittest.skipIf(curses is None, "requires curses")
    def test_switch_success_note_and_running_agy_message(self):
        # Success with no running agy -> the base note.
        fake = FakeSwitch((0, {"status": "ok", "running_agy": 0}))
        text = self._drive([curses.KEY_DOWN, 10, ord("y")] + [-1] * 25 + [ord("q")], fake)
        self.assertEqual(fake.calls, ["work@company.com"])
        self.assertIn("write their login back", text)
        self.assertNotIn("agy sessions running", text)

        # Success with running agy sessions -> the urgent count message.
        fake_run = FakeSwitch((0, {"status": "ok", "running_agy": 3}))
        text2 = self._drive([curses.KEY_DOWN, 10, ord("y")] + [-1] * 25 + [ord("q")], fake_run)
        self.assertIn("3 agy sessions running", text2)
        self.assertIn("switch back within about an hour", text2)

    @unittest.skipIf(curses is None, "requires curses")
    def test_enter_without_saved_login_shows_hint(self):
        fake = FakeSwitch()
        # Second non-current row: backup@gmail.com has no saved login.
        text = self._drive([curses.KEY_DOWN, curses.KEY_DOWN, 10, ord("q")], fake)
        self.assertEqual(fake.calls, [])
        self.assertIn("Sign in once with `agy`", text)

    @unittest.skipIf(curses is None, "requires curses")
    def test_enter_on_current_row_does_nothing(self):
        fake = FakeSwitch()
        text = self._drive([10, ord("q")], fake)
        self.assertEqual(fake.calls, [])
        self.assertNotIn("Switch login", text)

    @unittest.skipIf(curses is None, "requires curses")
    def test_non_macos_shows_macos_only(self):
        fake = FakeSwitch()
        with mock.patch("kanjo.tui.term.sys.platform", "linux"):
            text = self._drive([curses.KEY_DOWN, 10, ord("q")], None)
        self.assertIn("Switching is macOS-only", text)

    def test_status_message_and_expiry(self):
        w, h = 100, 30
        filtered = filter_report({}, TimeRange.ALL, now=self.now)
        state = TUIState(version="0.9.0", lang="en",
                         status_message="hello status",
                         status_until=time.time() + 5)
        canvas = Canvas(w, h)
        render_ui(canvas, state, filtered, build_total_view_model(filtered))
        self.assertIn("hello status", canvas.get_line_text(h - 2))
        self.assertIn("F1", canvas.get_line_text(h - 1))

        expired = TUIState(version="0.9.0", lang="en",
                           status_message="hello status",
                           status_until=time.time() - 1)
        canvas2 = Canvas(w, h)
        render_ui(canvas2, expired, filtered, build_total_view_model(filtered))
        self.assertNotIn("hello status", "\n".join(canvas2.get_line_text(y) for y in range(h)))

    def test_accounts_and_confirm_styles_never_combine_colour_with_reverse(self):
        filtered = filter_report(self.doc, TimeRange.ALL, now=self.now)
        for view_mode in (ViewMode.ACCOUNTS, ViewMode.PROJECTS):
            for confirm in ("", "work@company.com"):
                canvas = Canvas(100, 30)
                state = TUIState(version="0.9.0", lang="zh",
                                 view_mode=view_mode,
                                 confirm_switch_email=confirm,
                                 status_message="status text",
                                 status_until=time.time() + 5)
                render_ui(
                    canvas, state, filtered,
                    build_total_view_model(filtered, "zh"),
                    build_subscription_meters(self.doc, now=self.now, lang="zh"),
                    build_antigravity_accounts_section(self.doc, now=self.now, lang="zh"),
                    build_project_rows(filtered, self.now, self.tz, lang="zh"),
                    build_project_footer_rows(filtered, self.now, self.tz, lang="zh"),
                    build_model_rows(filtered, lang="zh"),
                    build_agent_rows(filtered, lang="zh"),
                    build_day_rows(filtered, lang="zh"),
                )
                for y in range(canvas.height):
                    for x in range(canvas.width):
                        style = canvas.grid[y][x].style
                        self.assertFalse(
                            style.inverse and (style.fg is not None or style.bg is not None),
                            f"cell ({x},{y}) combines colour and reverse: {style!r}",
                        )

    def test_confirm_box_fits_zh_narrow(self):
        state = TUIState(version="0.9.0", lang="zh",
                         confirm_switch_email="a-very-long-account-name@example.com")
        canvas = Canvas(72, 24)
        filtered = filter_report({}, TimeRange.ALL, now=self.now)
        render_ui(canvas, state, filtered, build_total_view_model(filtered, "zh"))
        for y in range(24):
            self.assertLessEqual(str_width(canvas.get_line_text(y)), 72)
        all_text = "\n".join(canvas.get_line_text(y) for y in range(24))
        self.assertIn("切换登录", all_text)


class TUIMouseTest(unittest.TestCase):
    """htop-style mouse support: hit boxes, and clicks acting like keys."""

    def setUp(self):
        self.doc = load_sample_fixture()
        self.tz = get_tz(self.doc)
        self.now = parse_iso_dt(self.doc.get("generated_at"), default_tz=self.tz)
        self.filtered = filter_report(self.doc, TimeRange.ALL, now=self.now)

    def _view_models(self, lang="en"):
        return dict(
            filtered=self.filtered,
            total_vm=build_total_view_model(self.filtered, lang),
            meters=build_subscription_meters(self.doc, now=self.now, lang=lang),
            accounts_section=build_antigravity_accounts_section(self.doc, now=self.now, lang=lang),
            project_rows=build_project_rows(self.filtered, self.now, self.tz, lang=lang),
            project_footers=build_project_footer_rows(self.filtered, self.now, self.tz, lang=lang),
            model_rows=build_model_rows(self.filtered, lang=lang),
            agent_rows=build_agent_rows(self.filtered, lang=lang),
            day_rows=build_day_rows(self.filtered, lang=lang),
        )

    def _render(self, w, h, view_mode=ViewMode.PROJECTS):
        canvas = Canvas(w, h)
        state = TUIState(version="0.9.0", view_mode=view_mode)
        hit_boxes = render_ui(canvas, state, **self._view_models())
        return canvas, state, hit_boxes

    def _box(self, hit_boxes, action):
        matches = [box for box in hit_boxes if box[3] == action]
        self.assertTrue(matches, "no hit box for %r in %r" % (action, hit_boxes))
        return matches[0]

    def _first_data_row(self, text, rows):
        return next(line for line in text.splitlines()
                    if any(line.startswith(r.name) for r in rows))

    def test_hit_boxes_tabs_and_fkeys(self):
        for w, h in ((80, 24), (140, 40)):
            canvas, _state, hit_boxes = self._render(w, h)
            line0 = canvas.get_line_text(0)
            for value in ("all", "today", "7d", "30d", "reset", "cycle"):
                box_y, x0, x1, action = self._box(hit_boxes, "range:" + value)
                self.assertEqual(box_y, 0)
                self.assertGreaterEqual(x0, 0)
                self.assertLess(x1, w)
                self.assertEqual(action, "range:" + value)
                # The box covers a drawn label, not blank space.
                self.assertEqual(line0[x0], " ")
                self.assertNotEqual(line0[x0:x1 + 1].strip(), "")

            bar_y = h - 1
            bar = canvas.get_line_text(bar_y)
            for name in ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F10"):
                box_y, x0, x1, action = self._box(hit_boxes, "fkey:" + name)
                self.assertEqual(box_y, bar_y)
                self.assertEqual(action, "fkey:" + name)
                self.assertEqual(bar[x0:x0 + len(name)], name)
                self.assertLessEqual(x1, w - 1)

    def test_hit_boxes_rows_and_sort_headers(self):
        for w, h in ((80, 24), (140, 40)):
            canvas, _state, hit_boxes = self._render(w, h)
            proj_w = max(16, w - 59)
            header_y = next(y for y in range(canvas.height)
                            if "PROJECT" in canvas.get_line_text(y))
            header = canvas.get_line_text(header_y)
            expected = (("name", 0, proj_w - 1), ("cost", proj_w + 1, proj_w + 10),
                        ("tokens", proj_w + 12, proj_w + 19),
                        ("sessions", proj_w + 21, proj_w + 28))
            for column, x0, x1 in expected:
                box_y, bx0, bx1, action = self._box(hit_boxes, "sort:" + column)
                self.assertEqual(box_y, header_y)
                self.assertEqual((bx0, bx1), (x0, min(w - 1, x1)))
                self.assertEqual(action, "sort:" + column)
                # The box sits on the header label, not on blank space.
                self.assertNotEqual(header[bx0:bx1 + 1].strip(), "")
            # LAST ACTIVE and the 8-week strip are not sortable.
            self.assertEqual([b for b in hit_boxes if b[3] == "sort:last_active"], [])

            row_boxes = [b for b in hit_boxes if b[3].startswith("row:")]
            self.assertGreaterEqual(len(row_boxes), 5)
            rows = self._view_models()["project_rows"]
            for index, (box_y, x0, x1, action) in enumerate(row_boxes):
                self.assertEqual(action, "row:%d" % index)
                self.assertEqual((x0, x1), (0, w - 1))
                self.assertGreater(box_y, header_y)
                # Each box sits on the line its row was drawn on.
                self.assertTrue(canvas.get_line_text(box_y).startswith(rows[index].name),
                                "row %d box is not on its own line" % index)

    def test_hit_boxes_rows_in_every_view(self):
        for view_mode in (ViewMode.PROJECTS, ViewMode.MODELS, ViewMode.AGENTS,
                          ViewMode.DAYS, ViewMode.ACCOUNTS):
            _canvas, _state, hit_boxes = self._render(120, 40, view_mode)
            actions = [box[3] for box in hit_boxes if box[3].startswith("row:")]
            self.assertTrue(actions, "no row hit boxes in %s" % view_mode)
            self.assertEqual(actions[0], "row:0")

    def test_hit_box_at_resolves_coordinates(self):
        _canvas, _state, hit_boxes = self._render(80, 24)
        _y, x0, x1, _action = self._box(hit_boxes, "range:7d")
        self.assertEqual(hit_box_at(hit_boxes, 0, x0), "range:7d")
        self.assertEqual(hit_box_at(hit_boxes, 0, x1), "range:7d")
        self.assertIsNone(hit_box_at(hit_boxes, 0, x0 - 1))
        self.assertIsNone(hit_box_at(hit_boxes, 1, x0))

    def test_mouse_event_kind_and_click_keys(self):
        self.assertEqual(mouse_event_kind(BUTTON1_BITS), ("click", 0))
        self.assertEqual(mouse_event_kind(WHEEL_UP_BITS), ("wheel", -MOUSE_WHEEL_ROWS))
        self.assertEqual(mouse_event_kind(WHEEL_DOWN_BITS), ("wheel", MOUSE_WHEEL_ROWS))
        self.assertIsNone(mouse_event_kind(0))
        self.assertIsNone(mouse_event_kind(1 << 30))

        self.assertEqual(mouse_click_key("range:all"), ord("1"))
        self.assertEqual(mouse_click_key("range:cycle"), ord("6"))
        self.assertEqual(mouse_click_key("fkey:F1"), getattr(curses, "KEY_F1", None))
        self.assertEqual(mouse_click_key("fkey:F10"), getattr(curses, "KEY_F10", None))
        self.assertIsNone(mouse_click_key("row:2"))
        self.assertIsNone(mouse_click_key("sort:cost"))
        self.assertIsNone(mouse_click_key("range:nope"))

    def _drive(self, events, keys=(), view_mode=ViewMode.PROJECTS, mouse=True,
               width=80, height=24):
        scr = FakeMouseStdscr(width=width, height=height, events=events, keys=list(keys))
        rc = run_curses_tui(
            scr, initial_doc=self.doc, data_path="fake.json", no_color=True,
            lang="en", view_mode=view_mode, mouse=mouse,
            mouse_reader=mouse_reader(scr),
        )
        self.assertEqual(rc, 0)
        return scr

    @unittest.skipIf(curses is None, "requires curses")
    def test_click_on_range_tab_switches_range(self):
        _canvas, _state, hit_boxes = self._render(80, 24)
        _y, clicked_x, _x1, _action = self._box(hit_boxes, "range:7d")
        _y, all_x, _x1, _action = self._box(hit_boxes, "range:all")
        scr = self._drive([(clicked_x, 0, BUTTON1_BITS)], keys=[ord("q")])
        cells = reverse_cells(scr)
        # The clicked tab is highlighted, the previously active one is not.
        self.assertIn((0, clicked_x + 1), cells)
        self.assertNotIn((0, all_x + 1), cells)

    @unittest.skipIf(curses is None, "requires curses")
    def test_click_on_fkey_bar_acts_like_the_key(self):
        _canvas, _state, hit_boxes = self._render(80, 24)
        bar_y = 23

        # F1 opens the help overlay, exactly like pressing F1.
        _y, x0, _x1, _action = self._box(hit_boxes, "fkey:F1")
        scr = self._drive([(x0, bar_y, BUTTON1_BITS)], keys=[ord("q")])
        self.assertTrue(any("Help & Shortcuts" in frame for frame in screen_frames(scr)),
                        "clicking F1 did not open the help overlay")

        # F10 quits, so the queued keys are never read.
        _y, x0, _x1, _action = self._box(hit_boxes, "fkey:F10")
        scr = self._drive([(x0, bar_y, BUTTON1_BITS)], keys=[ord("2"), ord("3")])
        self.assertEqual(scr.keys, [ord("2"), ord("3")])

        # F2 cycles the range, like the right arrow.
        _y, x0, _x1, _action = self._box(hit_boxes, "fkey:F2")
        scr = self._drive([(x0, bar_y, BUTTON1_BITS)], keys=[ord("q")])
        self.assertIn("Today", screen_text(scr))

    @unittest.skipIf(curses is None, "requires curses")
    def test_click_on_row_selects_and_second_click_opens_detail(self):
        _canvas, _state, hit_boxes = self._render(80, 24)
        rows = self._view_models()["project_rows"]
        row2_y = self._box(hit_boxes, "row:2")[0]
        row4_y = self._box(hit_boxes, "row:4")[0]

        # A single click only moves the selection: Enter then opens that row.
        scr = self._drive([(3, row2_y, BUTTON1_BITS)], keys=[ord("q")])
        self.assertNotIn("Project: ", screen_text(scr))

        # A second click on the selected row acts like a double-click.
        scr = self._drive([(3, row2_y, BUTTON1_BITS), (4, row2_y, BUTTON1_BITS)],
                          keys=[ord("q")])
        self.assertIn("Project: %s" % rows[2].name, screen_text(scr))

        # Clicking a row and pressing Enter opens that row, not another one.
        scr = self._drive([(3, row4_y, BUTTON1_BITS)], keys=[10, ord("q")])
        text = screen_text(scr)
        self.assertIn("Project: %s" % rows[4].name, text)
        self.assertNotIn("Project: %s" % rows[0].name, text)

    @unittest.skipIf(curses is None, "requires curses")
    def test_wheel_scrolls_the_table_by_three_rows(self):
        _canvas, _state, hit_boxes = self._render(80, 24)
        row_y = self._box(hit_boxes, "row:0")[0]
        rows = self._view_models()["project_rows"]
        self.assertGreater(len(rows), 4)

        scr = self._drive([(3, row_y, WHEEL_DOWN_BITS)], keys=[10, ord("q")])
        self.assertIn("Project: %s" % rows[3].name, screen_text(scr))

        # Three wheel-ups bring the selection back to the first row.
        scr = self._drive([(3, row_y, WHEEL_UP_BITS)] * 3, keys=[10, ord("q")])
        self.assertIn("Project: %s" % rows[0].name, screen_text(scr))

        # The wheel does nothing outside the table.
        scr = self._drive([(3, 1, WHEEL_DOWN_BITS)], keys=[10, ord("q")])
        self.assertIn("Project: %s" % rows[0].name, screen_text(scr))

    @unittest.skipIf(curses is None, "requires curses")
    def test_click_on_header_sorts_and_toggles_direction(self):
        _canvas, _state, hit_boxes = self._render(80, 24)
        header_y, x0, _x1, _action = self._box(hit_boxes, "sort:tokens")
        rows = self._view_models()["project_rows"]
        ordered = sorted(rows, key=lambda r: parse_tokens_str(r.tokens_str))
        smallest, biggest = ordered[0], ordered[-1]

        scr = self._drive([(x0, header_y, BUTTON1_BITS)], keys=[ord("q")])
        first_row = self._first_data_row(screen_text(scr), rows)
        self.assertTrue(first_row.startswith(biggest.name),
                        "expected %s first, got %r" % (biggest.name, first_row))

        # A second click on the same column flips the direction.
        scr = self._drive([(x0, header_y, BUTTON1_BITS), (x0, header_y, BUTTON1_BITS)],
                          keys=[ord("q")])
        first_row = self._first_data_row(screen_text(scr), rows)
        self.assertTrue(first_row.startswith(smallest.name),
                        "expected %s first, got %r" % (smallest.name, first_row))

    @unittest.skipIf(curses is None, "requires curses")
    def test_no_mouse_leaves_the_terminal_alone(self):
        _canvas, _state, hit_boxes = self._render(80, 24)
        rows = self._view_models()["project_rows"]
        row2_y = self._box(hit_boxes, "row:2")[0]
        scr = self._drive([(3, row2_y, BUTTON1_BITS)], keys=[10, ord("q")], mouse=False)
        text = screen_text(scr)
        # The click is ignored, so Enter still acts on the first row.
        self.assertIn("Project: %s" % rows[0].name, text)
        self.assertNotIn("Project: %s" % rows[2].name, text)

    @unittest.skipIf(curses is None, "requires curses")
    def test_mouse_click_dismisses_help(self):
        _canvas, _state, hit_boxes = self._render(80, 24)
        row_y = self._box(hit_boxes, "row:2")[0]
        scr = self._drive([(3, row_y, BUTTON1_BITS)], keys=[ord("?"), ord("q")])
        frames = screen_frames(scr)
        self.assertTrue(any("Help & Shortcuts" in frame for frame in frames),
                        "the help overlay never appeared")
        self.assertNotIn("Help & Shortcuts", screen_text(scr),
                         "a click did not close the help overlay")

    def test_apply_mouse_event_pure_mapping(self):
        _canvas, state, hit_boxes = self._render(80, 24)
        rows = self._view_models()["project_rows"]
        row_count = visible_row_count(state, rows, [], [], [], None)
        row1_y = self._box(hit_boxes, "row:1")[0]

        # Clicking an unselected row only selects it.
        self.assertIsNone(apply_mouse_event(BUTTON1_BITS, 3, row1_y, hit_boxes,
                                            state, row_count))
        self.assertEqual(state.selected_index, 1)
        # Clicking the selected row acts like Enter.
        self.assertEqual(apply_mouse_event(BUTTON1_BITS, 3, row1_y, hit_boxes,
                                           state, row_count), 10)
        # The wheel moves the selection by three rows and clamps at both ends.
        apply_mouse_event(WHEEL_DOWN_BITS, 3, row1_y, hit_boxes, state, row_count)
        self.assertEqual(state.selected_index, 4)
        apply_mouse_event(WHEEL_UP_BITS, 3, row1_y, hit_boxes, state, row_count)
        self.assertEqual(state.selected_index, 1)
        apply_mouse_event(WHEEL_UP_BITS, 3, row1_y, hit_boxes, state, row_count)
        self.assertEqual(state.selected_index, 0)
        # Header clicks set the sort column, then flip the direction.
        header_y, x0, _x1, _action = self._box(hit_boxes, "sort:sessions")
        self.assertIsNone(apply_mouse_event(BUTTON1_BITS, x0, header_y, hit_boxes,
                                            state, row_count))
        self.assertEqual((state.sort_column, state.sort_descending), ("sessions", True))
        apply_mouse_event(BUTTON1_BITS, x0, header_y, hit_boxes, state, row_count)
        self.assertEqual((state.sort_column, state.sort_descending), ("sessions", False))
        # Ignored events leave the state alone.
        self.assertIsNone(apply_mouse_event(0, 3, 1, hit_boxes, state, row_count))
        self.assertEqual(state.selected_index, 0)

class TUIMissingQuotaAndStaticTest(unittest.TestCase):
    def test_claude_gpt_meter_labels_are_not_truncated_at_120_columns(self):
        doc = {
            "timezone": "UTC",
            "generated_at": "2026-11-13T12:00:00Z",
            "subscriptions": {
                "antigravity": {"plan_label": "Google AI Pro", "monthly_price_usd": 19.99},
            },
            "quota_windows": {
                "antigravity": {
                    "extra_windows": [
                        {"id": "3p-weekly", "title": "Weekly Limit Remaining",
                         "used_percent": 26.0, "resets_at": "2026-11-20T12:00:00Z"},
                        {"id": "3p-5h", "title": "Five Hour Limit Remaining",
                         "used_percent": 50.0, "resets_at": "2026-11-13T18:00:00Z"},
                    ],
                },
            },
            "totals": {"cost": 0.0, "tokens": {"total": 0}, "sessions": 0},
            "projects": [],
        }
        now = parse_iso_dt(doc["generated_at"])
        out = render_static_snapshot(doc, width=120, no_color=True, now=now, lang="en")
        self.assertIn("Claude/GPT weekly", out)
        self.assertIn("Claude/GPT 5-hour", out)

    def test_meter_label_width_fits_label_and_keeps_bar_room(self):
        from kanjo.tui.render import _meter_label_width
        doc = {
            "timezone": "UTC",
            "generated_at": "2026-11-13T12:00:00Z",
            "subscriptions": {"antigravity": {"plan_label": "Google AI Pro", "monthly_price_usd": 19.99}},
            "quota_windows": {"antigravity": {"extra_windows": [
                {"id": "3p-weekly", "title": "x", "used_percent": 1.0,
                 "resets_at": "2026-11-20T12:00:00Z"},
            ]}},
        }
        now = parse_iso_dt(doc["generated_at"])
        meters = build_subscription_meters(doc, now=now, lang="en")
        # Full-width column at 120 cols: the whole label fits.
        self.assertEqual(_meter_label_width(meters, "full", 118), len("Claude/GPT weekly"))
        # At 80 columns the label column still leaves the bar >= 10 cells.
        w80 = _meter_label_width(meters, "full", 80)
        self.assertLessEqual(w80 + 2 + 1 + 8 + 16 + 10, 80)
        self.assertEqual(w80, len("Claude/GPT weekly"))

    def test_subscription_without_quota_shows_placeholder(self):
        doc = {
            "timezone": "UTC",
            "generated_at": "2026-11-13T12:00:00Z",
            "subscriptions": {"claude": {"plan_label": "Claude Max", "monthly_price_usd": 100.0}},
            "quota_windows": {},
            "totals": {"cost": 0.0, "tokens": {"total": 0}, "sessions": 0},
            "projects": [],
        }
        now = parse_iso_dt(doc["generated_at"])
        meters = build_subscription_meters(doc, now=now, lang="en")
        self.assertEqual(len(meters), 1)
        self.assertEqual(len(meters[0].windows), 1)
        placeholder = meters[0].windows[0]
        self.assertTrue(placeholder.placeholder)
        self.assertEqual(placeholder.name, "quota")
        self.assertIn("no live data", placeholder.detail)

        zh = build_subscription_meters(doc, now=now, lang="zh")[0].windows[0]
        self.assertEqual(zh.name, "额度")
        self.assertIn("暂无实时数据", zh.detail)

        out = render_static_snapshot(doc, width=100, no_color=True, now=now, lang="en")
        self.assertIn("quota", out)
        self.assertIn("(no live data)", out)

    def test_static_shows_top_15_projects_and_no_chrome(self):
        projects = []
        for i in range(20):
            projects.append({
                "id": "p%d" % i,
                "name": "proj%02d" % i,
                "cost": float(100 - i),
                "tokens": {"total": 1000 + i},
                "sessions": 1,
                "by_day": [],
                "by_agent": [],
                "sessions_detail": [],
            })
        doc = {
            "timezone": "UTC",
            "generated_at": "2026-11-13T12:00:00Z",
            "totals": {"cost": sum(p["cost"] for p in projects),
                       "tokens": {"total": sum(p["tokens"]["total"] for p in projects)},
                       "sessions": 20},
            "projects": projects,
            "quota_windows": {},
            "subscriptions": {},
        }
        out = render_static_snapshot(doc, width=100, no_color=True, lang="en")
        self.assertIn("proj00", out)
        self.assertIn("proj14", out)
        self.assertNotIn("proj15", out)
        self.assertNotIn("F1", out)
        self.assertNotIn("F10", out)
        # No selected-row highlight and no trailing blank padding.
        self.assertNotIn("\033[", out)
        self.assertTrue(out.rstrip("\n").splitlines()[-1].startswith("Total"))


def _is_wide(ch: str) -> bool:
    """True for characters that may start a new line without a space."""
    if not ch:
        return False
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _fold_breaks_ok(chunks, text: str) -> bool:
    """True when every line break in ``chunks`` falls on a space or between
    two wide (CJK) characters, i.e. no word was cut in half.

    ``chunks`` are the rendered lines in order; ``text`` is the text they were
    wrapped from. A break inside a word leaves no space behind, so the next
    chunk has to continue the same word, which is only allowed for CJK.
    """
    remaining = " ".join(text.split())
    for chunk in chunks:
        if not remaining.startswith(chunk):
            return False
        remaining = remaining[len(chunk):]
        if not remaining:
            return True
        if remaining.startswith(" "):
            remaining = remaining[1:]
            continue
        # No space at the break: only CJK may break between characters, on
        # either side of the break.
        if _is_wide(remaining[0]) or (chunk and _is_wide(chunk[-1])):
            continue
        return False
    return remaining == ""


def _display_col_to_index(line: str, col: int) -> int:
    """Character index of the first character starting at display column ``col``."""
    width = 0
    for idx, ch in enumerate(line):
        if width >= col:
            return idx
        width += char_width(ch)
    return len(line)


def _slice_display(line: str, start_col: int, end_col: int) -> str:
    """Substring of ``line`` covering display columns ``[start_col, end_col)``."""
    return line[_display_col_to_index(line, start_col):_display_col_to_index(line, end_col)]


class TUIHelpWrapTest(unittest.TestCase):
    """The help overlay wraps at word boundaries, never inside a word."""

    HELP_KEYS = (
        "navigation", "range", "views", "detail", "filter",
        "sort", "meters", "refresh", "mouse", "quit",
    )

    def test_wrap_display_breaks_at_word_boundaries(self):
        # Latin words stay whole; the break only replaces a space.
        text = "Click tabs, F-keys, rows or headers; wheel scrolls; --no-mouse disables"
        longest = max(str_width(word) for word in text.split())
        for width in range(longest, 60):
            lines = wrap_display(text, width)
            for line in lines:
                self.assertLessEqual(str_width(line), width)
            self.assertEqual(" ".join(lines), " ".join(text.split()))
            self.assertTrue(all(line == line.rstrip() for line in lines))
            self.assertTrue(_fold_breaks_ok(lines, text))

        # A word longer than the line is broken as a last resort.
        self.assertEqual(wrap_display("abcdefghij", 4), ["abcd", "efgh", "ij"])
        self.assertEqual(wrap_display("aa bbbbbbbbbb cc", 4),
                         ["aa", "bbbb", "bbbb", "bb", "cc"])

        # CJK may break between any two characters.
        self.assertEqual(wrap_display("中文换行测试", 5), ["中文", "换行", "测试"])
        self.assertEqual(wrap_display("项目：名称", 6), ["项目：", "名称"])

        # Mixed text keeps the Latin words intact and still folds back.
        mixed = "Antigravity 账号 · 本额度周"
        lines = wrap_display(mixed, 12)
        self.assertLessEqual(len(lines), 3)
        self.assertTrue(_fold_breaks_ok(lines, mixed), repr(lines))
        for line in lines:
            self.assertLessEqual(str_width(line), 12)

        # Leading and trailing spaces never produce blank lines.
        self.assertEqual(wrap_display("  hi  ", 10), ["hi"])
        self.assertEqual(wrap_display("", 10), [""])

    def _help_box(self, lang, w, h):
        doc = load_sample_fixture()
        tz = get_tz(doc)
        now = parse_iso_dt(doc.get("generated_at"), default_tz=tz)
        filtered = filter_report(doc, TimeRange.ALL, now=now)
        canvas = Canvas(w, h)
        state = TUIState(version="0.9.0", lang=lang, show_help=True)
        render_ui(canvas, state, filtered, build_total_view_model(filtered, lang),
                  build_subscription_meters(doc, now=now, lang=lang),
                  build_antigravity_accounts_section(doc, now=now, lang=lang),
                  build_project_rows(filtered, now, tz, lang=lang),
                  build_project_footer_rows(filtered, now, tz, lang=lang),
                  build_model_rows(filtered, lang=lang),
                  build_agent_rows(filtered, lang=lang),
                  build_day_rows(filtered, lang=lang))
        lines = [canvas.get_line_text(y) for y in range(h)]
        # The overlay is centred, 76 columns wide at most.
        box_w = max(24, min(w - 4, 76))
        left = (w - box_w) // 2
        right = left + box_w - 1
        top = next(y for y, line in enumerate(lines) if t("help.title", lang) in line)
        bottom = next(y for y in range(top, h)
                      if _slice_display(lines[y], left, left + 1) == "└")
        return lines, left, right, top, bottom

    def _help_chunks(self, lines, left, right, top, bottom):
        """Rendered description lines, in order."""
        chunks = []
        for y in range(top + 2, bottom - 1):
            chunk = _slice_display(lines[y], left + 16, right).strip()
            if chunk:
                chunks.append(chunk)
        return chunks

    def _expected_help_text(self, lang):
        return " ".join(" ".join(t("help.%s.desc" % key, lang).split())
                        for key in self.HELP_KEYS)

    def test_help_overlay_never_splits_a_word(self):
        for lang in ("en", "zh"):
            w, h = 90, 28
            lines, left, right, top, bottom = self._help_box(lang, w, h)
            for y in range(top, bottom + 1):
                self.assertLessEqual(str_width(lines[y]), w,
                                     "help line %d wider than %d: %r" % (y, w, lines[y]))
            for y in range(top + 1, bottom):
                self.assertEqual(_slice_display(lines[y], right, right + 1), "│",
                                 "help border broken at %d: %r" % (y, lines[y]))
            self.assertEqual(_slice_display(lines[top], left, left + 1), "┌")
            self.assertEqual(_slice_display(lines[top], right, right + 1), "┐")
            self.assertEqual(_slice_display(lines[bottom], right, right + 1), "┘")

            # Folding the wrapped lines back has to give every description,
            # with each break on a space or between two CJK characters.
            chunks = self._help_chunks(lines, left, right, top, bottom)
            expected = self._expected_help_text(lang)
            self.assertTrue(_fold_breaks_ok(chunks, expected),
                            "%s help text was wrapped inside a word: %r" % (lang, chunks))

    def test_help_overlay_wraps_at_every_sample_size(self):
        for lang in ("en", "zh"):
            for w, h in ((80, 24), (90, 28), (100, 30), (120, 40), (200, 50)):
                lines, left, right, top, bottom = self._help_box(lang, w, h)
                chunks = self._help_chunks(lines, left, right, top, bottom)
                self.assertTrue(
                    _fold_breaks_ok(chunks, self._expected_help_text(lang)),
                    "%s help text was wrapped inside a word at %dx%d: %r"
                    % (lang, w, h, chunks))


if __name__ == "__main__":
    unittest.main()
