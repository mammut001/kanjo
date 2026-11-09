import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import pi

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_PI = os.path.join(HERE, "fixtures", "pi", "sessions")


class PiSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(pi.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = pi.discover([FIXTURE_PI])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("pi-sess-1.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = pi.discover([FIXTURE_PI])
        self.assertEqual(len(discovered), 1)
        path = discovered[0][0]
        session = pi.parse_file(path)

        self.assertEqual(session.id, "pi-sess-1")
        self.assertEqual(session.agent, "pi")
        self.assertEqual(session.cwd, "/Users/alice/Documents/GitHub/FocusApp")
        self.assertEqual(session.title, "Implement focus timer feature")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "step-5-preview")
        self.assertEqual(msg.input, 1000)
        self.assertEqual(msg.output, 500)
        self.assertEqual(msg.cache_read, 200)
        self.assertEqual(msg.cache_write, 100)
        self.assertEqual(msg.thinking, 0)
        self.assertEqual(msg.key, "pi:pi-sess-1:resp-1")
        self.assertEqual(session.tool_paths, [["/Users/alice/Documents/GitHub/FocusApp/timer.py"]])

    def test_cost_step_5_preview(self):
        discovered = pi.discover([FIXTURE_PI])
        self.assertEqual(len(discovered), 1)
        path = discovered[0][0]
        session = pi.parse_file(path)
        msg = session.messages[0]

        book = default_book()
        catalog_id, estimated = book.resolve(msg.model, agent="pi")
        self.assertEqual(catalog_id, "stepfun/step-5-preview")
        self.assertFalse(estimated)

        price = book.prices.get(catalog_id, {})
        cost = (
            (msg.input * price.get("in", 0.0) +
             msg.output * price.get("out", 0.0) +
             msg.cache_read * price.get("cache_read", 0.0) +
             msg.cache_write * price.get("cache_write", 0.0)) / 1_000_000.0
        )
        self.assertGreater(cost, 0)

    def test_dedupe_keys_stable(self):
        discovered = pi.discover([FIXTURE_PI])
        path = discovered[0][0]
        s1 = pi.parse_file(path)
        s2 = pi.parse_file(path)
        self.assertEqual([m.key for m in s1.messages], [m.key for m in s2.messages])


if __name__ == "__main__":
    unittest.main()
