import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import devin

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DEVIN = os.path.join(HERE, "fixtures", "devin", "cli")


class DevinSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(devin.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = devin.discover([FIXTURE_DEVIN])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("sessions.db::devin-sess-1", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = devin.discover([FIXTURE_DEVIN])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = devin.parse_file(path, parent)

        self.assertEqual(session.id, "devin-sess-1")
        self.assertEqual(session.agent, "devin")
        self.assertEqual(session.cwd, "/Users/alice/Projects/devin-proj")
        self.assertEqual(session.title, "Optimize DB query")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "claude-sonnet-4-5")
        self.assertEqual(msg.input, 1200)
        self.assertEqual(msg.output, 400)
        self.assertEqual(msg.cache_read, 300)
        self.assertEqual(msg.cache_write, 50)
        self.assertEqual(msg.thinking, 60)
        self.assertEqual(msg.key, "devin:devin-sess-1:1")

    def test_pricing(self):
        discovered = devin.discover([FIXTURE_DEVIN])
        session = devin.parse_file(discovered[0][0])
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
