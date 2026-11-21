"""Parity dump tests — same scenarios as macOS / Windows ParityDumpTests."""

from __future__ import annotations

import json
import os
import unittest

from kanjo.tui.parity_dump import build_parity_dump


def load_sample_fixture() -> dict:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(root, "ui", "fixtures", "sample.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class ParityDumpTests(unittest.TestCase):
    def test_dump(self) -> None:
        doc = load_sample_fixture()
        result = build_parity_dump(doc)
        dump_path = os.environ.get("KANJO_PARITY_DUMP")
        if dump_path:
            from kanjo.tui.parity_dump import formatted_json
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(formatted_json(result) + "\n")
            return
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        golden_path = os.path.join(root, "parity", "tui.json")
        with open(golden_path, "r", encoding="utf-8") as f:
            expected = json.load(f)
        self.assertEqual(expected, result, "TUI parity dump changed; regenerate golden")


if __name__ == "__main__":
    unittest.main()