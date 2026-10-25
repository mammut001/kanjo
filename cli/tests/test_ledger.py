"""Permanent ledger: deleted logs stay in the export, and only a new signature rewrites an entry."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from kanjo import cli
from kanjo.cache import _load_session
from kanjo.export import build_export
from kanjo.ledger import Ledger

from tests.support import ALICE

SID = "11111111-1111-1111-1111-111111111111"


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-ledger-")
        self.data = os.path.join(self.tmp, "data")
        self.cache = os.path.join(self.tmp, "cache")
        self.projects = os.path.join(self.tmp, "claude", "projects")
        self.codex = os.path.join(self.tmp, "codex")
        self.agy = os.path.join(self.tmp, "agy")
        os.makedirs(self.data)
        os.makedirs(self.codex)
        os.makedirs(self.agy)
        self.env = mock.patch.dict(os.environ, {
            "KANJO_DATA_DIR": self.data,
            "KANJO_CACHE_DIR": self.cache,
            "KANJO_CLAUDE_DIR": self.projects,
            "KANJO_CODEX_DIR": self.codex,
            "KANJO_ANTIGRAVITY_DIR": self.agy,
            "KANJO_TOKEI_DIR": os.path.join(self.tmp, "no-tokei"),
            "KANJO_CLAUDE_CONFIG": os.path.join(self.tmp, "no-claude.json"),
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)

    def scan_dirs(self):
        return {"claude": [self.projects], "codex": [self.codex], "antigravity": [self.agy]}

    def write_log(self, output=5):
        slug = os.path.join(self.projects, "slug")
        os.makedirs(slug, exist_ok=True)
        path = os.path.join(slug, SID + ".jsonl")
        line = {
            "type": "assistant",
            "timestamp": "2026-10-02T19:48:05.461Z",
            "cwd": self.tmp,
            "sessionId": SID,
            "uuid": "u1",
            "message": {
                "model": "claude-opus-5-5",
                "id": "msg_test_1",
                "content": [],
                "usage": {"input_tokens": 10, "output_tokens": output},
            },
        }
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
        return path

    def export(self):
        return build_export(dirs=self.scan_dirs(), cache=None, home=ALICE,
                             tokei_dir=os.path.join(self.tmp, "no-tokei"))

    def _ledger_bytes(self):
        with open(os.path.join(self.data, "ledger.json"), "rb") as handle:
            return handle.read()

    def ids(self, doc):
        found = []
        for project in doc["projects"]:
            found.extend(s["id"] for s in project["sessions_detail"])
        for name in ("unattributed", "excluded"):
            found.extend(s["id"] for s in doc["buckets"][name]["sessions_detail"])
        return found

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_deleted_log_stays_in_export_and_reimport_updates_once(self):
        path = self.write_log(5)
        doc = self.export()  # --no-cache path: cache is None, the ledger is still written
        self.assertIn(SID, self.ids(doc))
        self.assertEqual((doc["ledger"]["sessions"], doc["ledger"]["orphaned"]), (1, 0))
        self.assertFalse(any(name.endswith(".tmp") for name in os.listdir(self.data)))
        blob = self._ledger_bytes()
        first = next(iter(Ledger(directory=self.data).entries.values()))

        doc = self.export()
        self.assertEqual(self._ledger_bytes(), blob)
        self.assertEqual(doc["ledger"]["orphaned"], 0)

        os.remove(path)
        doc = self.export()
        self.assertIn(SID, self.ids(doc))
        self.assertEqual((doc["ledger"]["sessions"], doc["ledger"]["orphaned"]), (1, 1))
        self.assertEqual(self._ledger_bytes(), blob)

        self.write_log(9)
        # imported_at is whole seconds; force a later clock so the rewrite is visible.
        with mock.patch("kanjo.ledger.time.time", return_value=time.time() + 5):
            doc = self.export()
        self.assertEqual((doc["ledger"]["sessions"], doc["ledger"]["orphaned"]), (1, 0))
        ledger = Ledger(directory=self.data)
        self.assertEqual(len(ledger.entries), 1)
        entry = next(iter(ledger.entries.values()))
        self.assertNotEqual(entry["file_sig"], first["file_sig"])
        self.assertNotEqual(entry["imported_at"], first["imported_at"])
        self.assertEqual(entry["source_path"], path)
        self.assertEqual(_load_session(entry["session"]).messages[0].output, 9)
        blob = self._ledger_bytes()
        self.export()
        self.assertEqual(self._ledger_bytes(), blob)
        self.assertFalse(any(name.endswith(".tmp") for name in os.listdir(self.data)))

    def test_atomic_write_leaves_no_temp_file(self):
        self.write_log()
        self.export()
        self.assertEqual([name for name in os.listdir(self.data) if name.endswith(".tmp")], [])
        ledger = Ledger(directory=self.data)
        ledger.dirty = True
        with mock.patch("kanjo.ledger.os.replace", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                ledger.save()
        self.assertEqual([name for name in os.listdir(self.data) if name.endswith(".tmp")], [])
        with open(os.path.join(self.data, "ledger.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["version"], 1)

    def test_forget_orphans_requires_yes(self):
        path = self.write_log()
        self.export()
        os.remove(path)
        code, out, _ = self.cli("ledger", "--forget-orphans")
        self.assertEqual(code, 0)
        self.assertIn("--yes", out)
        self.assertEqual(len(Ledger(directory=self.data).entries), 1)
        code, out, _ = self.cli("ledger", "--forget-orphans", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("forgot 1", out)
        self.assertEqual(Ledger(directory=self.data).entries, {})
        self.assertFalse(any(name.endswith(".tmp") for name in os.listdir(self.data)))

    def test_cli_no_cache_updates_ledger_and_doctor_prints_it(self):
        self.write_log()
        code, out, _ = self.cli("export", "--no-cache")
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["ledger"]["sessions"], 1)
        self.assertEqual(doc["ledger"]["orphaned"], 0)
        code, out, _ = self.cli("ledger")
        self.assertEqual(code, 0)
        self.assertIn(os.path.join(self.data, "ledger.json"), out)
        self.assertIn("sessions: 1", out)
        self.assertIn("orphaned: 0", out)
        self.assertIn("size:", out)
        code, out, _ = self.cli("doctor", "--no-cache")
        self.assertEqual(code, 0)
        self.assertIn("ledger: %s" % os.path.join(self.data, "ledger.json"), out)
        self.assertIn("orphaned=0", out)


if __name__ == "__main__":
    unittest.main()
