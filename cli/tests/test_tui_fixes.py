"""Regression tests for verified TUI defects."""

import copy
import json
import os
import unittest
from datetime import datetime, timezone

from kanjo.tui.model import TimeRange, filter_report

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


if __name__ == "__main__":
    unittest.main()
