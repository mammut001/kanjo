import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import kimicode

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_KC = os.path.join(HERE, "fixtures", "kimicode")


class KimiCodeSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(kimicode.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = kimicode.discover([FIXTURE_KC])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("wire.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = kimicode.discover([FIXTURE_KC])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = kimicode.parse_file(path, parent)

        self.assertEqual(session.id, "kimi-sess-1")
        self.assertEqual(session.agent, "kimicode")
        self.assertEqual(session.cwd, "/Users/alice/Projects/kimi-app")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "moonshotai/kimi-k3")
        self.assertEqual(msg.input, 600)
        self.assertEqual(msg.output, 250)
        self.assertEqual(msg.cache_read, 150)
        self.assertEqual(msg.cache_write, 50)

    def test_pricing(self):
        discovered = kimicode.discover([FIXTURE_KC])
        session = kimicode.parse_file(discovered[0][0])
        book = default_book()
        msg = session.messages[0]
        cost = book.cost(
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
