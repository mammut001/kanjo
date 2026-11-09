import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import musecode

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_MC = os.path.join(HERE, "fixtures", "musecode")


class MuseCodeSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(musecode.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = musecode.discover([FIXTURE_MC])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("session.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = musecode.discover([FIXTURE_MC])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = musecode.parse_file(path, parent)

        self.assertEqual(session.id, "muse-sess-1")
        self.assertEqual(session.agent, "musecode")
        self.assertEqual(session.cwd, "/Users/alice/Projects/muse-demo")
        self.assertEqual(session.branch, "feature/muse-ui")
        self.assertEqual(session.title, "Implement Muse UI")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "muse-spark-1.2")
        self.assertEqual(msg.input, 700)
        self.assertEqual(msg.output, 400)
        self.assertEqual(msg.cache_read, 300)
        self.assertEqual(msg.cache_write, 100)
        self.assertEqual(msg.thinking, 50)
        self.assertEqual(msg.key, "musecode:muse-sess-1:rec-1")

    def test_pricing(self):
        discovered = musecode.discover([FIXTURE_MC])
        session = musecode.parse_file(discovered[0][0])
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
