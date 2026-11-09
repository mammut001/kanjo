import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import deepseek_harness

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DSH = os.path.join(HERE, "fixtures", "deepseek_harness")


class DeepSeekHarnessSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(deepseek_harness.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = deepseek_harness.discover([FIXTURE_DSH])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("dsh-sess-1.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = deepseek_harness.discover([FIXTURE_DSH])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = deepseek_harness.parse_file(path, parent)

        self.assertEqual(session.id, "dsh-sess-1")
        self.assertEqual(session.agent, "deepseek_harness")
        self.assertEqual(session.cwd, "/Users/alice/Projects/dsh-proj")
        self.assertEqual(session.title, "Refactor deepseek harness")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "deepseek-v4-pro")
        self.assertEqual(msg.input, 1000)
        self.assertEqual(msg.output, 350)
        self.assertEqual(msg.cache_read, 500)
        self.assertEqual(msg.cache_write, 10)
        self.assertEqual(msg.thinking, 50)
        self.assertEqual(msg.key, "deepseek_harness:dsh-sess-1:1:1")

    def test_pricing(self):
        discovered = deepseek_harness.discover([FIXTURE_DSH])
        session = deepseek_harness.parse_file(discovered[0][0])
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
