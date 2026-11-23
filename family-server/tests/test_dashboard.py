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
            self.session_id = db.create_session(conn, "admin@example.com")

        self.firebase_config = {
            "apiKey": "fake-key",
            "authDomain": "example-family.firebaseapp.com",
            "projectId": "example-family",
        }
        self.api_server, self.dash_server, self.api_port, self.dash_port = start_servers(
            db_path=self.db_path,
            api_host="127.0.0.1",
            api_port=0,
            dashboard_host="127.0.0.1",
            dashboard_port=0,
            firebase_config=self.firebase_config,
            project_id="example-family",
            admin_emails={"admin@example.com"},
            public_origin="https://usage.example.com",
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

    def test_stored_labels_and_model_names_are_escaped(self):
        attack = "<img src=x onerror=alert(1)>"
        report = copy.deepcopy(self.fixture_data)
        report["member_label"] = attack
        report["summary"]["all_time"]["top_models"][0]["model"] = attack
        with db.get_connection(self.db_path) as conn:
            _, member = db.add_member(conn, attack)
            db.insert_report(conn, member, report["generated_at"], json.dumps(report))
        status, html = self._dash_request("/")
        self.assertEqual(status, 200)
        self.assertNotIn(attack, html)
        self.assertGreaterEqual(html.count("&lt;img src=x onerror=alert(1)&gt;"), 3)

    def test_dashboard_empty_state(self):
        status, html = self._dash_request("/")
        self.assertEqual(status, 200)
        self.assertIn("家庭用量汇总", html)
        self.assertIn("尚未添加任何成员", html)
        self.assertIn("按公开 API 价格折算，不是实际支出", html)

    def test_aggregate_cache_tracks_report_and_member_changes(self):
        from unittest.mock import patch
        from family_server import dashboard

        dashboard._cached_dashboard_merge.cache_clear()
        with db.get_connection(self.db_path) as conn:
            _, member = db.add_member(conn, "Alice")
            raw = json.dumps(self.fixture_data)
            db.insert_report(conn, member, "2026-01-01", raw, received_at="2026-01-01")
        with patch.object(dashboard, "merge_member_reports", wraps=dashboard.merge_member_reports) as merge:
            first = dashboard.generate_dashboard_html(self.db_path)
            self.assertEqual(first, dashboard.generate_dashboard_html(self.db_path))
            self.assertEqual(merge.call_count, 1)
            with db.get_connection(self.db_path) as conn:
                db.insert_report(conn, member, "2026-01-02", raw, received_at="2026-01-02")
            dashboard.generate_dashboard_html(self.db_path)
            self.assertEqual(merge.call_count, 2)
            with db.get_connection(self.db_path) as conn:
                conn.execute("UPDATE members SET name = 'Alicia' WHERE id = ?", (member,))
                conn.commit()
            self.assertIn("Alicia", dashboard.generate_dashboard_html(self.db_path))
            self.assertEqual(merge.call_count, 3)

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

        # The fixture's usage is dated before this week, so look at the "all" range.
        status, html = self._dash_request("/?range=all")
        self.assertEqual(status, 200)

        # 1. Quota pool section
        self.assertIn("Google AI Ultra 额度池（全家共用）", html)
        self.assertIn("42.5%", html)
        self.assertIn("Gemini 模型 · 本周", html)
        self.assertIn("数据来自 Alice 的最新上报", html)
        self.assertIn("本额度周", html)

        # 2. Ranking table
        self.assertIn("成员排行", html)
        self.assertIn("Alice", html)

        # 3. Trend SVG bar chart
        self.assertIn("<svg", html)
        self.assertIn("class=\"chart-svg\"", html)
        self.assertIn("<rect", html)

        # 4. Model breakdown (ranking row detail and analysis)
        self.assertIn("模型排行", html)
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

        # The fixture's usage (and the hostile model name) is dated before this week.
        status, html = self._dash_request("/?range=all")
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
        """Reports older than 2 hours must show stale badge."""
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
        self.assertIn("超过 2 小时未上报", html)

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

    def test_dashboard_sums_multiple_devices_and_renders_device_list(self):
        from zoneinfo import ZoneInfo

        now = datetime.now(timezone.utc)
        today_str = now.astimezone(ZoneInfo("America/Toronto")).date().isoformat()

        def make_dev_payload(dev_id, dev_name, dev_os, tz_name, ver, day_tok, day_cost, all_tok, all_cost, weekly_pct=None):
            p = copy.deepcopy(self.fixture_data)
            p["device"] = {"id": dev_id, "name": dev_name, "os": dev_os}
            p["timezone"] = tz_name
            p["generated_by"] = ver
            p["summary"]["all_time"]["tokens"]["total"] = all_tok
            p["summary"]["all_time"]["cost_usd"] = all_cost
            p["summary"]["days"] = [
                {
                    "period": today_str,
                    "first_day": today_str,
                    "last_day": today_str,
                    "tokens": {"input": day_tok, "output": 0, "cache_read": 0, "cache_write": 0, "total": day_tok},
                    "cost_usd": day_cost,
                    "by_provider": [{"provider": "google", "label": "Google", "tokens": {"input": day_tok, "output": 0, "cache_read": 0, "cache_write": 0, "total": day_tok}, "cost_usd": day_cost, "models": []}],
                    "by_agent": [{"agent": "antigravity", "label": "Antigravity", "tokens_total": day_tok, "cost_usd": day_cost}],
                    "top_models": [{"model": "gemini-3.8-pro", "provider": "google", "tokens_total": day_tok, "cost_usd": day_cost}],
                }
            ]
            if weekly_pct is not None:
                p["quota_windows"] = {
                    "antigravity": {
                        "weekly_resets_at": (now + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "weekly_window_hours": 168,
                        "weekly_used_percent": weekly_pct,
                    }
                }
            else:
                p["quota_windows"] = {}
            return p

        rec_mac = now - timedelta(hours=1)
        rec_linux = now - timedelta(minutes=10)
        mac_p = make_dev_payload(
            "1111222233334444", "Shanghai-Mac", "macos", "Asia/Shanghai", "kanjo 0.6.3",
            60000, 3.00, 64_000_000, 120.00, weekly_pct=22.0,
        )
        linux_p = make_dev_payload(
            "aaaa5555bbbb6666", "UTC-Linux", "linux", "UTC", "kanjo 0.6.4",
            40000, 2.00, 27_000_000, 50.00, weekly_pct=55.5,
        )
        bob_p = make_dev_payload(
            "9999888877776666", "Bob-PC", "windows", "America/New_York", "kanjo 0.6.3",
            10000, 0.50, 10_000_000, 20.00, weekly_pct=None,
        )

        with db.get_connection(self.db_path) as conn:
            _, m_alice = db.add_member(conn, "Alice")
            _, m_bob = db.add_member(conn, "Bob")
            # Legacy report older than Alice's device reports -> excluded + note shown
            legacy_p = copy.deepcopy(self.fixture_data)
            legacy_p.pop("device", None)
            db.insert_report(
                conn, m_alice, legacy_p["generated_at"], json.dumps(legacy_p),
                received_at=(now - timedelta(hours=5)).isoformat(), device_id="", device_name=None,
            )
            db.insert_report(
                conn, m_alice, mac_p["generated_at"], json.dumps(mac_p),
                received_at=rec_mac.isoformat(), device_id="1111222233334444", device_name="Shanghai-Mac",
            )
            db.insert_report(
                conn, m_alice, linux_p["generated_at"], json.dumps(linux_p),
                received_at=rec_linux.isoformat(), device_id="aaaa5555bbbb6666", device_name="UTC-Linux",
            )
            db.insert_report(
                conn, m_bob, bob_p["generated_at"], json.dumps(bob_p),
                received_at=rec_mac.isoformat(), device_id="9999888877776666", device_name="Bob-PC",
            )

        status, html = self._dash_request("/")
        self.assertEqual(status, 200)

        # Alice summed cycle total: 60000 + 40000 = 100.0k, $5.00
        self.assertIn("100.0k", html)
        self.assertIn("$5.00", html)

        # Pool card picks freshest device (UTC-Linux at 55.5%)
        self.assertIn("已用 <strong>55.5%</strong>", html)
        self.assertIn("数据来自 Alice 的最新上报（UTC-Linux）", html)

        # Device counts & details
        self.assertIn("2 台电脑", html)
        self.assertIn("1 台电脑", html)
        self.assertIn("Shanghai-Mac", html)
        self.assertIn("macOS", html)
        self.assertIn("Asia/Shanghai", html)
        self.assertIn("kanjo 0.6.3", html)
        self.assertIn("64.00M", html)
        self.assertIn("$120.00", html)
        self.assertIn("UTC-Linux", html)
        self.assertIn("Linux", html)
        self.assertIn("kanjo 0.6.4", html)
        self.assertIn("27.00M", html)
        self.assertIn("$50.00", html)
        self.assertIn("Bob-PC", html)
        self.assertIn("Windows", html)

        # Last report time shown in dashboard's configured timezone (America/Toronto)
        local_linux = rec_linux.astimezone(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d %H:%M")
        self.assertIn(local_linux, html)

        # Legacy excluded note shown for Alice
        self.assertIn("旧版 Kanjo 未计入", html)

    def test_dashboard_escapes_html_in_device_fields(self):
        malicious = copy.deepcopy(self.fixture_data)
        malicious["device"] = {
            "id": "1234567890abcdef",
            "name": "<script>alert(1)</script>",
            "os": "linux",
        }
        malicious["generated_by"] = "<img src=x onerror=alert(2)>"
        malicious["timezone"] = "<b>UTC</b>"

        with db.get_connection(self.db_path) as conn:
            _, m_id = db.add_member(conn, "Eve")
            db.insert_report(
                conn, m_id, malicious["generated_at"], json.dumps(malicious),
                received_at=datetime.now(timezone.utc).isoformat(),
                device_id="1234567890abcdef",
                device_name="<script>alert(1)</script>",
            )

        status, html = self._dash_request("/")
        self.assertEqual(status, 200)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x onerror=alert(2)>", html)
        self.assertNotIn("<b>UTC</b>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;img src=x onerror=alert(2)&gt;", html)
        self.assertIn("&lt;b&gt;UTC&lt;/b&gt;", html)

    def test_dashboard_after_merge_sums_computers_and_hides_merged_member(self):
        from zoneinfo import ZoneInfo

        now = datetime.now(timezone.utc)
        today_str = now.astimezone(ZoneInfo("America/Toronto")).date().isoformat()

        def make_payload(dev_id, dev_name, dev_os, day_tok, day_cost):
            p = copy.deepcopy(self.fixture_data)
            if dev_id:
                p["device"] = {"id": dev_id, "name": dev_name, "os": dev_os}
            else:
                p.pop("device", None)
            p["quota_windows"] = {}
            p["summary"]["all_time"]["tokens"]["total"] = day_tok
            p["summary"]["all_time"]["cost_usd"] = day_cost
            p["summary"]["days"] = [
                {
                    "period": today_str,
                    "first_day": today_str,
                    "last_day": today_str,
                    "tokens": {"input": day_tok, "output": 0, "cache_read": 0, "cache_write": 0, "total": day_tok},
                    "cost_usd": day_cost,
                    "by_provider": [{"provider": "google", "label": "Google", "tokens": {"input": day_tok, "output": 0, "cache_read": 0, "cache_write": 0, "total": day_tok}, "cost_usd": day_cost, "models": []}],
                    "by_agent": [{"agent": "antigravity", "label": "Antigravity", "tokens_total": day_tok, "cost_usd": day_cost}],
                    "top_models": [{"model": "gemini-3.8-pro", "provider": "google", "tokens_total": day_tok, "cost_usd": day_cost}],
                }
            ]
            return p

        mac_p = make_payload("1111222233334444", "Payton-MBP", "macos", 70000, 3.50)
        win_p = make_payload("aaaa5555bbbb6666", "Win-Workstation", "windows", 30000, 1.50)

        with db.get_connection(self.db_path) as conn:
            _, id_mac = db.add_member(conn, "Payton Mac")
            _, id_win = db.add_member(conn, "Windows VM")
            db.insert_report(
                conn, id_mac, mac_p["generated_at"], json.dumps(mac_p),
                received_at=(now - timedelta(minutes=10)).isoformat(),
                device_id="1111222233334444", device_name="Payton-MBP",
            )
            db.insert_report(
                conn, id_win, win_p["generated_at"], json.dumps(win_p),
                received_at=(now - timedelta(minutes=5)).isoformat(),
                device_id="aaaa5555bbbb6666", device_name="Win-Workstation",
            )
            db.merge_members(conn, id_win, id_mac)

        status, html = self._dash_request("/")
        self.assertEqual(status, 200)
        self.assertIn("Payton Mac", html)
        self.assertNotIn("Windows VM", html)
        # Summed cycle tokens: 70000 + 30000 = 100.0k, $5.00
        self.assertIn("100.0k", html)
        self.assertIn("$5.00", html)
        self.assertIn("2 台电脑", html)
        self.assertIn("Payton-MBP", html)
        self.assertIn("Win-Workstation", html)

    def test_dashboard_legacy_merged_group_label_and_excluded_count(self):
        from zoneinfo import ZoneInfo

        now = datetime.now(timezone.utc)
        today_str = now.astimezone(ZoneInfo("America/Toronto")).date().isoformat()

        def make_legacy_payload(day_tok):
            p = copy.deepcopy(self.fixture_data)
            p.pop("device", None)
            p["quota_windows"] = {}
            p["summary"]["all_time"]["tokens"]["total"] = day_tok
            p["summary"]["days"] = [
                {
                    "period": today_str,
                    "first_day": today_str,
                    "last_day": today_str,
                    "tokens": {"input": day_tok, "output": 0, "cache_read": 0, "cache_write": 0, "total": day_tok},
                    "cost_usd": 1.0,
                    "by_provider": [],
                    "by_agent": [],
                    "top_models": [],
                }
            ]
            return p

        with db.get_connection(self.db_path) as conn:
            _, id_mac = db.add_member(conn, "Payton Mac")
            _, id_win = db.add_member(conn, "Windows VM")
            # Windows VM legacy report is NEWER than Payton Mac's tagged report -> included with original name
            db.insert_report(
                conn, id_win, now.isoformat(), json.dumps(make_legacy_payload(25000)),
                received_at=now.isoformat(), device_id="", device_name=None,
            )
            mac_tagged = copy.deepcopy(self.fixture_data)
            mac_tagged["device"] = {"id": "1111222233334444", "name": "Payton-MBP", "os": "macos"}
            mac_tagged["quota_windows"] = {}
            mac_tagged["summary"]["days"] = make_legacy_payload(50000)["summary"]["days"]
            db.insert_report(
                conn, id_mac, now.isoformat(), json.dumps(mac_tagged),
                received_at=(now - timedelta(hours=1)).isoformat(),
                device_id="1111222233334444", device_name="Payton-MBP",
            )
            # Payton Mac's own legacy report is OLDER than tagged -> 1 excluded
            db.insert_report(
                conn, id_mac, now.isoformat(), json.dumps(make_legacy_payload(10000)),
                received_at=(now - timedelta(hours=3)).isoformat(),
                device_id="", device_name=None,
            )
            db.merge_members(conn, id_win, id_mac)

        status, html = self._dash_request("/")
        self.assertEqual(status, 200)
        self.assertIn("旧版客户端 (Windows VM)", html)
        self.assertIn("1 台电脑使用旧版 Kanjo 未计入", html)
        # 50000 + 25000 = 75.0k
        self.assertIn("75.0k", html)

        # Now add a fresher tagged report so BOTH legacy groups are excluded -> "2 台电脑使用旧版 Kanjo 未计入"
        with db.get_connection(self.db_path) as conn:
            mac_tagged2 = copy.deepcopy(mac_tagged)
            db.insert_report(
                conn, id_mac, (now + timedelta(minutes=10)).isoformat(), json.dumps(mac_tagged2),
                received_at=(now + timedelta(minutes=10)).isoformat(),
                device_id="1111222233334444", device_name="Payton-MBP",
            )

        status2, html2 = self._dash_request("/")
        self.assertEqual(status2, 200)
        self.assertIn("2 台电脑使用旧版 Kanjo 未计入", html2)


if __name__ == "__main__":
    unittest.main()
