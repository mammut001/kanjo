import os
import unittest

from kanjo.sources import grok

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_GROK = os.path.join(HERE, "fixtures", "grok", "sessions")


class GrokSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(grok.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = grok.discover([FIXTURE_GROK])
        self.assertEqual(len(discovered), 2)
        paths = [d[0] for d in discovered]
        parents = {os.path.basename(os.path.dirname(d[0])): d[1] for d in discovered}
        self.assertIsNone(parents.get("grok-sess-1"))
        self.assertEqual(parents.get("grok-sub-1"), "grok-sess-1")

    def test_parse_main_session(self):
        usage_path = os.path.join(
            FIXTURE_GROK,
            "%2FUsers%2Falice%2FDocuments%2FGitHub%2FFocusApp",
            "grok-sess-1",
            "usage.json",
        )
        session = grok.parse_file(usage_path)
        self.assertEqual(session.id, "grok-sess-1")
        self.assertEqual(session.agent, "grok")
        self.assertEqual(session.cwd, "/Users/alice/Documents/GitHub/FocusApp")
        self.assertEqual(session.branch, "feature/ui")
        self.assertEqual(session.title, "Fix settings toggle")
        self.assertIsNone(session.subagent_of)
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "grok-4.5")
        self.assertEqual(msg.input, 600)  # 1000 - 400 cached
        self.assertEqual(msg.output, 200)
        self.assertEqual(msg.cache_read, 400)
        self.assertEqual(msg.thinking, 50)
        self.assertEqual(msg.key, "grok:grok-sess-1:1")

    def test_parse_subagent_session(self):
        usage_path = os.path.join(
            FIXTURE_GROK,
            "%2FUsers%2Falice%2FDocuments%2FGitHub%2FFocusApp",
            "grok-sub-1",
            "usage.json",
        )
        session = grok.parse_file(usage_path)
        self.assertEqual(session.id, "grok-sub-1")
        self.assertEqual(session.subagent_of, "grok-sess-1")
        self.assertEqual(len(session.messages), 1)
        msg = session.messages[0]
        self.assertEqual(msg.input, 400)  # 500 - 100 cached
        self.assertEqual(msg.cache_read, 100)
        self.assertEqual(msg.output, 100)
        self.assertEqual(msg.thinking, 20)

    def test_dedupe_keys_stable(self):
        usage_path = os.path.join(
            FIXTURE_GROK,
            "%2FUsers%2Falice%2FDocuments%2FGitHub%2FFocusApp",
            "grok-sess-1",
            "usage.json",
        )
        s1 = grok.parse_file(usage_path)
        s2 = grok.parse_file(usage_path)
        self.assertEqual([m.key for m in s1.messages], [m.key for m in s2.messages])


if __name__ == "__main__":
    unittest.main()
