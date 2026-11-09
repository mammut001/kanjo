import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import mimocode

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_MIMO = os.path.join(HERE, "fixtures", "mimocode", "data")


class MiMoCodeSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(mimocode.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = mimocode.discover([FIXTURE_MIMO])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("mimocode.db::mimo-sess-1", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = mimocode.discover([FIXTURE_MIMO])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = mimocode.parse_file(path, parent)

        self.assertEqual(session.id, "mimo-sess-1")
        self.assertEqual(session.agent, "mimocode")
        self.assertEqual(session.cwd, "/Users/alice/Projects/mimo-app")
        self.assertEqual(session.title, "Implement Search")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "MiMo-V2.5-Pro")
        self.assertEqual(msg.input, 800)
        self.assertEqual(msg.output, 350)
        self.assertEqual(msg.cache_read, 250)
        self.assertEqual(msg.cache_write, 50)
        self.assertEqual(msg.thinking, 45)
        self.assertEqual(msg.key, "mimocode:mimo-sess-1:msg-1")

    def test_pricing(self):
        discovered = mimocode.discover([FIXTURE_MIMO])
        session = mimocode.parse_file(discovered[0][0])
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
