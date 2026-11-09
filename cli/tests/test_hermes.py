import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import hermes

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_HERMES = os.path.join(HERE, "fixtures", "hermes")


class HermesSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(hermes.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = hermes.discover([FIXTURE_HERMES])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("state.db::hermes-sess-1", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = hermes.discover([FIXTURE_HERMES])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = hermes.parse_file(path, parent)

        self.assertEqual(session.id, "hermes-sess-1")
        self.assertEqual(session.agent, "hermes")
        self.assertEqual(session.cwd, "/Users/alice/Projects/hermes-project")
        self.assertEqual(session.title, "Fix parser bug")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "nousresearch/hermes-3-llama-3.1-70b")
        self.assertEqual(msg.input, 1200)
        self.assertEqual(msg.output, 450)
        self.assertEqual(msg.cache_read, 300)
        self.assertEqual(msg.cache_write, 100)
        self.assertEqual(msg.thinking, 60)
        self.assertEqual(msg.key, "hermes:hermes-sess-1:nousresearch/hermes-3-llama-3.1-70b:0")

    def test_pricing(self):
        discovered = hermes.discover([FIXTURE_HERMES])
        session = hermes.parse_file(discovered[0][0])
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
