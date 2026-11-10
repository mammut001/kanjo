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

        # Check days count <= 31
        self.assertLessEqual(len(summary["days"]), 31)
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


if __name__ == "__main__":
    unittest.main()
