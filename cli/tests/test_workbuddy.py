import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import workbuddy

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_WB = os.path.join(HERE, "fixtures", "workbuddy", "projects")


class WorkBuddySourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(workbuddy.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = workbuddy.discover([FIXTURE_WB])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("wb-sess-1.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = workbuddy.discover([FIXTURE_WB])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = workbuddy.parse_file(path, parent)

        self.assertEqual(session.id, "wb-sess-1")
        self.assertEqual(session.agent, "workbuddy")
        self.assertEqual(session.cwd, "/Users/alice/Projects/demo")
        self.assertEqual(session.title, "Implement Login")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "GLM-5.2")
        self.assertEqual(msg.input, 1100)
        self.assertEqual(msg.output, 400)
        self.assertEqual(msg.cache_read, 300)
        self.assertEqual(msg.cache_write, 100)
        self.assertEqual(msg.thinking, 50)
        self.assertEqual(msg.key, "workbuddy:wb-sess-1:msg-1")
        self.assertEqual(session.tool_paths, [["/Users/alice/Projects/demo/login.py"]])

    def test_cost_glm52(self):
        discovered = workbuddy.discover([FIXTURE_WB])
        session = workbuddy.parse_file(discovered[0][0])
        book = default_book()
        msg = session.messages[0]
        cost, _ = book.cost(
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
