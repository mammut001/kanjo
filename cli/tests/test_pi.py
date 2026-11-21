import os
import json
import tempfile
import unittest

from kanjo.pricing import default_book
from kanjo.sources import pi

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_PI = os.path.join(HERE, "fixtures", "pi", "sessions")


class PiSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(pi.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = pi.discover([FIXTURE_PI])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("pi-sess-1.jsonl", path)
        self.assertIsNone(parent)

    def test_malformed_usage_does_not_hide_valid_fixture(self):
        fixture = pi.discover([FIXTURE_PI])[0][0]
        with open(fixture) as handle:
            lines = handle.readlines()
        bad = json.loads(lines[-1])
        bad["message"]["usage"]["input"] = "invalid"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "session.jsonl")
            with open(path, "w") as handle:
                handle.write(json.dumps(bad) + "\n")
                handle.writelines(lines)
            session = pi.parse_file(path)
        self.assertEqual(len(session.messages), 1)
        self.assertEqual(session.messages[0].input, 1000)

    def test_parse_session(self):
        discovered = pi.discover([FIXTURE_PI])
        self.assertEqual(len(discovered), 1)
        path = discovered[0][0]
        session = pi.parse_file(path)

        self.assertEqual(session.id, "pi-sess-1")
        self.assertEqual(session.agent, "pi")
        self.assertEqual(session.cwd, "/Users/alice/Documents/GitHub/FocusApp")
        self.assertEqual(session.title, "Implement focus timer feature")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "step-5-preview")
        self.assertEqual(msg.input, 1000)
        self.assertEqual(msg.output, 500)
        self.assertEqual(msg.cache_read, 200)
        self.assertEqual(msg.cache_write, 100)
        self.assertEqual(msg.thinking, 0)
        self.assertEqual(msg.key, "pi:resp:resp-1")
        self.assertEqual(session.tool_paths, [["/Users/alice/Documents/GitHub/FocusApp/timer.py"]])

    def test_cost_step_5_preview(self):
        discovered = pi.discover([FIXTURE_PI])
        self.assertEqual(len(discovered), 1)
        path = discovered[0][0]
        session = pi.parse_file(path)
        msg = session.messages[0]

        book = default_book()
        catalog_id, estimated = book.resolve(msg.model, agent="pi")
        self.assertEqual(catalog_id, "stepfun/step-5-preview")
        self.assertFalse(estimated)

        price = book.prices.get(catalog_id, {})
        cost = (
            (msg.input * price.get("in", 0.0) +
             msg.output * price.get("out", 0.0) +
             msg.cache_read * price.get("cache_read", 0.0) +
             msg.cache_write * price.get("cache_write", 0.0)) / 1_000_000.0
        )
        self.assertGreater(cost, 0)

    def test_fork_copies_are_billed_once(self):
        from kanjo.export import dedupe

        def entry(eid, role, ts, response_id=None):
            msg = {"role": role, "content": [{"type": "text", "text": "hi"}]}
            if role == "assistant":
                msg.update({"model": "step-5-preview", "usage": {"input": 10, "output": 5}})
                if response_id:
                    msg["responseId"] = response_id
            return {"type": "message", "id": eid, "timestamp": ts, "message": msg}

        copied = [
            entry("e1", "user", "2026-11-08T10:00:01.000Z"),
            entry("e2", "assistant", "2026-11-08T10:00:02.000Z", "msg_01A"),
            entry("e3", "user", "2026-11-08T10:00:03.000Z"),
            entry("e4", "assistant", "2026-11-08T10:00:04.000Z"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proj = os.path.join(tmp, "--proj--")
            os.makedirs(proj)
            header = {"type": "session", "version": 3, "id": "orig", "timestamp": "2026-11-08T10:00:00.000Z", "cwd": "/tmp/p"}
            with open(os.path.join(proj, "2026-11-08T10-00-00_orig.jsonl"), "w") as handle:
                for row in [header] + copied:
                    handle.write(json.dumps(row) + "\n")
            fork_header = dict(header, id="fork", timestamp="2026-11-08T11:00:00.000Z",
                               parentSession=os.path.join(proj, "2026-11-08T10-00-00_orig.jsonl"))
            extra = [entry("e5", "user", "2026-11-08T11:00:01.000Z"),
                     entry("e6", "assistant", "2026-11-08T11:00:02.000Z", "msg_01B")]
            with open(os.path.join(proj, "2026-11-08T11-00-00_fork.jsonl"), "w") as handle:
                for row in [fork_header] + copied + extra:
                    handle.write(json.dumps(row) + "\n")
            sessions = [pi.parse_file(p, parent) for p, parent in pi.discover([tmp])]
            self.assertEqual(len(sessions), 2)
            self.assertEqual(sum(len(s.messages) for s in dedupe(sessions)), 3)

    def test_dedupe_keys_stable(self):
        discovered = pi.discover([FIXTURE_PI])
        path = discovered[0][0]
        s1 = pi.parse_file(path)
        s2 = pi.parse_file(path)
        self.assertEqual([m.key for m in s1.messages], [m.key for m in s2.messages])


if __name__ == "__main__":
    unittest.main()
