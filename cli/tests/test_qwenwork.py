import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import qwenwork

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_QWENWORK = os.path.join(HERE, "fixtures", "qwenwork", "logs", "sessions")


class QwenWorkSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(qwenwork.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = qwenwork.discover([FIXTURE_QWENWORK])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("qw-sess-uuid-1", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = qwenwork.discover([FIXTURE_QWENWORK])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = qwenwork.parse_file(path, parent)

        self.assertEqual(session.id, "qw-sess-uuid-1")
        self.assertEqual(session.agent, "qwenwork")
        self.assertEqual(session.cwd, "/Users/alice/Projects/demo")
        self.assertEqual(session.title, "Refactor authentication flow")
        # req-1 has duplicate response completed event, so total messages should be 2, not 3
        self.assertEqual(len(session.messages), 2)

        # Message 1
        msg1 = session.messages[0]
        self.assertEqual(msg1.model, "qwork-advanced")
        # In fixture: input_tokens=1500, cache_read_input_tokens=500 -> non-cached input = 1000
        self.assertEqual(msg1.input, 1000)
        self.assertEqual(msg1.output, 300)
        self.assertEqual(msg1.cache_read, 500)
        self.assertEqual(msg1.cache_write, 0)
        self.assertEqual(msg1.key, "qwenwork:qw-sess-uuid-1:req-1")

        # Message 2 (from second segment file in sequence)
        msg2 = session.messages[1]
        self.assertEqual(msg2.model, "qmodel_latest")
        # In fixture: input_tokens=2000, cache_creation_input_tokens=200 -> non-cached input = 1800
        self.assertEqual(msg2.input, 1800)
        self.assertEqual(msg2.output, 400)
        self.assertEqual(msg2.cache_read, 0)
        self.assertEqual(msg2.cache_write, 200)
        self.assertEqual(msg2.key, "qwenwork:qw-sess-uuid-1:req-2")

        # Tool paths
        self.assertEqual(
            session.tool_paths,
            [
                ["/Users/alice/Projects/demo/auth.py"],
                ["/Users/alice/Projects/demo/utils.py"],
            ],
        )

    def test_no_double_counting_total_prompt_tokens(self):
        discovered = qwenwork.discover([FIXTURE_QWENWORK])
        session = qwenwork.parse_file(discovered[0][0])
        msg1 = session.messages[0]
        # Raw event had input_tokens=1500, cache_read_input_tokens=500.
        # Ensure input + cache_read == 1500, not 1500 + 500 = 2000.
        self.assertEqual(msg1.input + msg1.cache_read, 1500)

    def test_cost_and_pricing_resolution(self):
        discovered = qwenwork.discover([FIXTURE_QWENWORK])
        session = qwenwork.parse_file(discovered[0][0])
        book = default_book()

        # Both qwork-advanced and qmodel_latest should resolve without estimation
        for msg in session.messages:
            cost, estimated = book.cost(
                msg.model,
                session.agent,
                input_tokens=msg.input,
                output_tokens=msg.output,
                cache_read=msg.cache_read,
                cache_write=msg.cache_write,
            )
            self.assertGreater(cost, 0.0)
            self.assertFalse(estimated, f"Model {msg.model} should not be estimated")

    def test_env_roots(self):
        old_env = os.environ.get("KANJO_QWENWORK_DIR")
        try:
            os.environ["KANJO_QWENWORK_DIR"] = FIXTURE_QWENWORK
            roots = qwenwork.roots()
            self.assertEqual(roots, [FIXTURE_QWENWORK])
        finally:
            if old_env is not None:
                os.environ["KANJO_QWENWORK_DIR"] = old_env
            else:
                os.environ.pop("KANJO_QWENWORK_DIR", None)


if __name__ == "__main__":
    unittest.main()
