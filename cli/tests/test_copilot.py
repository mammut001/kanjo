"""Unit tests for the Copilot CLI parser."""

import os
import unittest

from kanjo.sources import copilot
from kanjo.sources.base import ParseError

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "copilot")
FIXTURE_DB_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "copilot_db")


class CopilotParserTest(unittest.TestCase):
    def test_discover_and_parse_events(self):
        discovered = copilot.discover([FIXTURE_DIR])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertTrue(path.endswith("events.jsonl"))
        self.assertIsNone(parent)

        session = copilot.parse_file(path, parent)
        self.assertEqual(session.id, "ses-copilot-1")
        self.assertEqual(session.agent, "copilot")
        self.assertEqual(session.cwd, "/Users/alice/Documents/GitHub/testrepo")
        self.assertEqual(session.branch, "main")
        self.assertEqual(session.title, "Fix bug in app")
        self.assertEqual(session.remote_hints.get("/Users/alice/Documents/GitHub/testrepo"), "https://github.com/alice/testrepo")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "claude-haiku-4.5")
        self.assertEqual(msg.input, 1000)
        self.assertEqual(msg.output, 80)
        self.assertEqual(msg.thinking, 20)
        self.assertEqual(msg.cache_read, 100)
        self.assertEqual(msg.cache_write, 50)
        self.assertEqual(msg.key, "copilot:ses-copilot-1:claude-haiku-4.5")

        # Tool paths from codeChanges
        self.assertEqual(len(session.tool_paths), 1)
        self.assertEqual(session.tool_paths[0], ["/Users/alice/Documents/GitHub/testrepo/src/fix.py"])

    def test_fallback_to_session_store_db(self):
        discovered = copilot.discover([FIXTURE_DB_DIR])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("session-store.db::ses_db_1", path)

        session = copilot.parse_file(path, parent)
        self.assertEqual(session.id, "ses_db_1")
        self.assertEqual(session.cwd, "/Users/alice/Documents/GitHub/testrepo")
        self.assertEqual(session.branch, "main")
        self.assertEqual(len(session.messages), 1)
        msg = session.messages[0]
        self.assertEqual(msg.model, "gpt-5.6-luna")
        self.assertEqual(msg.input, 500)
        self.assertEqual(msg.output, 40)
        self.assertEqual(msg.cache_read, 10)
        self.assertEqual(msg.cache_write, 5)
        self.assertEqual(msg.key, "copilot:ses_db_1:1")

    def test_stable_dedupe_key(self):
        discovered = copilot.discover([FIXTURE_DIR])
        path, parent = discovered[0]
        s1 = copilot.parse_file(path, parent)
        s2 = copilot.parse_file(path, parent)
        self.assertEqual([m.key for m in s1.messages], [m.key for m in s2.messages])
        self.assertEqual(s1.messages[0].key, "copilot:ses-copilot-1:claude-haiku-4.5")

    def test_missing_directory(self):
        self.assertEqual(copilot.discover(["/nonexistent/copilot/path"]), [])

    def test_missing_file_raises_parse_error(self):
        with self.assertRaises(ParseError):
            copilot.parse_file("/nonexistent/events.jsonl")
