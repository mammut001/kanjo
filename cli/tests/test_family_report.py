"""Tests for family report export and reporting command (CONTRACT.md section 13)."""

from http.server import HTTPServer, BaseHTTPRequestHandler
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

# Add family-server to sys.path to import the real merged server validator
FAMILY_SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "family-server"))
if FAMILY_SERVER_DIR not in sys.path:
    sys.path.insert(0, FAMILY_SERVER_DIR)

from family_server.validation import validate_report_payload, check_privacy_backstop

from kanjo import cli, export
from tests.support import FIXTURE_DIRS


class FamilyReportExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-family-test-")
        self.data_dir = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

        self.env = {
            "KANJO_DATA_DIR": self.data_dir,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_CLAUDE_DIR": FIXTURE_DIRS["claude"][0],
            "KANJO_ANTIGRAVITY_DIR": FIXTURE_DIRS["antigravity"][0],
            "KANJO_CODEX_DIR": FIXTURE_DIRS["codex"][0],
            "KANJO_GROK_DIR": self.tmp,
            "KANJO_QWEN_DIR": self.tmp,
            "KANJO_COMMANDCODE_DIR": self.tmp,
            "KANJO_MINIMAX_DIR": self.tmp,
            "KANJO_OPENCODE_DIR": self.tmp,
            "KANJO_COPILOT_DIR": self.tmp,
            "KANJO_PI_DIR": self.tmp,
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_cli(self, *args, extra_env=None):
        out = io.StringIO()
        err = io.StringIO()
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        with mock.patch.dict(os.environ, env), mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_family_report_schema_and_server_validation(self):
        code, out, err = self._run_cli("export", "--family-report", "--member-label", "Alice (MacBook)")
        self.assertEqual(code, 0, err)
        doc = json.loads(out)

        # 1. Top-level schema
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(doc["kind"], "kanjo-family-report")
        self.assertEqual(doc["member_label"], "Alice (MacBook)")
        self.assertIn("generated_at", doc)
        self.assertIn("timezone", doc)
        self.assertIn("generated_by", doc)
        self.assertIn("cost_note", doc)
        self.assertIn("plans", doc)
        self.assertIn("quota_windows", doc)
        self.assertIn("summary", doc)

        # 2. summary structure
        summary = doc["summary"]
        for key in ("all_time", "months", "weeks", "days"):
            self.assertIn(key, summary)
            self.assertIsInstance(summary[key], (dict if key == "all_time" else list))

        # Check days count <= 62
        self.assertLessEqual(len(summary["days"]), 62)
        for d in summary["days"]:
            self.assertIn("period", d)
            self.assertRegex(d["period"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertEqual(d["first_day"], d["period"])
            self.assertEqual(d["last_day"], d["period"])
            self.assertIn("tokens", d)
            self.assertIn("cost_usd", d)
            self.assertIn("by_provider", d)
            self.assertIn("by_agent", d)
            self.assertIn("top_models", d)

        # 3. Check plans only contain agent -> plan_label
        for agent, plan_label in doc["plans"].items():
            self.assertIsInstance(agent, str)
            self.assertIsInstance(plan_label, str)

        # 4. Invariant checks
        problems = export.check_family_report_invariants(doc)
        self.assertEqual(problems, [], "Invariant violations: %s" % problems)

        # 5. Run the real server validator: validate_report_payload
        val_err = validate_report_payload(doc)
        self.assertIsNone(val_err, "family-server validator rejected payload: %s" % val_err)

        # 6. Run the real server privacy backstop check
        raw_bytes = out.encode("utf-8")
        privacy_err = check_privacy_backstop(raw_bytes)
        self.assertIsNone(privacy_err, "family-server privacy backstop failed: %s" % privacy_err)

    def test_family_report_null_member_label_by_default(self):
        code, out, err = self._run_cli("export", "--family-report")
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertIsNone(doc["member_label"])

        # Must pass server validator
        self.assertIsNone(validate_report_payload(doc))
        self.assertIsNone(check_privacy_backstop(out.encode("utf-8")))

    def test_mutual_exclusion(self):
        # --family-report with --mobile
        code, _, err = self._run_cli("export", "--family-report", "--mobile")
        self.assertEqual(code, 2)
        self.assertIn("--family-report cannot be combined with --mobile or --public-summary", err)

        # --family-report with --public-summary
        code, _, err = self._run_cli("export", "--family-report", "--public-summary")
        self.assertEqual(code, 2)
        self.assertIn("--family-report cannot be combined with --mobile or --public-summary", err)

    def test_extra_windows_title_sanitization(self):
        # Mock quota.quota_windows to return extra_windows with a 'title' field
        mock_qw = {
            "antigravity": {
                "weekly_resets_at": "2026-11-14T12:00:00Z",
                "weekly_window_hours": 168,
                "weekly_used_percent": 15.0,
                "source": "live",
                "extra_windows": [
                    {"id": "3p-weekly", "title": "Claude/GPT Weekly", "used_percent": 20.0, "window_hours": 168}
                ]
            }
        }
        with mock.patch("kanjo.quota.quota_windows", return_value=mock_qw):
            doc = export.build_family_report()
            # 'title' key must have been renamed to 'label'
            ew = doc["quota_windows"]["antigravity"]["extra_windows"][0]
            self.assertNotIn("title", ew)
            self.assertEqual(ew.get("label"), "Claude/GPT Weekly")

            # Must strictly pass privacy backstop check and payload validation
            raw_bytes = json.dumps(doc, ensure_ascii=False).encode("utf-8")
            self.assertIsNone(check_privacy_backstop(raw_bytes))
            self.assertIsNone(validate_report_payload(doc))

    def test_family_report_days_max_62(self):
        from datetime import datetime, timezone
        from kanjo.sources.base import Message, Session
        # Create messages across 80 days
        base_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        messages = []
        for i in range(80):
            ts = base_ts + i * 86400
            messages.append(Message(ts=ts, model="gemini-3.8-pro", input=100, output=100))
        sess = Session(id="sess-1", agent="antigravity", file="/fake", messages=messages)
        scan_res = export.ScanResult(sessions=[sess], failed_files=[], stats={})

        doc = export.build_family_report(scan_result=scan_res)
        days = doc["summary"]["days"]
        self.assertEqual(len(days), 62)
        # Verify it kept the latest 62 days
        expected_last_day = datetime.fromtimestamp(base_ts + 79 * 86400, timezone.utc).strftime("%Y-%m-%d")
        expected_first_day = datetime.fromtimestamp(base_ts + (80 - 62) * 86400, timezone.utc).strftime("%Y-%m-%d")
        self.assertEqual(days[-1]["period"], expected_last_day)
        self.assertEqual(days[0]["period"], expected_first_day)
        self.assertEqual(export.check_family_report_invariants(doc), [])


class MockFamilyServerHandler(BaseHTTPRequestHandler):
    received_requests = []
    response_status = 200
    response_body = {"status": "ok", "received_at": "2026-11-09T19:00:00Z"}

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        auth = self.headers.get("Authorization", "")
        MockFamilyServerHandler.received_requests.append({
            "path": self.path,
            "auth": auth,
            "headers": dict(self.headers),
            "body": body,
        })
        self.send_response(MockFamilyServerHandler.response_status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(MockFamilyServerHandler.response_body).encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Suppress stdout logging during tests


class ReportFamilyCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-family-cmd-test-")
        self.data_dir = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

        self.env = {
            "KANJO_DATA_DIR": self.data_dir,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_CLAUDE_DIR": FIXTURE_DIRS["claude"][0],
            "KANJO_ANTIGRAVITY_DIR": FIXTURE_DIRS["antigravity"][0],
            "KANJO_CODEX_DIR": FIXTURE_DIRS["codex"][0],
            "KANJO_GROK_DIR": self.tmp,
            "KANJO_QWEN_DIR": self.tmp,
            "KANJO_COMMANDCODE_DIR": self.tmp,
            "KANJO_MINIMAX_DIR": self.tmp,
            "KANJO_OPENCODE_DIR": self.tmp,
            "KANJO_COPILOT_DIR": self.tmp,
            "KANJO_PI_DIR": self.tmp,
        }
        MockFamilyServerHandler.received_requests = []
        MockFamilyServerHandler.response_status = 200
        MockFamilyServerHandler.response_body = {"status": "ok", "received_at": "2026-11-09T19:00:00Z"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_cli(self, *args, extra_env=None):
        out = io.StringIO()
        err = io.StringIO()
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        with mock.patch.dict(os.environ, env), mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_refuse_when_token_unset(self):
        # KANJO_FAMILY_TOKEN is unset
        code, out, _ = self._run_cli("report-family", "--url", "http://127.0.0.1:8788")
        self.assertEqual(code, 1)
        res = json.loads(out.strip())
        self.assertEqual(res["status"], "error")
        self.assertIn("KANJO_FAMILY_TOKEN", res["message"])

    def test_reject_insecure_or_non_local_http(self):
        # Insecure remote HTTP URL must be rejected
        code, out, _ = self._run_cli(
            "report-family", "--url", "http://usage.paytonpei.top",
            extra_env={"KANJO_FAMILY_TOKEN": "test-token-123"}
        )
        self.assertEqual(code, 1)
        res = json.loads(out.strip())
        self.assertEqual(res["status"], "error")
        self.assertIn("Invalid URL", res["message"])

        # Non-http scheme rejected
        code, out, _ = self._run_cli(
            "report-family", "--url", "ftp://127.0.0.1:8788",
            extra_env={"KANJO_FAMILY_TOKEN": "test-token-123"}
        )
        self.assertEqual(code, 1)
        res = json.loads(out.strip())
        self.assertEqual(res["status"], "error")

    def test_successful_report_to_local_server(self):
        # Start ephemeral local HTTP server on 127.0.0.1
        server = HTTPServer(("127.0.0.1", 0), MockFamilyServerHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.handle_request)
        thread.daemon = True
        thread.start()

        url = f"http://127.0.0.1:{port}"
        code, out, err = self._run_cli(
            "report-family", "--url", url, "--member-label", "Bob (Mac mini)",
            extra_env={"KANJO_FAMILY_TOKEN": "secret-family-token-xyz"}
        )
        server.server_close()
        thread.join(timeout=2)

        self.assertEqual(code, 0, err)
        res = json.loads(out.strip())
        self.assertEqual(res, {"status": "sent", "received_at": "2026-11-09T19:00:00Z"})

        # Verify server received the request correctly
        self.assertEqual(len(MockFamilyServerHandler.received_requests), 1)
        req = MockFamilyServerHandler.received_requests[0]
        self.assertEqual(req["path"], "/api/report")
        self.assertEqual(req["auth"], "Bearer secret-family-token-xyz")

        payload = json.loads(req["body"].decode("utf-8"))
        self.assertEqual(payload["kind"], "kanjo-family-report")
        self.assertEqual(payload["member_label"], "Bob (Mac mini)")
        # Validate against family-server rules
        self.assertIsNone(validate_report_payload(payload))
        self.assertIsNone(check_privacy_backstop(req["body"]))

    def test_http_error_response_from_server(self):
        MockFamilyServerHandler.response_status = 401
        MockFamilyServerHandler.response_body = {"status": "error", "error": "Unauthorized"}

        server = HTTPServer(("127.0.0.1", 0), MockFamilyServerHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.handle_request)
        thread.daemon = True
        thread.start()

        url = f"http://127.0.0.1:{port}"
        code, out, _ = self._run_cli(
            "report-family", "--url", url,
            extra_env={"KANJO_FAMILY_TOKEN": "revoked-token"}
        )
        server.server_close()
        thread.join(timeout=2)

        self.assertEqual(code, 1)
        res = json.loads(out.strip())
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["http_status"], 401)
        self.assertEqual(res["message"], "Unauthorized")


class TestFamilyReportScope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-family-scope-test-")
        self.data_dir = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.config_dir = os.path.join(self.tmp, "config")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.config_dir, exist_ok=True)

        self.env = {
            "KANJO_DATA_DIR": self.data_dir,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_CONFIG_DIR": self.config_dir,
            "KANJO_CLAUDE_DIR": FIXTURE_DIRS["claude"][0],
            "KANJO_ANTIGRAVITY_DIR": FIXTURE_DIRS["antigravity"][0],
            "KANJO_CODEX_DIR": FIXTURE_DIRS["codex"][0],
            "KANJO_GROK_DIR": self.tmp,
            "KANJO_QWEN_DIR": self.tmp,
            "KANJO_COMMANDCODE_DIR": self.tmp,
            "KANJO_MINIMAX_DIR": self.tmp,
            "KANJO_OPENCODE_DIR": self.tmp,
            "KANJO_COPILOT_DIR": self.tmp,
            "KANJO_PI_DIR": self.tmp,
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_cli(self, *args, extra_env=None):
        out = io.StringIO()
        err = io.StringIO()
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        with mock.patch.dict(os.environ, env), mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_default_scope_and_plans_quota_filtering(self):
        # Configure subscriptions for both antigravity and claude
        self._run_cli("config", "set", "subscriptions.antigravity.plan", "google_ai_ultra")
        self._run_cli("config", "set", "subscriptions.claude.plan", "pro")

        code, out, err = self._run_cli("export", "--family-report", "--no-cache")
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        # Default scope: antigravity only, since is null
        self.assertEqual(doc.get("scope"), {"agents": ["antigravity"], "since": None})
        # plans must ONLY contain antigravity (claude is filtered out)
        self.assertEqual(doc.get("plans", {}), {"antigravity": "Google AI Ultra"})
        # quota_windows must not contain claude
        self.assertNotIn("claude", doc.get("quota_windows", {}))
        # All messages aggregated under by_agent must only be antigravity
        by_agent = doc["summary"]["all_time"]["by_agent"]
        agents = [a["agent"] for a in by_agent]
        self.assertEqual(agents, ["antigravity"])

    def test_scope_all_agents_includes_other_agents(self):
        # Configure subscriptions for both antigravity and claude
        self._run_cli("config", "set", "subscriptions.antigravity.plan", "google_ai_ultra")
        self._run_cli("config", "set", "subscriptions.claude.plan", "pro")
        # Configure family.agents = all
        code, _, err = self._run_cli("config", "set", "family.agents", "all")
        self.assertEqual(code, 0, err)

        code, out, err = self._run_cli("export", "--family-report", "--no-cache")
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc.get("scope"), {"agents": ["all"], "since": None})

        # When scope is all, both antigravity and claude plans appear
        self.assertIn("antigravity", doc.get("plans", {}))
        self.assertIn("claude", doc.get("plans", {}))

        by_agent = doc["summary"]["all_time"]["by_agent"]
        agents = [a["agent"] for a in by_agent]
        self.assertIn("antigravity", agents)
        self.assertIn("claude", agents)

    def test_filtering_by_since_boundary_condition(self):
        from kanjo.sources.base import Message, Session, local_timezone_name
        from kanjo.config import Config
        from datetime import datetime, timezone
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(local_timezone_name())
        except Exception:
            tz = timezone.utc

        # Let since date be 2026-11-09 (midnight in local timezone)
        dt = datetime(2026, 11, 9, 0, 0, 0, tzinfo=tz)
        since_ts = dt.timestamp()

        # Session with 3 messages:
        # 1. exactly one second before since_ts -> excluded
        # 2. exactly at since_ts -> included
        # 3. one second after since_ts -> included
        s = Session(
            id="session-boundary",
            agent="antigravity",
            file="/dummy/path",
            started=since_ts - 1.0,
            ended=since_ts + 1.0,
            messages=[
                Message(ts=since_ts - 1.0, model="gemini-2.5-flash", input=100, output=50),
                Message(ts=since_ts, model="gemini-2.5-flash", input=200, output=100),
                Message(ts=since_ts + 1.0, model="gemini-2.5-flash", input=300, output=150),
            ],
        )
        scan_res = export.ScanResult(sessions=[s], failed_files=[], stats={})

        cfg = Config(family_since="2026-11-09", family_agents=["antigravity"])
        doc = export.build_family_report(config=cfg, scan_result=scan_res)

        self.assertEqual(doc["scope"], {"agents": ["antigravity"], "since": "2026-11-09"})
        # Only messages 2 and 3 should be included:
        # input = 200 + 300 = 500
        # output = 100 + 150 = 250
        # total = 750
        tokens = doc["summary"]["all_time"]["tokens"]
        self.assertEqual(tokens["input"], 500)
        self.assertEqual(tokens["output"], 250)
        self.assertEqual(tokens["total"], 750)

    def test_fast_cache_invalidated_when_scope_changes(self):
        # 1. Run export with default scope (antigravity, since=None)
        code, out1, err = self._run_cli("export", "--family-report")
        self.assertEqual(code, 0, err)
        doc1 = json.loads(out1)
        self.assertEqual(doc1["scope"], {"agents": ["antigravity"], "since": None})

        # Verify fast cache file was created
        cache_file = os.path.join(self.cache_dir, "family-report-last.json")
        self.assertTrue(os.path.exists(cache_file))

        # 2. Change scope to since = 2026-11-09
        code, _, err = self._run_cli("config", "set", "family.since", "2026-11-09")
        self.assertEqual(code, 0, err)

        # 3. Export again without --no-cache (cache is used)
        code, out2, err = self._run_cli("export", "--family-report")
        self.assertEqual(code, 0, err)
        doc2 = json.loads(out2)
        # Must reflect the new scope, NOT stale cached doc1!
        self.assertEqual(doc2["scope"], {"agents": ["antigravity"], "since": "2026-11-09"})

        # 4. Change scope to agents = all
        code, _, err = self._run_cli("config", "set", "family.agents", "all")
        self.assertEqual(code, 0, err)

        code, out3, err = self._run_cli("export", "--family-report")
        self.assertEqual(code, 0, err)
        doc3 = json.loads(out3)
        self.assertEqual(doc3["scope"], {"agents": ["all"], "since": "2026-11-09"})

        # 5. Direct load_fast_family_report with wrong scope returns None
        fp = export.source_fingerprint(config=cli._config(type("Args", (), {"config": None})()))
        wrong_scope = {"agents": ["antigravity"], "since": "1999-01-01"}
        cached = export.load_fast_family_report(fp, directory=self.cache_dir, scope=wrong_scope)
        self.assertIsNone(cached)


if __name__ == "__main__":
    unittest.main()
