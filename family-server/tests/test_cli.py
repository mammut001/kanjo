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


if __name__ == "__main__":
    unittest.main()
