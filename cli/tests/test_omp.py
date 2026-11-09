import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import omp

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_OMP = os.path.join(HERE, "fixtures", "omp", "agent", "sessions")


class OMPSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(omp.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = omp.discover([FIXTURE_OMP])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("omp-sess-1.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = omp.discover([FIXTURE_OMP])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = omp.parse_file(path, parent)

        self.assertEqual(session.id, "omp-sess-1")
        self.assertEqual(session.agent, "omp")
        self.assertEqual(session.cwd, "/Users/alice/Projects/omp-proj")
        self.assertEqual(session.title, "Execute omp build")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "stepfun/step-5-preview")
        self.assertEqual(msg.input, 1000)
        self.assertEqual(msg.output, 300)
        self.assertEqual(msg.cache_read, 200)
        self.assertEqual(msg.cache_write, 40)
        self.assertEqual(msg.thinking, 50)
        self.assertEqual(msg.key, "omp:omp-sess-1:line_2")

    def test_pricing(self):
        discovered = omp.discover([FIXTURE_OMP])
        session = omp.parse_file(discovered[0][0])
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
