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


if __name__ == "__main__":
    unittest.main()
