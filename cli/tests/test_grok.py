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


FIXTURE_ACP = os.path.join(HERE, "fixtures", "grok_acp", "sessions")
ACP_CWD = "%2FUsers%2Falice%2FDocuments%2FGitHub%2FNotes"


def _acp(session_id, name="updates.jsonl"):
    return os.path.join(FIXTURE_ACP, ACP_CWD, session_id, name)


class GrokUpdatesFormatTest(unittest.TestCase):
    """Newer Grok CLI builds write only updates.jsonl (turn_completed), no usage.json."""

    def test_discover_prefers_updates_jsonl(self):
        found = {os.path.basename(os.path.dirname(p)): p for p, _ in grok.discover([FIXTURE_ACP])}
        self.assertEqual(set(found), {"grok-acp-1", "grok-mix-1", "grok-empty-1"})
        self.assertTrue(all(p.endswith("updates.jsonl") for p in found.values()))

    def test_old_fixture_still_discovers_usage_json(self):
        paths = [p for p, _ in grok.discover([FIXTURE_GROK])]
        self.assertTrue(all(p.endswith("usage.json") for p in paths))

    def test_turn_completed_only_session(self):
        session = grok.parse_file(_acp("grok-acp-1"))
        self.assertEqual(session.id, "grok-acp-1")
        self.assertEqual(session.cwd, "/Users/alice/Documents/GitHub/Notes")
        self.assertEqual(session.remote_hints, {"/Users/alice/Documents/GitHub/Notes/": "https://github.com/alice/Notes.git"})
        # p-1 (one model) + p-3 (two models); the empty, usage-less and broken records add nothing.
        self.assertEqual(len(session.messages), 3)
        first = session.messages[0]
        self.assertEqual(first.key, "grok:grok-acp-1:p:p-1")
        self.assertEqual(first.model, "grok-4.7-build")
        self.assertEqual(first.input, 1000)  # 5000 - 4000 cached
        self.assertEqual(first.cache_read, 4000)
        self.assertEqual(first.output, 300)
        self.assertEqual(first.thinking, 120)
        self.assertEqual(first.ts, 1794564060.0)  # 2026-11-13T10:01:00Z
        keys = [m.key for m in session.messages[1:]]
        self.assertEqual(keys, ["grok:grok-acp-1:p:p-3:grok-4.7-build", "grok:grok-acp-1:p:p-3:grok-4.7-build-fast"])
        fast = session.messages[2]
        self.assertEqual((fast.input, fast.cache_read, fast.output), (150, 50, 20))
        self.assertEqual(session.ended, 1794564300.0)

    def test_turn_completed_generation_time(self):
        session = grok.parse_file(_acp("grok-acp-1"))
        self.assertEqual([m.gen_s for m in session.messages], [6.0, 2.0, 0.5])

    def test_usage_json_wins_for_the_same_turn(self):
        session = grok.parse_file(_acp("grok-mix-1"))
        by_key = {m.key: m for m in session.messages}
        self.assertEqual(set(by_key), {"grok:grok-mix-1:2", "grok:grok-mix-1:p:m-1"})
        kept = by_key["grok:grok-mix-1:2"]  # from usage.json, not turn_completed m-2
        self.assertEqual((kept.input, kept.cache_read, kept.output, kept.model), (500, 300, 80, "grok-4.6-build"))
        added = by_key["grok:grok-mix-1:p:m-1"]  # turn usage.json dropped
        self.assertEqual((added.input, added.cache_read, added.output), (300, 100, 40))
        self.assertEqual(session.title, "Tidy notes")
        self.assertEqual(session.branch, "main")

    def test_same_session_from_any_file(self):
        a = grok.parse_file(_acp("grok-mix-1"))
        b = grok.parse_file(_acp("grok-mix-1", "usage.json"))
        c = grok.parse_file(os.path.dirname(_acp("grok-mix-1")))
        self.assertEqual([m.key for m in a.messages], [m.key for m in b.messages])
        self.assertEqual([m.key for m in a.messages], [m.key for m in c.messages])

    def test_session_without_turns(self):
        session = grok.parse_file(_acp("grok-empty-1"))
        self.assertEqual(session.messages, [])


if __name__ == "__main__":
    unittest.main()
