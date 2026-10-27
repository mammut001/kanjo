"""Unit tests for the MiniMax log parser."""

import os
import unittest

from kanjo.sources import minimax
from kanjo.sources.base import ParseError

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "minimax")
DUP_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "minimax_duplicate")


class MiniMaxParserTest(unittest.TestCase):
    def test_discover_and_parse(self):
        discovered = minimax.discover([FIXTURE_DIR])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("sqlite.db::mvs_test1", path)
        self.assertIsNone(parent)

        session = minimax.parse_file(path, parent)
        self.assertEqual(session.id, "mvs_test1")
        self.assertEqual(session.agent, "minimax")
        self.assertEqual(session.cwd, "/Users/alice/Documents/GitHub/testrepo")
        self.assertEqual(session.title, "Test Title")
        self.assertEqual(session.origin_ts, 1782884255.658)
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "minimax/MiniMax-M3")
        self.assertEqual(msg.ts, 1782884273.084)
        self.assertEqual(msg.input, 100)
        self.assertEqual(msg.output, 50)
        self.assertEqual(msg.thinking, 10)
        self.assertEqual(msg.cache_read, 20)
        self.assertEqual(msg.cache_write, 5)
        self.assertEqual(msg.key, "minimax:mvs_test1:turn_1")

        # Tool paths
        self.assertEqual(len(session.tool_paths), 1)
        self.assertEqual(session.tool_paths[0], ["/Users/alice/Documents/GitHub/testrepo/src/index.ts"])

    def test_stable_dedupe_key(self):
        discovered = minimax.discover([FIXTURE_DIR])
        path, parent = discovered[0]
        s1 = minimax.parse_file(path, parent)
        s2 = minimax.parse_file(path, parent)
        self.assertEqual([m.key for m in s1.messages], [m.key for m in s2.messages])
        self.assertEqual(s1.messages[0].key, "minimax:mvs_test1:turn_1")

    def test_missing_directory(self):
        self.assertEqual(minimax.discover(["/nonexistent/minimax/path"]), [])

    def test_missing_file_raises_parse_error(self):
        with self.assertRaises(ParseError):
            minimax.parse_file("/nonexistent/path/sqlite.db::mvs_test1")

    def test_duplicated_turn_id(self):
        """When turn_id is duplicated within a session, 1st row keeps current key and 2nd+ rows use :row_id suffix."""
        discovered = minimax.discover([DUP_FIXTURE_DIR])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = minimax.parse_file(path, parent)
        self.assertEqual(session.id, "mvs_dup1")
        self.assertEqual(len(session.messages), 4)

        keys = [m.key for m in session.messages]
        # 1st row of turn_1: retains current key format minimax:{sid}:{turn_id}
        self.assertEqual(keys[0], "minimax:mvs_dup1:turn_1")
        # 2nd row of turn_1: appends row id (2)
        self.assertEqual(keys[1], "minimax:mvs_dup1:turn_1:2")
        # 3rd row of turn_1: appends row id (3)
        self.assertEqual(keys[2], "minimax:mvs_dup1:turn_1:3")
        # 1st (and only) row of turn_2: retains current key format
        self.assertEqual(keys[3], "minimax:mvs_dup1:turn_2")

        # All keys are unique so deduplication preserves all rows
        self.assertEqual(len(set(keys)), 4)
