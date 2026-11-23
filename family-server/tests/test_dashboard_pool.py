"""Dashboard aggregation tests that call generate_dashboard_html directly."""

import copy
from datetime import datetime, timezone
import json
import os
import re
import tempfile
import unittest

from family_server import dashboard, db

NOW = datetime(2026, 11, 21, 17, 0, tzinfo=timezone.utc)


def _day(period, agent, provider, model, tokens, cost=1.0):
    return {
        "period": period,
        "first_day": period,
        "last_day": period,
        "tokens": {"input": tokens, "output": 0, "cache_read": 0, "cache_write": 0, "total": tokens},
        "cost_usd": cost,
        "by_provider": [{
            "provider": provider, "label": provider,
            "tokens": {"input": tokens, "output": 0, "cache_read": 0, "cache_write": 0, "total": tokens},
            "cost_usd": cost,
            "models": [{"model": model, "tokens_total": tokens, "cost_usd": cost}],
        }],
        "by_agent": [{"agent": agent, "label": agent, "tokens_total": tokens, "cost_usd": cost}],
        "top_models": [{"model": model, "provider": provider, "tokens_total": tokens, "cost_usd": cost}],
    }


class DashboardPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(__file__), "fixtures", "report.json")
        with open(path, "r", encoding="utf-8") as f:
            cls.fixture = json.load(f)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "pool.db")
        db.init_db(self.db_path)
        dashboard._cached_dashboard_merge.cache_clear()

    def tearDown(self):
        self.tmp.cleanup()

    def _payload(self, label, days, scope=None, quota=None):
        data = copy.deepcopy(self.fixture)
        data["member_label"] = label
        data["summary"]["days"] = days
        data["quota_windows"] = quota if quota is not None else {}
        if scope is not None:
            data["scope"] = scope
        return data

    def _add(self, name, payload, received_at=None):
        with db.get_connection(self.db_path) as conn:
            _, mid = db.add_member(conn, name)
            db.insert_report(conn, mid, payload["generated_at"], json.dumps(payload),
                             received_at=(received_at or NOW).isoformat())
        return mid

    def _section(self, html, title):
        start = html.index(title)
        end = html.index("</section>", start)
        return html[start:end]

    def test_pool_share_ignores_days_without_antigravity_usage(self):
        self._add("Alice", self._payload(
            "a", [_day("2026-11-20", "antigravity", "google", "gemini-3.8-pro", 100000)],
            quota=self._ag_quota(45.0)))
        self._add("Bob", self._payload(
            "b", [_day("2026-11-20", "claude", "anthropic", "claude-opus-5.5", 900000)],
            scope={"agents": ["all"]}))

        html = dashboard.generate_dashboard_html(self.db_path, now=NOW)
        share = self._section(html, "重置以来谁用掉了额度池")
        self.assertNotIn("Bob", share)
        self.assertIn("100.0k tokens (100.0%)", share)

    def test_pool_tokens_fall_back_to_total_only_without_breakdown(self):
        day = {"period": "2026-11-20", "tokens": {"total": 5000}}
        self.assertEqual(dashboard.pool_tokens_for_day(day, 5000), 5000)
        day = _day("2026-11-20", "claude", "anthropic", "claude-opus-5.5", 5000)
        self.assertEqual(dashboard.pool_tokens_for_day(day, 5000), 0)

    def test_cycle_models_table_has_no_all_time_fallback(self):
        payload = self._payload(
            "a", [_day("2026-10-15", "antigravity", "google", "gemini-3.8-pro", 50000000, 1234.56)])
        payload["summary"]["all_time"]["top_models"] = [
            {"model": "gemini-3.8-pro", "provider": "google", "tokens_total": 50000000, "cost_usd": 1234.56}]
        self._add("Alice", payload)
        with db.get_connection(self.db_path) as conn:
            db.set_setting(conn, "cycle_anchor_day", "9")
            db.set_setting(conn, "tracking_start", "2026-11-09")

        html = dashboard.generate_dashboard_html(self.db_path, now=NOW, range_key="cycle")
        self.assertIn("该时段暂无模型用量明细", html)
        self.assertNotIn("50.00M", html)
        self.assertNotIn("$1,234.56", html)

    def _ag_quota(self, weekly):
        return {"antigravity": {"weekly_resets_at": "2026-11-24T12:00:00Z", "weekly_window_hours": 168,
                                "weekly_used_percent": weekly}}

    def test_unknown_weekly_percent_is_not_zero_and_not_a_disagreement(self):
        self._add("Alice", self._payload("a", [], quota=self._ag_quota(45.0)))
        self._add("Bob", self._payload("b", [], quota=self._ag_quota(None)))
        html = dashboard.generate_dashboard_html(self.db_path, now=NOW)
        self.assertNotIn("数值不一致", html)
        self.assertNotIn("周额度已用：<strong>0.0%</strong>", html)

    def test_unknown_weekly_percent_renders_as_unknown_in_member_grid(self):
        self._add("Alice", self._payload("a", [], quota=self._ag_quota(45.0)))
        self._add("Bob", self._payload("b", [], quota=self._ag_quota(None)))
        self._add("Carol", self._payload("c", [], quota=self._ag_quota(10.0)))
        html = dashboard.generate_dashboard_html(self.db_path, now=NOW)
        self.assertIn("数值不一致", html)
        self.assertIn("周额度已用：<strong>未知</strong>", html)
        self.assertNotIn("周额度已用：<strong>0.0%</strong>", html)

    def test_out_of_range_reset_timestamp_does_not_crash_dashboard(self):
        for i, value in enumerate(("0001-01-01T00:00:00Z", "9999-12-31T23:00:00-05:00")):
            with self.subTest(value=value):
                self.db_path = os.path.join(self.tmp.name, "range%d.db" % i)
                db.init_db(self.db_path)
                quota = {"antigravity": {"weekly_resets_at": value, "weekly_used_percent": 10.0,
                                         "five_hour_resets_at": value, "five_hour_used_percent": 1.0,
                                         "extra_windows": [{"id": "3p-weekly", "used_percent": 5.0,
                                                            "resets_at": value}]}}
                self._add("Alice", self._payload("a", [], quota=self._ag_quota(60.0)),
                          received_at=NOW.replace(hour=1))
                self._add("Bob", self._payload("b", [], quota=quota))
                html = dashboard.generate_dashboard_html(self.db_path, now=NOW)
                self.assertIn("数据来自 Bob 的最新上报", html)


if __name__ == "__main__":
    unittest.main()


class ResetCountdownTests(DashboardPoolTests):
    def test_countdown_text_formats(self):
        from datetime import timedelta
        from family_server.dashboard_view import countdown_text
        self.assertEqual(countdown_text(NOW + timedelta(days=2, hours=19, minutes=5), NOW), "2 天 19 小时 5 分")
        self.assertEqual(countdown_text(NOW + timedelta(hours=3, minutes=7), NOW), "3 小时 7 分")
        self.assertEqual(countdown_text(NOW + timedelta(minutes=12), NOW), "12 分钟")
        self.assertEqual(countdown_text(NOW + timedelta(seconds=30), NOW), "不到 1 分钟")
        self.assertEqual(countdown_text(NOW - timedelta(minutes=1), NOW), "已到重置时间")

    def test_header_and_pool_show_live_countdown_to_next_reset(self):
        quota = self._ag_quota(45.0)
        # Weekly reset 2026-11-24 12:00Z is 2 d 19 h away; the 5-hour window resets sooner.
        quota["antigravity"].update({"five_hour_resets_at": "2026-11-21T19:30:00Z",
                                     "five_hour_window_hours": 5, "five_hour_used_percent": 10.0})
        self._add("Alice", self._payload("a", [], quota=quota))
        html = dashboard.generate_dashboard_html(self.db_path, now=NOW)
        self.assertIn('class="reset-pill"', html)
        self.assertIn('data-reset-at="2026-11-24T12:00:00Z">2 天 19 小时 0 分</span>', html)
        self.assertIn('class="cd-value"', html)
        self.assertIn("距下次重置", html)

    def test_no_reset_pill_without_upcoming_reset(self):
        self._add("Alice", self._payload("a", [], quota={}))
        html = dashboard.generate_dashboard_html(self.db_path, now=NOW)
        self.assertNotIn('class="reset-pill"', html)
