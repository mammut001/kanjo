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

from kanjo.tui.model import TimeRange, filter_report
from kanjo.tui.render import TUIState
from kanjo.tui.term import ViewModelCache, run_curses_tui

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


if __name__ == "__main__":
    unittest.main()
