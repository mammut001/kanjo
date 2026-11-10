"""Unit and integration tests for manager-set billing cycles, settings, and tracking_start."""

import copy
from datetime import date, datetime, timedelta, timezone
import json
import logging
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from family_server import db
from family_server.dashboard import compute_cycle_boundaries, generate_dashboard_html
from family_server.server import start_servers, stop_servers


class TestCycleBoundariesMath(unittest.TestCase):
    """Test boundary math for compute_cycle_boundaries."""

    def test_anchor_31_in_feb_leap_year(self):
        # 2024 is a leap year; Feb has 29 days
        prev_start, curr_start, next_start = compute_cycle_boundaries(31, date(2024, 2, 15))
        self.assertEqual(prev_start, date(2023, 12, 31))
        self.assertEqual(curr_start, date(2024, 1, 31))
        self.assertEqual(next_start, date(2024, 2, 29))

        # On Feb 29 itself, anchor 31 is clamped to 29, so it marks the start of the new cycle
        prev_start, curr_start, next_start = compute_cycle_boundaries(31, date(2024, 2, 29))
        self.assertEqual(prev_start, date(2024, 1, 31))
        self.assertEqual(curr_start, date(2024, 2, 29))
        self.assertEqual(next_start, date(2024, 3, 31))

    def test_anchor_31_in_feb_non_leap_year(self):
        # 2025 is not a leap year; Feb has 28 days
        prev_start, curr_start, next_start = compute_cycle_boundaries(31, date(2025, 2, 15))
        self.assertEqual(prev_start, date(2024, 12, 31))
        self.assertEqual(curr_start, date(2025, 1, 31))
        self.assertEqual(next_start, date(2025, 2, 28))

        # On Feb 28 itself
        prev_start, curr_start, next_start = compute_cycle_boundaries(31, date(2025, 2, 28))
        self.assertEqual(prev_start, date(2025, 1, 31))
        self.assertEqual(curr_start, date(2025, 2, 28))
        self.assertEqual(next_start, date(2025, 3, 31))

    def test_anchor_31_in_april(self):
        # April has 30 days
        prev_start, curr_start, next_start = compute_cycle_boundaries(31, date(2026, 4, 15))
        self.assertEqual(prev_start, date(2026, 2, 28))
        self.assertEqual(curr_start, date(2026, 3, 31))
        self.assertEqual(next_start, date(2026, 4, 30))

        # On April 30
        prev_start, curr_start, next_start = compute_cycle_boundaries(31, date(2026, 4, 30))
        self.assertEqual(prev_start, date(2026, 3, 31))
        self.assertEqual(curr_start, date(2026, 4, 30))
        self.assertEqual(next_start, date(2026, 5, 31))

    def test_anchor_on_today(self):
        # Today is Nov 9 and anchor is 9: starts today
        prev_start, curr_start, next_start = compute_cycle_boundaries(9, date(2026, 11, 9))
        self.assertEqual(prev_start, date(2026, 10, 9))
        self.assertEqual(curr_start, date(2026, 11, 9))
        self.assertEqual(next_start, date(2026, 12, 9))

        # Day before anchor: Nov 8 with anchor 9
        prev_start, curr_start, next_start = compute_cycle_boundaries(9, date(2026, 11, 8))
        self.assertEqual(prev_start, date(2026, 9, 9))
        self.assertEqual(curr_start, date(2026, 10, 9))
        self.assertEqual(next_start, date(2026, 11, 9))

    def test_anchor_dst_timezone(self):
        tz = ZoneInfo("America/Toronto")
        # In UTC, 2026-03-08 04:00:00 is 2026-03-07 23:00:00 EST (UTC-5)
        dt_pre = datetime(2026, 3, 8, 4, 0, 0, tzinfo=timezone.utc)
        prev_start, curr_start, next_start = compute_cycle_boundaries(8, dt_pre, tz=tz)
        self.assertEqual(curr_start, date(2026, 2, 8))
        self.assertEqual(next_start, date(2026, 3, 8))

        # In UTC, 2026-03-08 05:01:00 is 2026-03-08 00:01:00 EST
        dt_post = datetime(2026, 3, 8, 5, 1, 0, tzinfo=timezone.utc)
        prev_start, curr_start, next_start = compute_cycle_boundaries(8, dt_post, tz=tz)
        self.assertEqual(curr_start, date(2026, 3, 8))
        self.assertEqual(next_start, date(2026, 4, 8))

    def test_anchor_none_fallback_to_calendar_month(self):
        prev_start, curr_start, next_start = compute_cycle_boundaries(None, date(2026, 11, 15))
        self.assertEqual(prev_start, date(2026, 10, 1))
        self.assertEqual(curr_start, date(2026, 11, 1))
        self.assertEqual(next_start, date(2026, 12, 1))


class TestTrackingStartFiltering(unittest.TestCase):
    """Test that tracking_start excludes usage before it everywhere on dashboard."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "dash_filter_test.db")
        db.init_db(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_tracking_start_filtering_everywhere(self):
        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "report.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Alice has daily data. Let's create a controlled test payload with 4 days:
        # 2026-11-01: 1000 tokens
        # 2026-11-05: 2000 tokens
        # 2026-11-08: 3000 tokens
        # 2026-11-09: 4000 tokens
        test_payload = copy.deepcopy(data)
        test_payload["summary"]["days"] = [
            {
                "period": "2026-11-01",
                "tokens": {"total": 1000},
                "cost_usd": 0.10,
                "by_agent": [{"agent": "antigravity", "tokens_total": 1000}],
                "top_models": [{"model": "gemini-3.8-pro", "tokens_total": 1000, "cost_usd": 0.10}],
            },
            {
                "period": "2026-11-05",
                "tokens": {"total": 2000},
                "cost_usd": 0.20,
                "by_agent": [{"agent": "antigravity", "tokens_total": 2000}],
                "top_models": [{"model": "gemini-3.8-pro", "tokens_total": 2000, "cost_usd": 0.20}],
            },
            {
                "period": "2026-11-08",
                "tokens": {"total": 3000},
                "cost_usd": 0.30,
                "by_agent": [{"agent": "antigravity", "tokens_total": 3000}],
                "top_models": [{"model": "gemini-3.8-pro", "tokens_total": 3000, "cost_usd": 0.30}],
            },
            {
                "period": "2026-11-09",
                "tokens": {"total": 4000},
                "cost_usd": 0.40,
                "by_agent": [{"agent": "antigravity", "tokens_total": 4000}],
                "top_models": [{"model": "gemini-3.8-pro", "tokens_total": 4000, "cost_usd": 0.40}],
            },
        ]

        with db.get_connection(self.db_path) as conn:
            _, m_id = db.add_member(conn, "Alice")
            now_iso = "2026-11-09T20:00:00Z"
            db.insert_report(conn, m_id, now_iso, json.dumps(test_payload), received_at=now_iso)

            # Set cycle anchor to 1, and tracking_start to 2026-11-08
            # This should ignore 2026-11-01 and 2026-11-05 (totaling 3000 tokens)
            # Cycle tokens should only include 2026-11-08 (3000) and 2026-11-09 (4000) = 7000 tokens ($0.70)
            db.set_setting(conn, "cycle_anchor_day", "1")
            db.set_setting(conn, "tracking_start", "2026-11-08")
            db.set_setting(conn, "timezone", "America/Toronto")

        fixed_now = datetime(2026, 11, 9, 20, 0, 0, tzinfo=timezone.utc)
        html = generate_dashboard_html(self.db_path, now=fixed_now)

        # Check cycle tokens: 7.0k tokens ($0.70)
        self.assertIn("7.0k", html)
        self.assertIn("$0.70", html)
        # 10.0k (total with filtered days) must NOT appear as cycle tokens
        self.assertNotIn("10.0k", html)
        self.assertNotIn("$1.00", html)


class TestSettingsAuthCsrfValidation(unittest.TestCase):
    """Test /settings authentication, CSRF checks, validation, and PII-free logging."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "dash_settings_test.db")
        db.init_db(self.db_path)

        with db.get_connection(self.db_path) as conn:
            self.admin_session = db.create_session(conn, "admin@paytonpei.top")
            self.member_session = db.create_session(conn, "member@paytonpei.top")

        self.api_server, self.dash_server, self.api_port, self.dash_port = start_servers(
            db_path=self.db_path,
            api_host="127.0.0.1",
            api_port=0,
            dashboard_host="127.0.0.1",
            dashboard_port=0,
            admin_emails={"admin@paytonpei.top"},
            public_origin="https://usage.paytonpei.top",
        )

    def tearDown(self):
        stop_servers(self.api_server, self.dash_server)
        self.tmp_dir.cleanup()

    def _request(self, method: str, path: str, data: dict = None, session_id: str = None, headers: dict = None):
        url = f"http://127.0.0.1:{self.dash_port}{path}"
        req_headers = {}
        if session_id:
            req_headers["Cookie"] = f"__Host-family_session={session_id}"
        if headers:
            req_headers.update(headers)

        body_bytes = None
        if data is not None:
            if req_headers.get("Content-Type") == "application/json":
                body_bytes = json.dumps(data).encode("utf-8")
            else:
                body_bytes = urllib.parse.urlencode(data).encode("utf-8")
                req_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

        req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)

        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirectHandler)
        try:
            with opener.open(req) as resp:
                return resp.status, resp.read().decode("utf-8"), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8"), e.headers

    def test_settings_unauthenticated(self):
        # GET /settings unauthenticated redirects to /login
        status, body, headers = self._request("GET", "/settings")
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/login")

        # POST /settings unauthenticated
        status, body, headers = self._request("POST", "/settings", data={"cycle_anchor_day": "9"})
        # Fails CSRF or auth with 403 or 302
        self.assertIn(status, (401, 403, 302))

    def test_settings_forbidden_for_non_admin(self):
        # GET /settings as regular member -> 403
        status, body, _ = self._request("GET", "/settings", session_id=self.member_session)
        self.assertEqual(status, 403)
        self.assertIn("Admin access required", body)

        # POST /settings as regular member -> 403
        headers = {"Origin": "https://usage.paytonpei.top"}
        status, body, _ = self._request(
            "POST",
            "/settings",
            data={"cycle_anchor_day": "9"},
            session_id=self.member_session,
            headers=headers,
        )
        self.assertEqual(status, 403)
        self.assertIn("Admin access required", body)

    def test_settings_csrf_protection(self):
        # POST with wrong origin -> 403 Forbidden
        headers = {"Origin": "https://attacker.example.com"}
        status, body, _ = self._request(
            "POST",
            "/settings",
            data={"cycle_anchor_day": "9"},
            session_id=self.admin_session,
            headers=headers,
        )
        self.assertEqual(status, 403)
        self.assertIn("CSRF", body)

        # POST without Origin and without Sec-Fetch-Site: same-origin -> 403 Forbidden
        status, body, _ = self._request(
            "POST",
            "/settings",
            data={"cycle_anchor_day": "9"},
            session_id=self.admin_session,
        )
        self.assertEqual(status, 403)
        self.assertIn("CSRF", body)

    def test_settings_validation_errors(self):
        headers = {"Origin": "https://usage.paytonpei.top", "Accept": "application/json", "Content-Type": "application/json"}

        # Bad anchor day: 0
        status, body, _ = self._request(
            "POST",
            "/settings",
            data={"cycle_anchor_day": 0, "timezone": "America/Toronto"},
            session_id=self.admin_session,
            headers=headers,
        )
        self.assertEqual(status, 400)
        self.assertIn("计费周期起始日必须在 1 至 31 之间", body)

        # Bad anchor day: 32
        status, body, _ = self._request(
            "POST",
            "/settings",
            data={"cycle_anchor_day": 32, "timezone": "America/Toronto"},
            session_id=self.admin_session,
            headers=headers,
        )
        self.assertEqual(status, 400)
        self.assertIn("计费周期起始日必须在 1 至 31 之间", body)

        # Bad anchor day: not a number
        status, body, _ = self._request(
            "POST",
            "/settings",
            data={"cycle_anchor_day": "invalid", "timezone": "America/Toronto"},
            session_id=self.admin_session,
            headers=headers,
        )
        self.assertEqual(status, 400)
        self.assertIn("必须为 1 至 31 之间的整数", body)

        # Bad timezone
        status, body, _ = self._request(
            "POST",
            "/settings",
            data={"cycle_anchor_day": 9, "timezone": "Invalid/Timezone"},
            session_id=self.admin_session,
            headers=headers,
        )
        self.assertEqual(status, 400)
        self.assertIn("时区名称无效", body)

        # Bad tracking_start: invalid format
        status, body, _ = self._request(
            "POST",
            "/settings",
            data={"cycle_anchor_day": 9, "tracking_start": "2026-99-99", "timezone": "America/Toronto"},
            session_id=self.admin_session,
            headers=headers,
        )
        self.assertEqual(status, 400)
        self.assertIn("统计起始日期格式无效", body)

    def test_settings_save_success_and_logging(self):
        # Capture logs to verify PII is not logged
        logger = logging.getLogger("family_server.dashboard")
        with self.assertLogs(logger, level="INFO") as log_capture:
            headers = {
                "Origin": "https://usage.paytonpei.top",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            status, _, resp_headers = self._request(
                "POST",
                "/settings",
                data={
                    "cycle_anchor_day": "9",
                    "tracking_start": "2026-11-09",
                    "timezone": "America/Toronto",
                },
                session_id=self.admin_session,
                headers=headers,
            )
            # Browser form POST redirects to /settings?saved=1
            self.assertEqual(status, 303)
            self.assertEqual(resp_headers.get("Location"), "/settings?saved=1")

            # Check that settings were stored in DB
            with db.get_connection(self.db_path) as conn:
                settings = db.get_all_settings(conn)
                self.assertEqual(settings.get("cycle_anchor_day"), "9")
                self.assertEqual(settings.get("tracking_start"), "2026-11-09")
                self.assertEqual(settings.get("timezone"), "America/Toronto")

            # Verify log messages do NOT contain user email or PII
            settings_log = [entry for entry in log_capture.output if "Settings updated:" in entry]
            self.assertTrue(len(settings_log) >= 1)
            for log_line in settings_log:
                self.assertNotIn("admin@paytonpei.top", log_line)
                self.assertNotIn(self.admin_session, log_line)
                self.assertIn("cycle_anchor_day=9", log_line)
                self.assertIn("tracking_start=2026-11-09", log_line)
                self.assertIn("timezone=America/Toronto", log_line)

        # GET /settings?saved=1 displays success message
        status, html, _ = self._request("GET", "/settings?saved=1", session_id=self.admin_session)
        self.assertEqual(status, 200)
        self.assertIn("设置已成功保存生效", html)


class TestDashboardCycleRendering(unittest.TestCase):
    """Test dashboard HTML rendering of manager-set cycle numbers."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "dash_cycle_test.db")
        db.init_db(self.db_path)

        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "report.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            self.fixture_data = json.load(f)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_dashboard_renders_cycle_prompt_when_unset(self):
        with db.get_connection(self.db_path) as conn:
            _, m_id = db.add_member(conn, "Alice")
            now_iso = "2026-11-09T18:00:00Z"
            db.insert_report(conn, m_id, now_iso, json.dumps(self.fixture_data), received_at=now_iso)

        fixed_now = datetime(2026, 11, 9, 18, 0, 0, tzinfo=timezone.utc)
        html = generate_dashboard_html(self.db_path, now=fixed_now, user_email="admin@paytonpei.top")

        # Prompts admin to set the cycle
        self.assertIn("尚未设置计费周期起始日，当前按自然月展示", html)
        self.assertIn("/settings", html)
        # Default calendar month
        self.assertIn("本周期 11/01 – 11/30", html)

    def test_dashboard_renders_manager_set_cycle(self):
        with db.get_connection(self.db_path) as conn:
            _, m_id = db.add_member(conn, "Alice")
            now_iso = "2026-11-09T18:00:00Z"
            db.insert_report(conn, m_id, now_iso, json.dumps(self.fixture_data), received_at=now_iso)
            db.set_setting(conn, "cycle_anchor_day", "9")
            db.set_setting(conn, "timezone", "America/Toronto")

        fixed_now = datetime(2026, 11, 9, 18, 0, 0, tzinfo=timezone.utc)
        html = generate_dashboard_html(self.db_path, now=fixed_now, user_email="admin@paytonpei.top")

        # Prompt banner is gone
        self.assertNotIn("尚未设置计费周期起始日", html)
        # Cycle header displays "本周期 11/09 – 12/08"
        self.assertIn("本周期 11/09 – 12/08", html)
        # Member card displays cycle metrics
        self.assertIn("本周期", html)
        self.assertIn("上周期", html)
        self.assertIn("剩余天数", html)
        self.assertIn("至 12/09 重置", html)
        # Header has settings link
        self.assertIn('<a href="/settings" class="settings-btn">设置</a>', html)


if __name__ == "__main__":
    unittest.main()
