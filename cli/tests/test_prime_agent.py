import os
import unittest

from kanjo.pricing import default_book
from kanjo.sources import prime_agent

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_PRIME = os.path.join(HERE, "fixtures", "prime_agent", "agent", "sessions")


class PrimeAgentSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(prime_agent.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = prime_agent.discover([FIXTURE_PRIME])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("prime-sess-1.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = prime_agent.discover([FIXTURE_PRIME])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = prime_agent.parse_file(path, parent)

        self.assertEqual(session.id, "prime-sess-1")
        self.assertEqual(session.agent, "prime_agent")
        self.assertEqual(session.cwd, "/Users/alice/Projects/prime-proj")
        self.assertEqual(session.title, "Run prime pipeline")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "stepfun/step-5-preview")
        self.assertEqual(msg.input, 1200)
        self.assertEqual(msg.output, 400)
        self.assertEqual(msg.cache_read, 300)
        self.assertEqual(msg.cache_write, 50)
        self.assertEqual(msg.thinking, 60)
        self.assertEqual(msg.key, "prime_agent:prime-sess-1:line_2")

    def test_pricing(self):
        discovered = prime_agent.discover([FIXTURE_PRIME])
        session = prime_agent.parse_file(discovered[0][0])
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
