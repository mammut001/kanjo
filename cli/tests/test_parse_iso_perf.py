"""Timestamp and usage-key compatibility for the export hot paths."""

import json
import unittest
from datetime import datetime, timezone

from kanjo.sources.base import parse_iso
from kanjo.sources.codex import _usage_key


class ParseHotPathTest(unittest.TestCase):
    def test_timestamp_formats_and_fraction_truncation(self):
        expected = datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc).timestamp()
        for value in ("2026-01-02T03:04:05.123456Z",
                      "2026-01-02T03:04:05.123456789Z",
                      " 2026-01-02T04:04:05.123456+01:00 ",
                      "2026-01-02T03:04:05.123456"):
            self.assertEqual(parse_iso(value), expected)
        self.assertEqual(parse_iso("2026-01-02T03:04:05Z"), int(expected))
        self.assertIsNone(parse_iso("2026-99-02T03:04:05.123Z"))
        self.assertIsNone(parse_iso([]))

    def test_usage_key_keeps_canonical_json(self):
        info = {"total_token_usage": {"z": [1, {"b": "é", "a": None}], "a": 2},
                "last_token_usage": {"output_tokens": 3, "input_tokens": 4}}
        expected = "codex:" + json.dumps([info["total_token_usage"], info["last_token_usage"]],
                                          sort_keys=True, separators=(",", ":"))
        self.assertEqual(_usage_key(info), expected)
        self.assertIsNone(_usage_key({"last_token_usage": None}))
