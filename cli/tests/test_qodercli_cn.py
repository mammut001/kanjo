import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import qodercli_cn

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_QCCN = os.path.join(HERE, "fixtures", "qodercli_cn", "projects")


class QoderCLICNSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(qodercli_cn.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = qodercli_cn.discover([FIXTURE_QCCN])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("sess-cn-1.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = qodercli_cn.discover([FIXTURE_QCCN])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = qodercli_cn.parse_file(path, parent)

        self.assertEqual(session.id, "sess-cn-1")
        self.assertEqual(session.agent, "qodercli_cn")
        self.assertEqual(session.cwd, "/Users/alice/Projects/qoder-cli-cn")
        self.assertEqual(session.title, "refactor router")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "GLM-5.2")
        self.assertEqual(msg.input, 650)
        self.assertEqual(msg.output, 400)
        self.assertEqual(msg.cache_read, 300)
        self.assertEqual(msg.cache_write, 50)
        self.assertEqual(session.tool_paths, [["/Users/alice/Projects/qoder-cli-cn/router.py"]])

    def test_pricing(self):
        discovered = qodercli_cn.discover([FIXTURE_QCCN])
        session = qodercli_cn.parse_file(discovered[0][0])
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
