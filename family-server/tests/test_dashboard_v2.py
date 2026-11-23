"""Dashboard v2 page: range rendering, ?range= handling, JSON escaping, CSP and static JS."""

import copy
from datetime import datetime, timedelta, timezone
import json
import os
import re
import tempfile
import unittest
import urllib.error
import urllib.request

from family_server import dashboard, dashboard_view, db, ranges
from family_server.server import start_servers, stop_servers

NOW = datetime(2026, 11, 21, 17, 0, tzinfo=timezone.utc)
HOSTILE = '</script><img src=x onerror=alert(1)>'
EXPECTED_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://apis.google.com https://www.gstatic.com; "
    "connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://www.googleapis.com; "
    "frame-src https://example-family.firebaseapp.com; "
    "img-src 'self' data: https://lh3.googleusercontent.com; "
    "style-src 'self' 'unsafe-inline'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def _day(period, tokens, model="gemini-3.8-pro", cost=1.0):
    tok = {"input": tokens, "output": 0, "cache_read": 0, "cache_write": 0, "total": tokens}
    return {
        "period": period, "first_day": period, "last_day": period, "tokens": tok, "cost_usd": cost,
        "by_provider": [{"provider": "google", "label": "Google", "tokens": dict(tok), "cost_usd": cost,
                         "models": [{"model": model, "tokens_total": tokens, "cost_usd": cost}]}],
        "by_agent": [{"agent": "antigravity", "label": "Antigravity", "tokens_total": tokens, "cost_usd": cost}],
        "top_models": [{"model": model, "provider": "google", "tokens_total": tokens, "cost_usd": cost}],
    }


def _dash_json(page):
    m = re.search(r'<script type="application/json" id="dash-data">(.*?)</script>', page, re.S)
    return json.loads(m.group(1))


class DashboardV2RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "report.json"), encoding="utf-8") as f:
            cls.fixture = json.load(f)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "v2.db")
        db.init_db(self.db_path)
        dashboard._cached_dashboard_merge.cache_clear()

    def tearDown(self):
        self.tmp.cleanup()

    def _add(self, name, days, label="lbl", device=None, quota=None, received=NOW):
        data = copy.deepcopy(self.fixture)
        data["member_label"] = label
        data["summary"]["days"] = days
        data["quota_windows"] = quota or {}
        if device:
            data["device"] = {"id": device[0], "name": device[1], "os": "macos"}
        with db.get_connection(self.db_path) as conn:
            mid = db.get_member_by_name(conn, name)
            mid = mid["id"] if mid else db.add_member(conn, name)[1]
            db.insert_report(conn, mid, data["generated_at"], json.dumps(data), received_at=received.isoformat(),
                             device_id=device[0] if device else None, device_name=device[1] if device else None)
        return mid

    def test_every_range_renders_and_default_is_this_week(self):
        quota = {"antigravity": {"weekly_resets_at": "2026-11-24T12:00:00Z", "weekly_window_hours": 168,
                                 "weekly_used_percent": 30.0}}
        self._add("Alice", [_day("2026-11-17", 50000), _day("2026-11-20", 20000), _day("2026-11-10", 9000)],
                  quota=quota)
        self._add("Bob", [_day("2026-11-19", 10000, model="claude-opus-5.5")])
        with db.get_connection(self.db_path) as conn:
            db.add_member(conn, "Quiet")

        default = dashboard.generate_dashboard_html(self.db_path, now=NOW)
        self.assertIn('href="?range=this_week" data-range="this_week" aria-current="page"', default)
        self.assertIn("本周 · 11/16 – 11/22", default)
        self.assertIn("另有 1 人无用量", default)
        self.assertIn("较上周", default)
        self.assertEqual(_dash_json(default)["range"], "this_week")

        titles = {
            "today": "今天 · 11/21", "this_week": "本周 · 11/16 – 11/22", "last_week": "上周 · 11/09 – 11/15",
            "7d": "7 天 · 11/15 – 11/21", "30d": "30 天 · 10/23 – 11/21",
            "since_reset": "重置以来 · 11/17 – 11/21", "cycle": "周期 · 11/01 – 11/30", "all": "全部",
        }
        for key in ranges.RANGE_ORDER:
            with self.subTest(key=key):
                page = dashboard.generate_dashboard_html(self.db_path, now=NOW, range_key=key)
                self.assertIn(f'data-range="{key}" aria-current="page"', page)
                self.assertEqual(page.count('aria-current="page">'), 1)
                self.assertIn(titles[key], page)
                self.assertEqual(_dash_json(page)["range"], key)
                self.assertIn('<div id="view-main">', page)
        since = dashboard.generate_dashboard_html(self.db_path, now=NOW, range_key="since_reset")
        self.assertIn("按天近似", since)
        self.assertIn("额度池预计用量", since)
        bogus = dashboard.generate_dashboard_html(self.db_path, now=NOW, range_key="nope")
        self.assertIn('data-range="this_week" aria-current="page"', bogus)

    def test_since_reset_without_pool_shows_empty_state(self):
        self._add("Alice", [_day("2026-11-20", 1000)])
        page = dashboard.generate_dashboard_html(self.db_path, now=NOW, range_key="since_reset")
        self.assertIn("无法计算「重置以来」", page)
        self.assertIsNone(_dash_json(page)["ranges"]["since_reset"])

    def test_multi_device_rows_in_ranking_detail(self):
        mid = self._add("Alice", [_day("2026-11-20", 60000, cost=3.0)], device=("1111222233334444", "Mac-A"))
        self._add("Alice", [_day("2026-11-20", 40000, cost=2.0)], device=("aaaa5555bbbb6666", "PC-B"))
        page = dashboard.generate_dashboard_html(self.db_path, now=NOW)
        self.assertIn("100.0k", page)
        self.assertIn("2 台电脑", page)
        self.assertIn("60.0k ($3.00)", page)
        self.assertIn("40.0k ($2.00)", page)
        data = _dash_json(page)
        row = [m for m in data["ranges"]["this_week"]["members"] if m["id"] == mid][0]
        self.assertEqual(sorted(d["tokens"] for d in row["devices"]), [40000, 60000])

    def test_hostile_names_are_escaped_in_html_and_json(self):
        self._add(HOSTILE, [_day("2026-11-20", 1000, model=HOSTILE)], label=HOSTILE,
                  device=("1111222233334444", HOSTILE))
        page = dashboard.generate_dashboard_html(self.db_path, now=NOW)
        self.assertNotIn(HOSTILE, page)
        self.assertNotIn("<img", page)
        self.assertIn("&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;", page)
        block = re.search(r'id="dash-data">(.*?)</script>', page, re.S).group(1)
        for ch in "<>&":
            self.assertNotIn(ch, block)
        data = _dash_json(page)
        self.assertEqual(data["members"][0]["name"], HOSTILE)
        self.assertEqual(data["members"][0]["label"], HOSTILE)
        self.assertEqual(data["members"][0]["devices"][0]["name"], HOSTILE)
        self.assertEqual(data["ranges"]["this_week"]["models"][0]["model"], HOSTILE)
        # Only two script elements: the inert JSON block and the external file.
        scripts = re.findall(r"<script[^>]*>", page)
        self.assertEqual(scripts, ['<script type="application/json" id="dash-data">',
                                   '<script src="/static/dashboard.js" defer>'])

    def test_embed_json_escapes_breakout_characters(self):
        text = dashboard_view.embed_json({"n": "</script>& "})
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)
        self.assertNotIn("&", text)
        self.assertEqual(json.loads(text), {"n": "</script>& "})

    def test_stale_and_never_reported_status(self):
        self._add("Fresh", [_day("2026-11-20", 1000)], received=NOW - timedelta(minutes=30))
        self._add("Old", [_day("2026-11-20", 1000)], received=NOW - timedelta(hours=3))
        with db.get_connection(self.db_path) as conn:
            db.add_member(conn, "Never")
        page = dashboard.generate_dashboard_html(self.db_path, now=NOW)
        self.assertIn('<span class="badge badge-active">正常</span>', page)
        self.assertIn('<span class="badge badge-stale">超过 2 小时未上报</span>', page)
        self.assertIn('<span class="badge badge-stale badge-never">从未上报</span>', page)


class DashboardV2HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "v2http.db")
        db.init_db(self.db_path)
        with db.get_connection(self.db_path) as conn:
            self.session_id = db.create_session(conn, "admin@example.com")
            db.add_member(conn, "Alice")
        self.api, self.dash, _, self.port = start_servers(
            db_path=self.db_path, api_port=0, dashboard_port=0,
            firebase_config={"apiKey": "k", "authDomain": "example-family.firebaseapp.com",
                             "projectId": "example-family"},
            project_id="example-family", admin_emails={"admin@example.com"},
            public_origin="https://usage.example.com",
        )

    def tearDown(self):
        stop_servers(self.api, self.dash)
        self.tmp.cleanup()

    def _get(self, path, auth=True):
        headers = {"Cookie": f"__Host-family_session={self.session_id}"} if auth else {}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, dict(resp.headers), resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf-8")

    def test_range_query_and_csp_header_unchanged(self):
        for path, key in (("/", "this_week"), ("/?range=last_week", "last_week"),
                          ("/?range=all&x=1", "all"), ("/?range=%3Cscript%3E", "this_week")):
            with self.subTest(path=path):
                status, headers, body = self._get(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Security-Policy"], EXPECTED_CSP)
                self.assertIn(f'data-range="{key}" aria-current="page"', body)
                self.assertNotIn("<script>", body)

    def test_dashboard_js_served_as_javascript_and_public_like_other_static(self):
        status, headers, body = self._get("/static/dashboard.js", auth=False)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/javascript; charset=utf-8")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn('getElementById("dash-data")', body)
        self.assertNotIn("innerHTML", body)
        self.assertNotIn("eval(", body)
        status, _, _ = self._get("/static/../dashboard.py", auth=False)
        self.assertEqual(status, 404)
        # The page itself still needs a session (urllib follows the redirect to /login).
        status, _, body = self._get("/?range=all", auth=False)
        self.assertIn("使用 Google 账号登录", body)
        self.assertNotIn("dash-data", body)


if __name__ == "__main__":
    unittest.main()
