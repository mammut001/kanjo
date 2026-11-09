import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import workbuddy_ai

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_WBAI = os.path.join(HERE, "fixtures", "workbuddy_ai", "projects")


class WorkBuddyAISourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(workbuddy_ai.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = workbuddy_ai.discover([FIXTURE_WBAI])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("wbai-sess-1.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = workbuddy_ai.discover([FIXTURE_WBAI])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = workbuddy_ai.parse_file(path, parent)

        self.assertEqual(session.id, "wbai-sess-1")
        self.assertEqual(session.agent, "workbuddy_ai")
        self.assertEqual(session.cwd, "/Users/alice/Projects/intl")
        self.assertEqual(session.title, "Translate Docs")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "Balanced")
        self.assertEqual(msg.input, 700)
        self.assertEqual(msg.output, 250)
        self.assertEqual(msg.cache_read, 100)
        self.assertEqual(msg.cache_write, 0)
        self.assertEqual(msg.key, "workbuddy_ai:wbai-sess-1:msg-2")
        self.assertEqual(session.tool_paths, [["/Users/alice/Projects/intl/README.md"]])

    def test_pricing_resolution(self):
        discovered = workbuddy_ai.discover([FIXTURE_WBAI])
        session = workbuddy_ai.parse_file(discovered[0][0])
        book = default_book()
        msg = session.messages[0]
        resolved, estimated = book.resolve(msg.model, session.agent)
        self.assertTrue(estimated)
        cost = book.cost(
            msg.model,
            session.agent,
            input_tokens=msg.input,
            output_tokens=msg.output,
            cache_read=msg.cache_read,
            cache_write=msg.cache_write,
        )
        self.assertGreater(cost, 0.0)


if __name__ == "__main__":
    unittest.main()
