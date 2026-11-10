"""Unit tests for the report API endpoint (HTTP 401, 400, 413, 429, 200, privacy checks)."""

import copy
import io
import json
import logging
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from family_server import db
from family_server.server import start_servers, stop_servers


class TestAPIEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "report.json")
        with open(cls.fixture_path, "r", encoding="utf-8") as f:
            cls.fixture_data = json.load(f)

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "api_test.db")
        db.init_db(self.db_path)

        # Capture log records to verify token and body are NEVER logged
        self.log_stream = io.StringIO()
        self.log_handler = logging.StreamHandler(self.log_stream)
        self.logger = logging.getLogger("family_server")
        self.logger.addHandler(self.log_handler)
        self.logger.setLevel(logging.INFO)

        # Start servers on ephemeral ports
        self.api_server, self.dash_server, self.api_port, self.dash_port = start_servers(
            db_path=self.db_path,
            api_host="127.0.0.1",
            api_port=0,
            dashboard_host="127.0.0.1",
            dashboard_port=0,
        )

        with db.get_connection(self.db_path) as conn:
            self.token_alice, self.m_alice = db.add_member(conn, "Alice")
            self.token_bob, self.m_bob = db.add_member(conn, "Bob")
            self.token_revoked, self.m_revoked = db.add_member(conn, "RevokedMember")
            db.revoke_member(conn, "RevokedMember")

    def tearDown(self):
        stop_servers(self.api_server, self.dash_server)
        self.logger.removeHandler(self.log_handler)
        self.tmp_dir.cleanup()

    def _api_request(self, method: str, path: str, data: bytes = None, headers: dict = None):
        """Helper to send HTTP request to API server."""
        url = f"http://127.0.0.1:{self.api_port}{path}"
        req_headers = headers.copy() if headers else {}
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                body = resp.read()
                resp_headers = dict(resp.getheaders())
                return status, body, resp_headers
        except urllib.error.HTTPError as e:
            status = e.code
            body = e.read()
            resp_headers = dict(e.headers)
            return status, body, resp_headers

    def test_healthz(self):
        status, body, _ = self._api_request("GET", "/healthz")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("status"), "ok")

    def test_unknown_path_is_404(self):
        status, _, _ = self._api_request("GET", "/unknown")
        self.assertEqual(status, 404)

        status, _, _ = self._api_request("POST", "/healthz", data=b"{}")
        self.assertEqual(status, 404)

        status, _, _ = self._api_request("GET", "/api/report")
        self.assertEqual(status, 404)

    def test_401_missing_or_invalid_auth(self):
        raw_body = json.dumps(self.fixture_data).encode("utf-8")

        # Missing auth header
        status, _, _ = self._api_request("POST", "/api/report", data=raw_body)
        self.assertEqual(status, 401)

        # Invalid auth scheme
        status, _, _ = self._api_request(
            "POST", "/api/report", data=raw_body, headers={"Authorization": "Basic dXNlcjpwYXNz"}
        )
        self.assertEqual(status, 401)

        # Invalid bearer token
        fake_token = "invalid-token-12345678901234567890"
        status, _, _ = self._api_request(
            "POST", "/api/report", data=raw_body, headers={"Authorization": f"Bearer {fake_token}"}
        )
        self.assertEqual(status, 401)

        # Revoked member token
        status, _, _ = self._api_request(
            "POST", "/api/report", data=raw_body, headers={"Authorization": f"Bearer {self.token_revoked}"}
        )
        self.assertEqual(status, 401)

        # Check logs never contain the token
        logs = self.log_stream.getvalue()
        self.assertNotIn(fake_token, logs)
        self.assertNotIn(self.token_revoked, logs)

    def test_413_payload_too_large(self):
        # 2 MB limit: payload larger than 2 * 1024 * 1024 bytes
        large_body = b"x" * (2 * 1024 * 1024 + 10)
        status, body, _ = self._api_request(
            "POST",
            "/api/report",
            data=large_body,
            headers={
                "Authorization": f"Bearer {self.token_alice}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(status, 413)

    def test_400_invalid_json(self):
        status, body, _ = self._api_request(
            "POST",
            "/api/report",
            data=b"not a valid json {{{",
            headers={
                "Authorization": f"Bearer {self.token_alice}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(status, 400)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_400_invalid_kind_or_missing_keys(self):
        # Wrong kind
        bad_kind = copy.deepcopy(self.fixture_data)
        bad_kind["kind"] = "kanjo-public-summary"
        status, _, _ = self._api_request(
            "POST",
            "/api/report",
            data=json.dumps(bad_kind).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token_alice}"},
        )
        self.assertEqual(status, 400)

        # Missing summary key
        missing_key = copy.deepcopy(self.fixture_data)
        del missing_key["summary"]
        status, _, _ = self._api_request(
            "POST",
            "/api/report",
            data=json.dumps(missing_key).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token_alice}"},
        )
        self.assertEqual(status, 400)

    def test_privacy_backstops(self):
        """Privacy backstop: reject if contains /Users/, /home/, @, or forbidden keys."""
        forbidden_substrings = ["/Users/alice/projects", "/home/ubuntu/code", "user@domain.com"]
        for pat in forbidden_substrings:
            bad_data = copy.deepcopy(self.fixture_data)
            bad_data["member_label"] = f"Label with {pat}"
            status, _, _ = self._api_request(
                "POST",
                "/api/report",
                data=json.dumps(bad_data).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.token_alice}"},
            )
            self.assertEqual(status, 400, f"Failed to reject forbidden pattern: {pat}")

        forbidden_keys = ["sessions_detail", "account", "paths", "title", "sessions"]
        for key in forbidden_keys:
            bad_data = copy.deepcopy(self.fixture_data)
            bad_data[key] = "forbidden_value"
            status, _, _ = self._api_request(
                "POST",
                "/api/report",
                data=json.dumps(bad_data).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.token_alice}"},
            )
            self.assertEqual(status, 400, f"Failed to reject forbidden key: {key}")

        # Verify that none of these rejected reports were stored in DB
        with db.get_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM reports")
            self.assertEqual(cur.fetchone()[0], 0)

        # Verify logs never leaked token or body
        logs = self.log_stream.getvalue()
        self.assertNotIn(self.token_alice, logs)
        self.assertNotIn("user@domain.com", logs)

    def test_privacy_backstop_model_with_at_accepted_and_email_rejected(self):
        """Model ids with '@' (e.g. claude-x@20240620) must be accepted, while email addresses are rejected."""
        # 1. Model id with @ like claude-3-5-sonnet@20240620 is accepted
        ok_data = copy.deepcopy(self.fixture_data)
        ok_data["member_label"] = "Model test claude-3-5-sonnet@20240620"
        ok_data["summary"]["all_time"]["top_models"].append({
            "model": "claude-x@20240620",
            "tokens_total": 500,
            "cost_usd": 0.05,
        })
        status, body, _ = self._api_request(
            "POST",
            "/api/report",
            data=json.dumps(ok_data).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token_alice}"},
        )
        self.assertEqual(status, 200, f"Valid model id with @ should be accepted, got: {body.decode('utf-8')}")

        # 2. Email in string value is rejected
        email_data = copy.deepcopy(self.fixture_data)
        email_data["member_label"] = "Please contact me at admin@corp.example.com"
        status, _, _ = self._api_request(
            "POST",
            "/api/report",
            data=json.dumps(email_data).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token_bob}"},
        )
        self.assertEqual(status, 400, "Email in string value must be rejected")

        # 3. Email in dict key is rejected
        email_key_data = copy.deepcopy(self.fixture_data)
        email_key_data["summary"]["alice@company.org"] = "leaked"
        status, _, _ = self._api_request(
            "POST",
            "/api/report",
            data=json.dumps(email_key_data).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token_bob}"},
        )
        self.assertEqual(status, 400, "Email in dict key must be rejected")

    def test_200_valid_report_and_storage(self):
        valid_bytes = json.dumps(self.fixture_data).encode("utf-8")
        status, body, _ = self._api_request(
            "POST",
            "/api/report",
            data=valid_bytes,
            headers={
                "Authorization": f"Bearer {self.token_alice}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(status, 200)
        res = json.loads(body.decode("utf-8"))
        self.assertEqual(res["status"], "ok")
        self.assertIn("received_at", res)

        # Verify stored in DB
        with db.get_connection(self.db_path) as conn:
            rep = db.get_member_latest_report(conn, self.m_alice)
            self.assertIsNotNone(rep)
            stored_payload = json.loads(rep["payload_json"])
            self.assertEqual(stored_payload["kind"], "kanjo-family-report")

    def test_429_rate_limiting(self):
        valid_bytes = json.dumps(self.fixture_data).encode("utf-8")

        # First report from Alice -> 200 OK
        status1, body1, _ = self._api_request(
            "POST",
            "/api/report",
            data=valid_bytes,
            headers={"Authorization": f"Bearer {self.token_alice}"},
        )
        self.assertEqual(status1, 200)

        # Immediate second report with same token -> 429 Too Many Requests
        status2, body2, headers2 = self._api_request(
            "POST",
            "/api/report",
            data=valid_bytes,
            headers={"Authorization": f"Bearer {self.token_alice}"},
        )
        self.assertEqual(status2, 429)
        self.assertIn("retry-after", [k.lower() for k in headers2.keys()])

        # Report with Bob's token should succeed (per-token limit)
        status_bob, _, _ = self._api_request(
            "POST",
            "/api/report",
            data=valid_bytes,
            headers={"Authorization": f"Bearer {self.token_bob}"},
        )
        self.assertEqual(status_bob, 200)


if __name__ == "__main__":
    unittest.main()
