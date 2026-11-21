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
            "a", [_day("2026-11-20", "antigravity", "google", "gemini-3.8-pro", 100000)]))
        self._add("Bob", self._payload(
            "b", [_day("2026-11-20", "claude", "anthropic", "claude-opus-5.5", 900000)],
            scope={"agents": ["all"]}))

        html = dashboard.generate_dashboard_html(self.db_path, now=NOW)
        share = self._section(html, "本周期谁用掉了额度池")
        self.assertNotIn("Bob", share)
        self.assertIn("100.0k tokens (100.0%)", share)

    def test_pool_tokens_fall_back_to_total_only_without_breakdown(self):
        day = {"period": "2026-11-20", "tokens": {"total": 5000}}
        self.assertEqual(dashboard.pool_tokens_for_day(day, 5000), 5000)
        day = _day("2026-11-20", "claude", "anthropic", "claude-opus-5.5", 5000)
        self.assertEqual(dashboard.pool_tokens_for_day(day, 5000), 0)


if __name__ == "__main__":
    unittest.main()
