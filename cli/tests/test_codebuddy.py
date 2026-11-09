import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import codebuddy

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_CB = os.path.join(HERE, "fixtures", "codebuddy", "projects")


class CodeBuddySourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(codebuddy.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = codebuddy.discover([FIXTURE_CB])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("cb-sess-1.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = codebuddy.discover([FIXTURE_CB])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = codebuddy.parse_file(path, parent)

        self.assertEqual(session.id, "cb-sess-1")
        self.assertEqual(session.agent, "codebuddy")
        self.assertEqual(session.cwd, "/Users/alice/Projects/demo")
        self.assertEqual(session.title, "Build Demo App")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "GLM-5.2")
        self.assertEqual(msg.input, 700)
        self.assertEqual(msg.output, 500)
        self.assertEqual(msg.cache_read, 200)
        self.assertEqual(msg.cache_write, 100)
        self.assertEqual(msg.thinking, 50)
        self.assertEqual(msg.key, "codebuddy:cb-sess-1:msg-1")
        self.assertEqual(session.tool_paths, [["/Users/alice/Projects/demo/main.py"]])

    def test_cost_glm52(self):
        discovered = codebuddy.discover([FIXTURE_CB])
        session = codebuddy.parse_file(discovered[0][0])
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
