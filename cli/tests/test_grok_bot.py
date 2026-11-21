import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import grok_bot

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_GB = os.path.join(HERE, "fixtures", "grok_bot")


class GrokBotSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(grok_bot.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = grok_bot.discover([FIXTURE_GB])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("transcript.blob", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = grok_bot.discover([FIXTURE_GB])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = grok_bot.parse_file(path, parent)

        self.assertEqual(session.id, "grok-sess-1")
        self.assertEqual(session.agent, "grok_bot")
        self.assertEqual(session.cwd, "/Users/alice/Projects/grok-demo")
        self.assertEqual(session.title, "Build Grok UI")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "grok")
        self.assertEqual(msg.input, 0)
        self.assertEqual(msg.output, 0)
        self.assertEqual(msg.key, "grok_bot:grok-sess-1:req-1")

    def test_pricing_zero_tokens(self):
        discovered = grok_bot.discover([FIXTURE_GB])
        session = grok_bot.parse_file(discovered[0][0])
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
        self.assertEqual(cost, 0.0)

    def test_blobs_load_once_per_change(self):
        import json
        import tempfile
        from unittest import mock

        n = 30
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(n):
                blob = {"value": {"entries": [
                    {"id": "e%d" % i, "kind": "send-message", "requestId": "r%d" % i,
                     "timestampMs": 1790000000000 + i},
                ]}}
                with open(os.path.join(tmp, "t%02d.blob" % i), "w") as handle:
                    json.dump(blob, handle)
            roster = {"value": {"rows": [{"id": "s%d" % i, "lastMessageId": "e%d" % i,
                                          "title": "T%d" % i} for i in range(n)]}}
            with open(os.path.join(tmp, "roster.blob"), "w") as handle:
                json.dump(roster, handle)

            real_load = grok_bot._load_blob
            calls = []

            def counting(path):
                calls.append(path)
                return real_load(path)

            with mock.patch.object(grok_bot, "_load_blob", counting):
                sessions = [grok_bot.parse_file(p, parent) for p, parent in grok_bot.discover([tmp])]
            self.assertEqual(sorted(s.id for s in sessions), sorted("s%d" % i for i in range(n)))
            self.assertLessEqual(len(calls), 2 * (n + 1))


if __name__ == "__main__":
    unittest.main()
