import os
import json
import tempfile
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

    def test_malformed_usage_does_not_hide_valid_fixture(self):
        fixture = commandcode.discover([FIXTURE_CMD])[0][0]
        with open(fixture) as handle:
            lines = handle.readlines()
        bad = json.loads(lines[-1])
        bad["usage"]["inputTokens"] = "invalid"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "session.jsonl")
            with open(path, "w") as handle:
                handle.write(json.dumps(bad) + "\n")
                handle.writelines(lines)
            session = commandcode.parse_file(path)
        self.assertEqual(len(session.messages), 1)
        self.assertEqual(session.messages[0].input, 1700)

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

    def test_fallback_keys_do_not_collide_across_sessions(self):
        from kanjo.export import dedupe

        with tempfile.TemporaryDirectory() as tmp:
            for sid in ("sess-a", "sess-b"):
                proj = os.path.join(tmp, "projects", "p-" + sid)
                os.makedirs(proj)
                rows = [
                    {"type": "session", "id": sid, "timestamp": "2026-10-15T16:00:00Z", "cwd": "/tmp/p"},
                    {"type": "message", "timestamp": "2026-10-15T16:00:10Z",
                     "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
                    {"type": "message", "timestamp": "2026-10-15T16:00:20Z", "model": "m",
                     "message": {"role": "assistant", "content": []},
                     "usage": {"inputTokens": 10, "outputTokens": 5}},
                ]
                with open(os.path.join(proj, sid + ".jsonl"), "w") as handle:
                    for row in rows:
                        handle.write(json.dumps(row) + "\n")
            sessions = [commandcode.parse_file(p, parent)
                        for p, parent in commandcode.discover([os.path.join(tmp, "projects")])]
            self.assertEqual(len(sessions), 2)
            self.assertEqual(sum(len(s.messages) for s in dedupe(sessions)), 2)

    def test_dedupe_keys_stable(self):
        discovered = commandcode.discover([FIXTURE_CMD])
        path = discovered[0][0]
        s1 = commandcode.parse_file(path)
        s2 = commandcode.parse_file(path)
        self.assertEqual([m.key for m in s1.messages], [m.key for m in s2.messages])


if __name__ == "__main__":
    unittest.main()
