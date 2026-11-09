import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import qoderwork

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_QW = os.path.join(HERE, "fixtures", "qoderwork", "data")


class QoderWorkSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(qoderwork.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = qoderwork.discover([FIXTURE_QW])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("agents.db::qw-chat-1", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = qoderwork.discover([FIXTURE_QW])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = qoderwork.parse_file(path, parent)

        self.assertEqual(session.id, "qw-chat-1")
        self.assertEqual(session.agent, "qoderwork")
        self.assertEqual(session.title, "Refactor Auth Module")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "GLM-5.2")
        self.assertEqual(msg.input, 1500)
        self.assertEqual(msg.output, 500)
        self.assertEqual(msg.cache_read, 400)
        self.assertEqual(msg.cache_write, 100)
        self.assertEqual(msg.key, "qoderwork:qw-chat-1:msg-1")

    def test_pricing(self):
        discovered = qoderwork.discover([FIXTURE_QW])
        session = qoderwork.parse_file(discovered[0][0])
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
