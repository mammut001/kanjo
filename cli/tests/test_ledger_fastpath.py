"""The ledger's meta fast path stays fast: warm scans do not reload ledger.json."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from kanjo import export
from kanjo.cache import SessionCache
from kanjo.ledger import Ledger


def _write_claude(path, sid, msg_id):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = {"type": "assistant", "timestamp": "2026-10-02T19:48:05.461Z",
           "cwd": "/tmp", "sessionId": sid, "uuid": "u-" + msg_id,
           "message": {"model": "claude-opus-4-5", "id": msg_id, "content": [],
                       "usage": {"input_tokens": 10, "output_tokens": 5}}}
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


class LedgerFastPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-fastpath-")
        self.logs = os.path.join(self.tmp, "claude")
        self.data = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.env = mock.patch.dict(os.environ, {
            "KANJO_DATA_DIR": self.data,
            "KANJO_CACHE_DIR": self.cache_dir,
        })
        self.env.start()
        self.paths = []
        for i in range(5):
            sid = "sess-%d" % i
            path = os.path.join(self.logs, "slug", sid + ".jsonl")
            _write_claude(path, sid, "msg-%d" % i)
            self.paths.append(path)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)

    def scan(self):
        calls = []
        real = Ledger._load_full

        def counting(ledger):
            calls.append(1)
            return real(ledger)

        with mock.patch.object(Ledger, "_load_full", counting):
            result = export.scan(dirs={"claude": [self.logs]}, cache=SessionCache(self.cache_dir),
                                 ledger=Ledger(self.data))
        return result, len(calls)

    def test_unchanged_broken_file_does_not_force_full_load(self):
        broken = os.path.join(self.logs, "slug", "broken.jsonl")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("{not json\n")
        self.scan()
        first, _ = self.scan()
        second, loads = self.scan()
        self.assertEqual(loads, 0)
        self.assertEqual(first.ledger, second.ledger)
        self.assertIn(broken, second.failed_files)

    def test_new_orphan_is_recorded_in_meta(self):
        self.scan()
        self.scan()
        os.remove(self.paths[0])
        result, loads = self.scan()
        self.assertEqual(loads, 1)
        self.assertIn("sess-0", [s.id for s in result.sessions])
        for _ in range(2):
            result, loads = self.scan()
            self.assertEqual(loads, 0)
            self.assertIn("sess-0", [s.id for s in result.sessions])
            self.assertEqual(result.ledger["orphaned"], 1)
        _write_claude(self.paths[0], "sess-0", "msg-0")
        for _ in range(2):
            result, _ = self.scan()
            self.assertEqual(result.ledger["orphaned"], 0)
            self.assertEqual([s.id for s in result.sessions].count("sess-0"), 1)


if __name__ == "__main__":
    unittest.main()
