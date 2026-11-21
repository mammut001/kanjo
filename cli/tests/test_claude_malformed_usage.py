import json
import os
import tempfile
import unittest

from kanjo.sources import claude


class ClaudeMalformedUsageTest(unittest.TestCase):
    def test_bad_usage_does_not_discard_valid_messages(self):
        def row(mid, usage):
            return {"type": "assistant", "timestamp": "2026-01-01T00:00:00Z",
                    "message": {"id": mid, "model": "claude-opus-4-6", "usage": usage}}

        rows = [row("one", {"input_tokens": 10}),
                row("bad", {"input_tokens": "not a number"}),
                row("one", {"output_tokens": {"invalid": 1}}),
                row("two", {"output_tokens": 20})]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "session.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                for item in rows:
                    handle.write(json.dumps(item) + "\n")
            parsed = claude.parse_file(path)
        self.assertEqual([(m.key, m.input, m.output) for m in parsed.messages],
                         [("claude:one", 10, 0), ("claude:two", 0, 20)])
