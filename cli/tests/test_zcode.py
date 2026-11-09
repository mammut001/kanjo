import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import zcode

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_ZC = os.path.join(HERE, "fixtures", "zcode", "cli", "db")


class ZCodeSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(zcode.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = zcode.discover([FIXTURE_ZC])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("db.sqlite::zc-sess-1", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = zcode.discover([FIXTURE_ZC])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = zcode.parse_file(path, parent)

        self.assertEqual(session.id, "zc-sess-1")
        self.assertEqual(session.agent, "zcode")
        self.assertEqual(session.cwd, "/Users/alice/Projects/zcode-app")
        self.assertEqual(session.title, "Add caching layer")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "GLM-5.2")
        self.assertEqual(msg.input, 1000)
        self.assertEqual(msg.output, 600)
        self.assertEqual(msg.cache_read, 400)
        self.assertEqual(msg.cache_write, 100)
        self.assertEqual(msg.thinking, 100)
        self.assertEqual(msg.key, "zcode:zc-sess-1:mu-1")

    def test_pricing(self):
        discovered = zcode.discover([FIXTURE_ZC])
        session = zcode.parse_file(discovered[0][0])
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
