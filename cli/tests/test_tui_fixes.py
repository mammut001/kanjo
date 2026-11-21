"""Regression tests for verified TUI defects."""

import copy
import json
import os
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

try:
    import curses
except ImportError:  # Windows has no _curses.
    curses = None

from kanjo.tui.model import (
    AGENT_COLORS, TimeRange, build_subscription_meters, compute_30d_sparkline,
    compute_8w_strip, filter_report,
)
from kanjo.tui.render import SELECTED_ROW_BG, Style, TUIState
from kanjo.tui.term import ColorManager, ViewModelCache, run_curses_tui

from tests.test_tui import FakeStdscr, screen_frames

NOW = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)


def load_sample_fixture() -> dict:
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ui", "fixtures", "sample.json"))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def synthetic_doc() -> dict:
    """A project with $10 on 2026-11-18 and an unattributed $5 session on 2026-11-20."""
    return copy.deepcopy({
        "timezone": "UTC",
        "totals": {"cost": 15.0, "tokens": {"total": 1500}, "sessions": 2,
                   "first_active": "2026-11-18", "last_active": "2026-11-20"},
        "projects": [{
            "id": "p1", "name": "alpha", "cost": 10.0, "tokens": {"total": 1000}, "sessions": 1,
            "first_active": "2026-11-18", "last_active": "2026-11-18",
            "by_agent": [{"agent": "claude", "label": "Claude Code", "cost": 10.0,
                          "tokens": {"total": 1000}, "sessions": 1}],
            "by_day": [{"day": "2026-11-18", "cost": 10.0, "tokens": 1000,
                        "by_agent": {"claude": 10.0}, "by_agent_tokens": {"claude": 1000}}],
            "by_model": [{"model": "claude-opus-5-5", "agent": "claude", "cost": 10.0,
                          "tokens": {"total": 1000}}],
            "sessions_detail": [{"id": "s1", "agent": "claude", "started": "2026-11-18T10:00:00Z",
                                 "ended": "2026-11-18T11:00:00Z", "cost": 10.0,
                                 "tokens": {"total": 1000}, "models": ["claude-opus-5-5"]}],
        }],
        "buckets": {
            "unattributed": {
                "cost": 5.0, "tokens": {"total": 500}, "sessions": 1,
                "first_active": "2026-11-20", "last_active": "2026-11-20",
                "sessions_detail": [{"id": "u1", "agent": "claude", "started": "2026-11-20T10:00:00Z",
                                     "ended": "2026-11-20T11:00:00Z", "cost": 5.0,
                                     "tokens": {"total": 500}, "models": ["claude-opus-5-5"]}],
            },
            "excluded": {"cost": 0.0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
        },
    })


class DaysViewReconcilesTest(unittest.TestCase):
    def test_days_sum_to_total_for_every_range(self):
        doc = synthetic_doc()
        for tr in TimeRange:
            f = filter_report(doc, tr, now=NOW)
            self.assertAlmostEqual(sum(d["cost"] for d in f.by_day), f.total_cost, places=2, msg=tr)
        for tr in (TimeRange.ALL, TimeRange.TODAY):
            days = {d["day"]: d["cost"] for d in filter_report(doc, tr, now=NOW).by_day}
            self.assertAlmostEqual(days.get("2026-11-20", 0.0), 5.0, places=2, msg=tr)

    def test_days_sum_to_total_on_sample_fixture(self):
        doc = load_sample_fixture()
        for tr in (TimeRange.ALL, TimeRange.DAYS_30):
            f = filter_report(doc, tr)
            self.assertAlmostEqual(sum(d["cost"] for d in f.by_day), f.total_cost, places=2, msg=tr)

    def test_session_spanning_midnight_splits_across_days(self):
        doc = synthetic_doc()
        s = doc["buckets"]["unattributed"]["sessions_detail"][0]
        s["started"] = "2026-11-19T23:00:00Z"
        s["ended"] = "2026-11-20T01:00:00Z"
        days = {d["day"]: d["cost"] for d in filter_report(doc, TimeRange.ALL, now=NOW).by_day}
        self.assertAlmostEqual(days["2026-11-19"], 2.5, places=2)
        self.assertAlmostEqual(days["2026-11-20"], 2.5, places=2)


def big_old_model_doc() -> dict:
    """$100 of claude-opus-5-5 on 2026-10-01 and $1 today."""
    doc = synthetic_doc()
    p = doc["projects"][0]
    p["cost"] = 101.0
    p["tokens"] = {"total": 1010000}
    p["sessions"] = 2
    p["first_active"], p["last_active"] = "2026-10-01", "2026-11-20"
    p["by_agent"] = [{"agent": "claude", "label": "Claude Code", "cost": 101.0,
                      "tokens": {"total": 1010000}, "sessions": 2}]
    p["by_day"] = [
        {"day": "2026-10-01", "cost": 100.0, "tokens": 1000000,
         "by_agent": {"claude": 100.0}, "by_agent_tokens": {"claude": 1000000}},
        {"day": "2026-11-20", "cost": 1.0, "tokens": 10000,
         "by_agent": {"claude": 1.0}, "by_agent_tokens": {"claude": 10000}},
    ]
    p["by_model"] = [{"model": "claude-opus-5-5", "agent": "claude", "cost": 101.0,
                      "tokens": {"total": 1010000}}]
    p["sessions_detail"] = [
        {"id": "s0", "agent": "claude", "started": "2026-10-01T10:00:00Z", "ended": "2026-10-01T11:00:00Z",
         "cost": 100.0, "tokens": {"total": 1000000}, "models": ["claude-opus-5-5"]},
        {"id": "s1", "agent": "claude", "started": "2026-11-20T10:00:00Z", "ended": "2026-11-20T11:00:00Z",
         "cost": 1.0, "tokens": {"total": 10000}, "models": ["claude-opus-5-5"]},
    ]
    doc["buckets"]["unattributed"] = {"cost": 0.0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []}
    doc["totals"] = {"cost": 101.0, "tokens": {"total": 1010000}, "sessions": 2}
    return doc


class ProjectDetailByModelRangeTest(unittest.TestCase):
    def test_by_model_follows_selected_range(self):
        doc = big_old_model_doc()
        for tr in (TimeRange.TODAY, TimeRange.DAYS_7, TimeRange.DAYS_30):
            state = TUIState(version="test", time_range=tr, detail_open=True, detail_project=doc["projects"][0])
            vm = ViewModelCache().get_or_build(doc, state, now=NOW).detail_vm
            self.assertEqual(vm.cost_str, "$1.00", msg=tr)
            self.assertEqual([m[2] for m in vm.by_model], ["$1.00"], msg=tr)

    def test_by_model_all_time_unchanged(self):
        doc = big_old_model_doc()
        state = TUIState(version="test", time_range=TimeRange.ALL, detail_open=True, detail_project=doc["projects"][0])
        vm = ViewModelCache().get_or_build(doc, state, now=NOW).detail_vm
        self.assertEqual([m[2] for m in vm.by_model], ["$101.00"])


class SlowFakeStdscr(FakeStdscr):
    """Returns no key for ``seconds`` (pacing like a real getch timeout), then quits."""

    def __init__(self, seconds: float, **kw):
        super().__init__(**kw)
        self.deadline = time.monotonic() + seconds

    def getch(self):
        if time.monotonic() < self.deadline:
            time.sleep(0.01)
            return -1
        return ord("q")


@unittest.skipIf(curses is None, "requires curses")
class FailedFirstRefreshTest(unittest.TestCase):
    def test_loading_screen_shows_refresh_error(self):
        scr = SlowFakeStdscr(0.8, width=80, height=24)
        with mock.patch("kanjo.tui.term.run_export_subprocess", side_effect=RuntimeError("boom")):
            rc = run_curses_tui(scr, initial_doc=None, no_color=True, mouse=False)
        self.assertEqual(rc, 0)
        frames = screen_frames(scr)
        self.assertTrue(any("Refresh failed: boom" in fr for fr in frames))
        last = frames[-1]
        self.assertIn("Refresh failed: boom", last)
        self.assertNotIn("Loading", last)


class HeatLowestLevelTest(unittest.TestCase):
    def test_8w_strip_draws_level_one(self):
        # NOW is Friday 2026-11-20; this Monday is 2026-11-16, last Monday 2026-11-09.
        by_day = [{"day": "2026-11-16", "cost": 100.0}, {"day": "2026-11-09", "cost": 10.0}]
        strip = compute_8w_strip(by_day, NOW, timezone.utc)
        self.assertEqual(strip[7][0], "\u2588")
        self.assertNotEqual(strip[6][0], " ")
        self.assertEqual(strip[5][0], " ")

    def test_30d_sparkline_draws_level_one(self):
        by_day = [{"day": "2026-11-20", "cost": 100.0}, {"day": "2026-11-19", "cost": 12.0}]
        spark, peak = compute_30d_sparkline(by_day, NOW, timezone.utc)
        self.assertEqual(peak, 100.0)
        self.assertNotEqual(spark[-2], " ")
        self.assertEqual(spark[-3], " ")


def low_colour_manager(colors: int) -> "ColorManager":
    cm = ColorManager(no_color=True)
    cm.no_color = False
    cm.can_color = True
    cm.colors_256 = colors >= 256
    cm.colors_16 = colors >= 16
    return cm


@unittest.skipIf(curses is None, "requires curses")
class LowColourTerminalTest(unittest.TestCase):
    def test_gray_is_not_black_on_8_colours(self):
        cm = low_colour_manager(8)
        self.assertNotEqual(cm.color_to_curses("gray"), cm.color_to_curses("black"))

    def test_gray_is_bright_black_on_16_colours(self):
        self.assertEqual(low_colour_manager(16).color_to_curses("gray"), 8)

    def test_agent_colours_never_black_on_8_colours(self):
        cm = low_colour_manager(8)
        for agent, rgb in AGENT_COLORS.items():
            self.assertNotEqual(cm.color_to_curses(rgb), curses.COLOR_BLACK, msg=agent)

    def test_selected_row_visible_on_8_colours(self):
        cm = low_colour_manager(8)
        with mock.patch("kanjo.tui.term.curses.init_pair"):
            pair, extra = cm.pair_and_attrs(Style(bold=True, fg="white", bg=SELECTED_ROW_BG))
        self.assertTrue(extra & curses.A_REVERSE)
        fg, bg = next(k for k, v in cm.pair_cache.items() if v == pair)
        self.assertEqual(bg, -1)

    def test_selected_row_uses_gray_bg_on_256_colours(self):
        cm = low_colour_manager(256)
        with mock.patch("kanjo.tui.term.curses.init_pair"):
            pair, extra = cm.pair_and_attrs(Style(bold=True, fg="white", bg=SELECTED_ROW_BG))
        self.assertEqual(extra, 0)
        self.assertIn((curses.COLOR_WHITE, 8), cm.pair_cache)


class EndedQuotaWindowTest(unittest.TestCase):
    def _doc(self, quota: dict) -> dict:
        doc = synthetic_doc()
        doc["subscriptions"] = {"claude": {"plan_label": "Max", "monthly_price_usd": 100}}
        doc["quota_windows"] = {"claude": quota}
        return doc

    def test_ended_five_hour_window_shows_window_ended(self):
        doc = self._doc({"weekly_resets_at": "2026-11-23T00:00:00Z", "weekly_window_hours": 168,
                         "weekly_used_percent": 57, "five_hour_window_hours": 5,
                         "five_hour_resets_at": None, "five_hour_used_percent": None})
        windows = build_subscription_meters(doc, now=NOW)[0].windows
        five = [w for w in windows if w.name == "5-hour"]
        self.assertEqual(len(five), 1, msg=[w.name for w in windows])
        self.assertIsNone(five[0].percent)
        self.assertEqual(five[0].detail, "window ended")

    def test_ended_extra_window_shows_window_ended(self):
        doc = self._doc({"weekly_resets_at": "2026-11-23T00:00:00Z", "weekly_window_hours": 168,
                         "extra_windows": [{"id": "custom-5h", "title": "Custom 5h",
                                            "resets_at": None, "used_percent": 40}]})
        windows = build_subscription_meters(doc, now=NOW)[0].windows
        extra = [w for w in windows if w.name == "Custom 5h"]
        self.assertEqual(len(extra), 1, msg=[w.name for w in windows])
        self.assertIsNone(extra[0].percent)
        self.assertEqual(extra[0].detail, "window ended")


class TotalLastActiveTest(unittest.TestCase):
    def test_total_last_active_includes_buckets(self):
        doc = synthetic_doc()
        self.assertEqual(filter_report(doc, TimeRange.ALL, now=NOW).last_active, "2026-11-20")
        self.assertEqual(filter_report(doc, TimeRange.TODAY, now=NOW).last_active, "2026-11-20")
        self.assertEqual(filter_report(doc, TimeRange.DAYS_7, now=NOW).first_active, "2026-11-18")


if __name__ == "__main__":
    unittest.main()
