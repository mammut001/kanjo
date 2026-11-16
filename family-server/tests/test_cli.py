"""Unit tests for CLI commands (member add/list/revoke, prune)."""

import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from family_server import db
from family_server.__main__ import main


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "cli_test.db")
        db.init_db(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def run_cli(self, args):
        full_args = ["--db", self.db_path] + args
        out = io.StringIO()
        err = io.StringIO()
        with patch.object(sys, "stdout", out), patch.object(sys, "stderr", err):
            code = main(full_args)
        return code, out.getvalue(), err.getvalue()

    def test_member_lifecycle_via_cli(self):
        # 1. Add member
        code, out, _ = self.run_cli(["member", "add", "Charlie"])
        self.assertEqual(code, 0)
        self.assertIn("Successfully added member 'Charlie'", out)
        self.assertIn("Token:", out)

        # 2. Duplicate member fails
        code, _, err = self.run_cli(["member", "add", "Charlie"])
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)

        # 3. List members
        code, out, _ = self.run_cli(["member", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Charlie", out)
        self.assertIn("Active", out)

        # 4. Revoke member
        code, out, _ = self.run_cli(["member", "revoke", "Charlie"])
        self.assertEqual(code, 0)
        self.assertIn("Successfully revoked", out)

        # List members again shows revoked
        code, out, _ = self.run_cli(["member", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Revoked", out)

    def test_prune_via_cli(self):
        code, out, _ = self.run_cli(["prune"])
        self.assertEqual(code, 0)
        self.assertIn("Pruned 0 report(s)", out)

    def test_device_list_and_remove_via_cli(self):
        with db.get_connection(self.db_path) as conn:
            _, m_id = db.add_member(conn, "Alice")
            db.insert_report(
                conn,
                m_id,
                "2026-11-10T10:00:00Z",
                '{"device":{"id":"1111222233334444","name":"OldMac","os":"macos"}}',
                received_at="2026-11-10T10:00:00Z",
                device_id="1111222233334444",
                device_name="OldMac",
            )
            db.insert_report(
                conn,
                m_id,
                "2026-11-11T10:00:00Z",
                '{"device":{"id":"aaaa5555bbbb6666","name":"LinuxBox","os":"linux"}}',
                received_at="2026-11-11T10:00:00Z",
                device_id="aaaa5555bbbb6666",
                device_name="LinuxBox",
            )

        # List devices
        code, out, _ = self.run_cli(["device", "list", "--member", "Alice"])
        self.assertEqual(code, 0)
        self.assertIn("1111222233334444", out)
        self.assertIn("OldMac", out)
        self.assertIn("macos", out)
        self.assertIn("aaaa5555bbbb6666", out)
        self.assertIn("LinuxBox", out)

        # Unknown member fails
        code, _, err = self.run_cli(["device", "list", "--member", "Nobody"])
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

        # Remove retired device
        code, out, _ = self.run_cli(
            ["device", "remove", "--member", "Alice", "--device", "1111222233334444"]
        )
        self.assertEqual(code, 0)
        self.assertIn("Removed 1 report(s)", out)

        # Verify only LinuxBox remains
        code, out, _ = self.run_cli(["device", "list", "--member", "Alice"])
        self.assertEqual(code, 0)
        self.assertNotIn("1111222233334444", out)
        self.assertIn("aaaa5555bbbb6666", out)

        # Removing nonexistent device returns 1
        code, _, err = self.run_cli(
            ["device", "remove", "--member", "Alice", "--device", "deadbeefdeadbeef"]
        )
        self.assertEqual(code, 1)
        self.assertIn("No reports found", err)

    def test_member_merge_and_tokens_via_cli(self):
        with db.get_connection(self.db_path) as conn:
            tok_win, id_win = db.add_member(conn, "Windows VM")
            tok_mac, id_mac = db.add_member(conn, "Payton Mac")
            _, _ = db.add_member(conn, "RevokedGuy")
            db.revoke_member(conn, "RevokedGuy")
            db.insert_report(
                conn, id_win, "2026-11-10T10:00:00Z", '{"summary":{}}',
                received_at="2026-11-10T10:00:00Z", device_id="", device_name=None,
            )

        # Refusal: unknown names, same member, revoked
        code, _, err = self.run_cli(["member", "merge", "--from", "Ghost", "--into", "Payton Mac"])
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

        code, _, err = self.run_cli(["member", "merge", "--from", "Windows VM", "--into", "Ghost"])
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

        code, _, err = self.run_cli(["member", "merge", "--from", "Payton Mac", "--into", "Payton Mac"])
        self.assertEqual(code, 1)
        self.assertIn("itself", err)

        code, _, err = self.run_cli(["member", "merge", "--from", "RevokedGuy", "--into", "Payton Mac"])
        self.assertEqual(code, 1)
        self.assertIn("revoked", err)

        # Happy path merge
        code, out, _ = self.run_cli(["member", "merge", "--from", "Windows VM", "--into", "Payton Mac"])
        self.assertEqual(code, 0)
        self.assertIn("1 token(s) moved", out)
        self.assertIn("1 report(s) moved", out)

        # Refusal: already merged
        code, _, err = self.run_cli(["member", "merge", "--from", "Windows VM", "--into", "Payton Mac"])
        self.assertEqual(code, 1)
        self.assertIn("already merged", err)

        # member list shows Merged into Payton Mac
        code, out, _ = self.run_cli(["member", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Merged into Payton Mac", out)

        # member tokens lists both active tokens for Payton Mac without full hash
        code, out, _ = self.run_cli(["member", "tokens", "--member", "Payton Mac"])
        self.assertEqual(code, 0)
        hash_win = db.hash_token(tok_win)
        hash_mac = db.hash_token(tok_mac)
        self.assertIn(hash_win[:8], out)
        self.assertIn(hash_mac[:8], out)
        self.assertNotIn(hash_win, out)
        self.assertNotIn(hash_mac, out)
        self.assertEqual(out.count("Active"), 2)

        # member tokens for unknown member fails
        code, _, err = self.run_cli(["member", "tokens", "--member", "Nobody"])
        self.assertEqual(code, 1)
        self.assertIn("not found", err)


if __name__ == "__main__":
    unittest.main()
