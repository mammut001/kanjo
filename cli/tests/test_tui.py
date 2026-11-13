"""Unit tests for Kanjo TUI (`kanjo usage` / `kanjo top`)."""

from datetime import datetime, timezone, timedelta
import io
import json
import os
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from kanjo.tui.model import (
    AntigravityAccountRow, AntigravityAccountsSection, FilteredData,
    QuotaLevel, RANGE_TABS, TimeRange, VIEW_MODES, ViewMode,
    agent_color, build_agent_rows, build_antigravity_accounts_section,
    build_day_rows, build_model_rows, build_project_detail,
    build_project_footer_rows, build_project_rows, build_subscription_meters,
    build_total_view_model, compute_30d_sparkline, compute_8w_strip,
    filter_report, format_money, format_reset_countdown, format_tokens,
    get_accounts_window, get_tz, heat_level, parse_iso_dt, quota_level
)
from kanjo.tui.render import Canvas, Cell, Style, TUIState, render_ui, char_width, str_width, truncate_str
from kanjo.tui.static import canvas_to_ansi, render_static_snapshot
from kanjo import cli


def load_fixture_doc() -> dict:
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "export_sample.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


class TUIModelTest(unittest.TestCase):
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
        self.assertIn("F1Help", out_nocolor)

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
                args = parser.parse_args(["usage", "--once", "--no-color", "--no-cache"])
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


if __name__ == "__main__":
    unittest.main()
