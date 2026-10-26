import os
import unittest

from kanjo.sources import commandcode

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_CMD = os.path.join(HERE, "fixtures", "commandcode", "projects")


class CommandCodeSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(commandcode.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = commandcode.discover([FIXTURE_CMD])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("cmd-sess-1.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = commandcode.discover([FIXTURE_CMD])
        self.assertEqual(len(discovered), 1)
        path = discovered[0][0]
        session = commandcode.parse_file(path)

        self.assertEqual(session.id, "cmd-sess-1")
        self.assertEqual(session.agent, "commandcode")
        self.assertEqual(session.cwd, "/Users/alice/Documents/GitHub/FocusApp")
        self.assertEqual(session.title, "Refactor views")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "xiaomi/mimo-v2.6-pro")
        self.assertEqual(msg.input, 1700)  # 2000 - 300 cached
        self.assertEqual(msg.output, 400)
        self.assertEqual(msg.cache_read, 300)
        self.assertEqual(msg.key, "commandcode:msg-asst-1")

    def test_dedupe_keys_stable(self):
        discovered = commandcode.discover([FIXTURE_CMD])
        path = discovered[0][0]
        s1 = commandcode.parse_file(path)
        s2 = commandcode.parse_file(path)
        self.assertEqual([m.key for m in s1.messages], [m.key for m in s2.messages])


if __name__ == "__main__":
    unittest.main()
