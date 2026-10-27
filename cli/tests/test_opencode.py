"""Unit tests for the OpenCode log parser, including explicit MiniMax dedupe."""

import io
import os
import tempfile
import unittest
from unittest import mock

from kanjo.sources import opencode
from kanjo.sources.base import ParseError

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "opencode")


class OpenCodeParserTest(unittest.TestCase):
    def test_discover_and_parse(self):
        discovered = opencode.discover([FIXTURE_DIR])
        # ses_mm_overlap1 must be excluded from discovery!
        ids = [p.split("::")[-1] for p, _ in discovered]
        self.assertIn("ses_op1", ids)
        self.assertIn("ses_op2", ids)
        self.assertNotIn("ses_mm_overlap1", ids)
        self.assertEqual(len(discovered), 2)

        # Parse ses_op1
        path1, parent1 = next(item for item in discovered if "ses_op1" in item[0])
        self.assertIsNone(parent1)
        session1 = opencode.parse_file(path1, parent1)
        self.assertEqual(session1.id, "ses_op1")
        self.assertEqual(session1.agent, "opencode")
        self.assertIsNone(session1.subagent_of)
        self.assertEqual(session1.cwd, "/Users/alice/Documents/GitHub/testrepo")
        self.assertEqual(session1.title, "OpenCode Task")
        self.assertEqual(session1.origin_ts, 1782884259.857)
        self.assertEqual(len(session1.messages), 1)

        msg1 = session1.messages[0]
        self.assertEqual(msg1.model, "deepseek-v4-flash-free")
        self.assertEqual(msg1.ts, 1782884259.857)
        self.assertEqual(msg1.input, 200)
        self.assertEqual(msg1.output, 100)
        self.assertEqual(msg1.thinking, 20)
        self.assertEqual(msg1.cache_read, 50)
        self.assertEqual(msg1.cache_write, 10)
        self.assertEqual(msg1.key, "opencode:msg_1")

        # Tool calls
        self.assertEqual(len(session1.tool_paths), 1)
        self.assertEqual(session1.tool_paths[0], ["/Users/alice/Documents/GitHub/testrepo/src/app.py"])

        # Parse ses_op2 (subagent)
        path2, parent2 = next(item for item in discovered if "ses_op2" in item[0])
        self.assertEqual(parent2, "ses_op1")
        session2 = opencode.parse_file(path2, parent2)
        self.assertEqual(session2.id, "ses_op2")
        self.assertEqual(session2.subagent_of, "ses_op1")
        self.assertEqual(len(session2.messages), 1)
        msg2 = session2.messages[0]
        self.assertEqual(msg2.model, "MiniMax-M2.7")
        self.assertEqual(msg2.input, 150)
        self.assertEqual(msg2.output, 75)
        self.assertEqual(msg2.cache_read, 25)

    def test_explicit_minimax_dedupe(self):
        """MiniMax sessions running on OpenCode must be excluded from OpenCode."""
        # 1. Directory under ~/.minimax
        db_path = os.path.join(FIXTURE_DIR, "opencode.db")
        discovered = opencode.discover([FIXTURE_DIR])
        sids = [p.split("::")[-1] for p, _ in discovered]
        self.assertNotIn("ses_mm_overlap1", sids)

        with self.assertRaises(ParseError):
            opencode.parse_file(f"{db_path}::ses_mm_overlap1")

        # 2. MiniMax framework_session_id match
        with mock.patch("kanjo.sources.opencode._minimax_session_ids", return_value={"ses_op1"}):
            filtered = opencode.discover([FIXTURE_DIR])
            filtered_ids = [p.split("::")[-1] for p, _ in filtered]
            self.assertNotIn("ses_op1", filtered_ids)
            with self.assertRaises(ParseError):
                opencode.parse_file(f"{db_path}::ses_op1")

    def test_stable_dedupe_key(self):
        discovered = opencode.discover([FIXTURE_DIR])
        path, parent = discovered[0]
        s1 = opencode.parse_file(path, parent)
        s2 = opencode.parse_file(path, parent)
        self.assertEqual([m.key for m in s1.messages], [m.key for m in s2.messages])
        self.assertEqual(s1.messages[0].key, "opencode:msg_1")

    def test_missing_directory(self):
        self.assertEqual(opencode.discover(["/nonexistent/opencode/path"]), [])

    def test_missing_file_raises_parse_error(self):
        with self.assertRaises(ParseError):
            opencode.parse_file("/nonexistent/opencode.db::ses_1")

    def test_minimax_db_exists_but_unreadable_skips_opencode_scan(self):
        """When MiniMax sqlite.db exists but cannot be read, skip OpenCode scan and log once to stderr."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_db = os.path.join(tmpdir, "sqlite.db")
            with open(bad_db, "wb") as f:
                f.write(b"corrupt sqlite header")

            with mock.patch.dict(os.environ, {"KANJO_MINIMAX_DIR": tmpdir}):
                err = io.StringIO()
                with mock.patch("sys.stderr", err):
                    discovered = opencode.discover([FIXTURE_DIR])

                    self.assertEqual(discovered, [])
                    err_output = err.getvalue()
                    self.assertIn("warning:", err_output)
                    self.assertIn("exists but cannot be read", err_output)
                    self.assertIn("skipping OpenCode scan", err_output)

                    # parse_file directly also raises ParseError
                    db_path = os.path.join(FIXTURE_DIR, "opencode.db")
                    with self.assertRaises(ParseError):
                        opencode.parse_file(f"{db_path}::ses_op1")

    def test_minimax_db_nonexistent_behaves_normally(self):
        """When MiniMax db doesn't exist, OpenCode scan discovers sessions normally without stderr warnings."""
        with mock.patch.dict(os.environ, {"KANJO_MINIMAX_DIR": "/nonexistent/minimax/dir"}):
            err = io.StringIO()
            with mock.patch("sys.stderr", err):
                discovered = opencode.discover([FIXTURE_DIR])

            ids = [p.split("::")[-1] for p, _ in discovered]
            self.assertIn("ses_op1", ids)
            self.assertIn("ses_op2", ids)
            self.assertNotIn("ses_mm_overlap1", ids)
            self.assertEqual(len(discovered), 2)
            self.assertEqual(err.getvalue(), "")
