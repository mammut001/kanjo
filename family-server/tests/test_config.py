"""Tests for server configuration validation, CSP header generation, and authDomain validation."""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from family_server.__main__ import main
from family_server.dashboard import make_dashboard_handler
from family_server.validation import validate_auth_domain, validate_serve_env


class TestServerConfig(unittest.TestCase):
    def test_missing_required_env_fails_with_all_names_listed(self):
        # 1. Direct validation function check
        errors, cfg = validate_serve_env(
            public_origin=None,
            firebase_config_raw=None,
            admin_emails=None,
        )
        self.assertEqual(len(errors), 3)
        joined_errors = "\n".join(errors)
        self.assertIn("FAMILY_PUBLIC_ORIGIN", joined_errors)
        self.assertIn("FIREBASE_WEB_CONFIG_JSON", joined_errors)
        self.assertIn("FAMILY_ADMIN_EMAILS", joined_errors)

        # 2. CLI serve subcommand execution check
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            captured_err = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), \
                 patch("sys.stderr", captured_err):
                with self.assertRaises(SystemExit) as ctx:
                    main(["--db", db_path, "serve"])
                self.assertNotEqual(ctx.exception.code, 0)
                err_out = captured_err.getvalue()
                self.assertIn("FAMILY_PUBLIC_ORIGIN", err_out)
                self.assertIn("FIREBASE_WEB_CONFIG_JSON", err_out)
                self.assertIn("FAMILY_ADMIN_EMAILS", err_out)

    def test_member_subcommand_does_not_require_serve_env(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            with patch.dict(os.environ, {}, clear=True):
                # member list should succeed even without any serve environment variables
                res = main(["--db", db_path, "member", "list"])
                self.assertEqual(res, 0)

    def test_csp_uses_auth_domain(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            custom_auth_domain = "custom-tenant.firebaseapp.com"
            config = {
                "apiKey": "dummy-api-key",
                "authDomain": custom_auth_domain,
                "projectId": "custom-tenant",
            }
            handler_cls = make_dashboard_handler(
                db_path=db_path,
                firebase_config=config,
                project_id="custom-tenant",
                admin_emails={"admin@example.com"},
                public_origin="https://usage.example.com",
            )
            csp = handler_cls.csp_header
            self.assertIn(f"frame-src https://{custom_auth_domain}", csp)

    def test_bad_auth_domain_rejected(self):
        bad_domains = [
            "example.com; script-src 'unsafe-inline'",
            "example.com\r\nX-Injected: 1",
            "example.com\nX-Injected: 1",
            "https://example.com",
            "http://example.com",
            "example.com/some/path",
            "example.com:8080",
            "example..com",
            "-example.com",
            "",
            "   ",
        ]

        for bad in bad_domains:
            self.assertFalse(validate_auth_domain(bad), f"Expected {bad!r} to be rejected")

        # make_dashboard_handler must raise ValueError on bad authDomain
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test.db")
            for bad in [
                "example.com; script-src *",
                "https://auth.example.com",
                "auth.example.com\r\nBad: True",
            ]:
                bad_config = {
                    "apiKey": "dummy",
                    "authDomain": bad,
                    "projectId": "demo",
                }
                with self.assertRaises(ValueError):
                    make_dashboard_handler(
                        db_path=db_path,
                        firebase_config=bad_config,
                        project_id="demo",
                        admin_emails={"admin@example.com"},
                        public_origin="https://usage.example.com",
                    )


if __name__ == "__main__":
    unittest.main()
