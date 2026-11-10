"""Unit tests for the Tailscale dashboard rendering and HTML escaping."""

import copy
from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request

from family_server import db
from family_server.server import start_servers, stop_servers


class TestDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "report.json")
        with open(cls.fixture_path, "r", encoding="utf-8") as f:
            cls.fixture_data = json.load(f)

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "dash_test.db")
        db.init_db(self.db_path)

        with db.get_connection(self.db_path) as conn:
            self.session_id = db.create_session(conn, "admin@paytonpei.top")

        self.api_server, self.dash_server, self.api_port, self.dash_port = start_servers(
            db_path=self.db_path,
            api_host="127.0.0.1",
            api_port=0,
            dashboard_host="127.0.0.1",
            dashboard_port=0,
            admin_emails={"admin@paytonpei.top"},
        )

    def tearDown(self):
        stop_servers(self.api_server, self.dash_server)
        self.tmp_dir.cleanup()

    def _dash_request(self, path: str, headers: dict = None, auth: bool = True):
        url = f"http://127.0.0.1:{self.dash_port}{path}"
        req_headers = {}
        if auth and hasattr(self, "session_id"):
            req_headers["Cookie"] = f"__Host-family_session={self.session_id}"
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, headers=req_headers, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def test_dashboard_empty_state(self):
        status, html = self._dash_request("/")
        self.assertEqual(status, 200)
        self.assertIn("家庭用量汇总", html)
        self.assertIn("尚未添加任何成员", html)
        self.assertIn("按公开 API 价格折算，不是实际支出", html)

    def test_dashboard_healthz_and_404(self):
        status, body = self._dash_request("/healthz")
        self.assertEqual(status, 200)
        self.assertIn('"status"', body)

        status, _ = self._dash_request("/unknown-path")
        self.assertEqual(status, 404)

    def test_pool_card_uses_freshest_report_and_lists_all_windows(self):
        from datetime import timedelta
        reset = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def report(weekly, label):
            data = json.loads(json.dumps(self.fixture_data))
            data["member_label"] = label
            data["quota_windows"] = {"antigravity": {
                "weekly_resets_at": reset, "weekly_window_hours": 168, "weekly_used_percent": weekly,
                "five_hour_resets_at": reset, "five_hour_window_hours": 5, "five_hour_used_percent": 3.0,
                "extra_windows": [
                    {"id": "3p-weekly", "label": "Weekly Limit Remaining", "used_percent": 50.4, "resets_at": reset},
                    {"id": "3p-5h", "label": "Five Hour Limit Remaining", "used_percent": 2.0, "resets_at": reset},
                ],
            }}
            return json.dumps(data)

        now = datetime.now(timezone.utc)
        with db.get_connection(self.db_path) as conn:
            _, a = db.add_member(conn, "Alice")
            _, b = db.add_member(conn, "Bob")
            db.insert_report(conn, a, self.fixture_data["generated_at"], report(10.0, "a"),
                             received_at=(now - timedelta(hours=2)).isoformat())
            db.insert_report(conn, b, self.fixture_data["generated_at"], report(30.0, "b"),
                             received_at=now.isoformat())

        status, html = self._dash_request("/")
        self.assertEqual(status, 200)
        # Freshest report (Bob) decides the pool numbers.
        self.assertIn("数据来自 Bob 的最新上报", html)
        self.assertIn("已用 <strong>30.0%</strong>", html)
        self.assertIn("Gemini 模型 · 5 小时", html)
        self.assertIn("Claude / GPT 模型 · 本周", html)
        self.assertIn("已用 <strong>50.4%</strong>", html)
        self.assertIn("Claude / GPT 模型 · 5 小时", html)
        # Members disagree by more than 2 points -> per-member list shown.
        self.assertIn("数值不一致", html)
        # Reset times are shown in the dashboard timezone (default America/Toronto), not UTC.
        from zoneinfo import ZoneInfo
        reset_dt = datetime.strptime(reset, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        local = reset_dt.astimezone(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d %H:%M")
        self.assertIn("重置：" + local, html)

    def test_dashboard_renders_with_fixture_report(self):
        # Add members and reports
        with db.get_connection(self.db_path) as conn:
            _, m_alice = db.add_member(conn, "Alice")
            now_iso = datetime.now(timezone.utc).isoformat()
            db.insert_report(
                conn,
                m_alice,
                self.fixture_data["generated_at"],
                json.dumps(self.fixture_data),
                received_at=now_iso,
            )

        status, html = self._dash_request("/")
        self.assertEqual(status, 200)

        # 1. Quota pool section
        self.assertIn("Google AI Ultra 额度池（全家共用）", html)
        self.assertIn("42.5%", html)
        self.assertIn("Gemini 模型 · 本周", html)
        self.assertIn("数据来自 Alice 的最新上报", html)
        self.assertIn("本额度周", html)

        # 2. Who used the quota pool
        self.assertIn("本周期谁用掉了额度池", html)
        self.assertIn("Alice", html)

        # 3. 30-day SVG bar chart
        self.assertIn("<svg", html)
        self.assertIn("class=\"chart-svg\"", html)
        self.assertIn("<rect", html)

        # 4. Member card
        self.assertIn("本周期", html)
        self.assertIn("上周期", html)
        self.assertIn("剩余天数", html)
        self.assertIn("gemini-3.8-pro", html)
        self.assertIn("claude-opus-5.5", html)

        # Cost note
        self.assertIn("按公开 API 价格折算，不是实际支出", html)

    def test_dashboard_escapes_html_in_labels_and_names(self):
        """Ensure XSS strings in member names and client-supplied labels are escaped."""
        xss_name = "<script>alert('xss-name')</script>"
        xss_label = "<b onmouseover='alert(1)'>HackerLabel</b>"
        xss_model = "<img src=x onerror=alert(2)>"

        malicious_payload = copy.deepcopy(self.fixture_data)
        malicious_payload["member_label"] = xss_label
        malicious_payload["summary"]["all_time"]["top_models"][0]["model"] = xss_model
        for d in malicious_payload.get("summary", {}).get("days", []):
            for tm in d.get("top_models", []):
                tm["model"] = xss_model

        with db.get_connection(self.db_path) as conn:
            _, m_id = db.add_member(conn, xss_name)
            now_iso = datetime.now(timezone.utc).isoformat()
            db.insert_report(
                conn,
                m_id,
                malicious_payload["generated_at"],
                json.dumps(malicious_payload),
                received_at=now_iso,
            )

        status, html = self._dash_request("/")
        self.assertEqual(status, 200)

        # Must NOT contain raw unescaped HTML tags
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b onmouseover", html)
        self.assertNotIn("<img src=x", html)

        # MUST contain properly escaped entities
        self.assertIn("&lt;script&gt;alert(&#x27;xss-name&#x27;)&lt;/script&gt;", html)
        self.assertIn("&lt;b onmouseover=&#x27;alert(1)&#x27;&gt;HackerLabel&lt;/b&gt;", html)
        self.assertIn("&lt;img src=x onerror=alert(2)&gt;", html)

    def test_dashboard_stale_indicator(self):
        """Reports older than 24 hours must show stale badge."""
        with db.get_connection(self.db_path) as conn:
            _, m_fresh = db.add_member(conn, "FreshUser")
            _, m_stale = db.add_member(conn, "StaleUser")

            now = datetime.now(timezone.utc)
            # Fresh: reported 10 minutes ago
            db.insert_report(
                conn,
                m_fresh,
                now.isoformat(),
                json.dumps(self.fixture_data),
                received_at=(now - timedelta(minutes=10)).isoformat(),
            )
            # Stale: reported 30 hours ago (> 24h)
            db.insert_report(
                conn,
                m_stale,
                now.isoformat(),
                json.dumps(self.fixture_data),
                received_at=(now - timedelta(hours=30)).isoformat(),
            )

        status, html = self._dash_request("/")
        self.assertEqual(status, 200)
        self.assertIn("badge-active", html)
        self.assertIn("badge-stale", html)
        self.assertIn("未更新", html)

    def test_dashboard_shows_scope_at_top_and_on_card(self):
        payload = copy.deepcopy(self.fixture_data)
        payload["scope"] = {"agents": ["antigravity"], "since": "2026-11-09"}

        with db.get_connection(self.db_path) as conn:
            _, m_id = db.add_member(conn, "Alice")
            now_iso = datetime.now(timezone.utc).isoformat()
            db.insert_report(
                conn,
                m_id,
                payload["generated_at"],
                json.dumps(payload),
                received_at=now_iso,
            )

        status, html = self._dash_request("/")
        self.assertEqual(status, 200)
        expected_scope = "统计范围：Antigravity · 自 2026-11-09 起"
        self.assertIn(expected_scope, html)
        # Should be in top scope notice and in member card scope
        self.assertIn('class="scope-notice"', html)
        self.assertIn('class="member-scope"', html)

    def test_dashboard_escapes_html_in_scope(self):
        xss_scope = {
            "agents": ["<script>alert('scope-agent')</script>"],
            "since": "<img src=x onerror=alert(3)>",
        }
        malicious_payload = copy.deepcopy(self.fixture_data)
        malicious_payload["scope"] = xss_scope

        with db.get_connection(self.db_path) as conn:
            _, m_id = db.add_member(conn, "Eve")
            now_iso = datetime.now(timezone.utc).isoformat()
            db.insert_report(
                conn,
                m_id,
                malicious_payload["generated_at"],
                json.dumps(malicious_payload),
                received_at=now_iso,
            )

        status, html = self._dash_request("/")
        self.assertEqual(status, 200)
        self.assertNotIn("<script>alert('scope-agent')</script>", html)
        self.assertNotIn("<img src=x onerror=alert(3)>", html)
        self.assertIn("&lt;script&gt;alert(&#x27;scope-agent&#x27;)&lt;/script&gt;", html)
        self.assertIn("&lt;img src=x onerror=alert(3)&gt;", html)


if __name__ == "__main__":
    unittest.main()
