import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import qoder_ide

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_QI = os.path.join(HERE, "fixtures", "qoder_ide", "SharedClientCache", "cache", "db")


class QoderIDESourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(qoder_ide.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = qoder_ide.discover([FIXTURE_QI])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("local.db::qi-sess-1", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = qoder_ide.discover([FIXTURE_QI])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = qoder_ide.parse_file(path, parent)

        self.assertEqual(session.id, "qi-sess-1")
        self.assertEqual(session.agent, "qoder_ide")
        self.assertEqual(session.cwd, "/Users/alice/Projects/qoder-app")
        self.assertEqual(session.title, "Refactor Auth")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "GLM-5.2")
        self.assertEqual(msg.input, 800)  # 1000 prompt - 200 cached
        self.assertEqual(msg.output, 300)
        self.assertEqual(msg.cache_read, 200)
        self.assertEqual(msg.cache_write, 0)
        self.assertEqual(msg.thinking, 40)
        self.assertEqual(msg.key, "qoder_ide:qi-sess-1:req-1")

    def test_pricing(self):
        discovered = qoder_ide.discover([FIXTURE_QI])
        session = qoder_ide.parse_file(discovered[0][0])
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
