"""Compatibility and recovery for proportional ledger saves."""
import json
import os
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from kanjo import export
from kanjo.ledger import Ledger


def old_ledger():
    source = subprocess.check_output(["git", "show", "origin/main:cli/kanjo/ledger.py"])
    module = types.ModuleType("kanjo.old_ledger")
    module.__package__ = "kanjo"
    exec(compile(source, "origin/main:cli/kanjo/ledger.py", "exec"), module.__dict__)
    return module.Ledger


class LedgerScalingTest(unittest.TestCase):
    def test_old_and_new_read_each_others_snapshot_and_journal(self):
        old = old_ledger()
        with tempfile.TemporaryDirectory() as root:
            for writer, reader in ((old, Ledger), (Ledger, old)):
                directory = os.path.join(root, writer.__module__)
                ledger = writer(directory)
                ledger.note_unparsed("claude", "/missing/first", error="bad")
                ledger.save()
                ledger.note_unparsed("claude", "/missing/second", error="bad")
                ledger.save()
                self.assertTrue(os.path.isfile(ledger.journal_path))
                self.assertEqual(reader(directory).entries, ledger.entries)

    def test_export_matches_old_ledger(self):
        old = old_ledger()
        with tempfile.TemporaryDirectory() as root:
            logs = os.path.join(root, "logs")
            os.makedirs(logs)
            path = os.path.join(logs, "session.jsonl")
            row = {"type": "assistant", "timestamp": "2026-10-02T19:48:05.461Z",
                   "cwd": root, "sessionId": "test-session", "uuid": "u1",
                   "message": {"model": "claude-opus-4-5", "id": "msg1", "content": [],
                               "usage": {"input_tokens": 10, "output_tokens": 5}}}
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            env = {"KANJO_DATA_DIR": os.path.join(root, "data"),
                   "KANJO_CACHE_DIR": os.path.join(root, "cache")}
            with mock.patch.dict(os.environ, env):
                with mock.patch.object(export, "Ledger", old):
                    before = export.build_export(dirs={"claude": [logs]}, home=root,
                                                 tokei_dir=os.path.join(root, "none"))
                after = export.build_export(dirs={"claude": [logs]}, home=root,
                                            tokei_dir=os.path.join(root, "none"))
            for doc in (before, after):
                doc.pop("generated_at")
                doc["ledger"].pop("updated_at")
            self.assertEqual(before, after)

    def test_interrupted_compaction_replays_journal_and_failed_replace_preserves_files(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            ledger.note_unparsed("claude", "/a", error="first")
            ledger.save()
            ledger.note_unparsed("claude", "/b", error="second")
            ledger.save()
            ledger.note_unparsed("claude", "/c", error="third")
            ledger.dirty_keys.update("force-%d" % i for i in range(501))
            with mock.patch("kanjo.ledger.os.replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    ledger.save()
            self.assertEqual(len(Ledger(root).entries), 2)
            with mock.patch("kanjo.ledger.os.unlink", side_effect=OSError("interrupted")):
                ledger.save()
            self.assertTrue(os.path.exists(ledger.journal_path))
            self.assertEqual(len(Ledger(root).entries), 3)

    def test_lazy_deletion_survives_loading_before_compaction(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(root)
            ledger.note_unparsed("claude", "/a", error="bad")
            ledger.save()
            ledger = Ledger(root)
            ledger._drop_marker("claude", "/a")
            self.assertEqual(ledger.entries, {})
