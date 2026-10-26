import os
import unittest

from kanjo.sources import qwen

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_QWEN = os.path.join(HERE, "fixtures", "qwen")


class QwenSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(qwen.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = qwen.discover([FIXTURE_QWEN])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("qwen-sess-1.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = qwen.discover([FIXTURE_QWEN])
        self.assertEqual(len(discovered), 1)
        path = discovered[0][0]
        session = qwen.parse_file(path)

        self.assertEqual(session.id, "qwen-sess-1")
        self.assertEqual(session.agent, "qwen")
        self.assertEqual(session.cwd, "/Users/alice/Documents/GitHub/FocusApp")
        self.assertEqual(session.branch, "main")
        self.assertEqual(session.title, "Implement auth module")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "qwen3.8-max")
        self.assertEqual(msg.input, 700)  # 1200 - 500 cached
        self.assertEqual(msg.output, 300)
        self.assertEqual(msg.cache_read, 500)
        self.assertEqual(msg.thinking, 80)
        self.assertEqual(msg.key, "qwen:qwen-sess-1:req-qwen-1")

    def test_dedupe_keys_stable(self):
        discovered = qwen.discover([FIXTURE_QWEN])
        path = discovered[0][0]
        s1 = qwen.parse_file(path)
        s2 = qwen.parse_file(path)
        self.assertEqual([m.key for m in s1.messages], [m.key for m in s2.messages])


if __name__ == "__main__":
    unittest.main()
