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
from kanjo import disk
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

    def test_concurrent_saves_use_unique_tmp_paths(self):
        l1 = Ledger(directory=self.data)
        l2 = Ledger(directory=self.data)
        l1.entries = {"a": {"test": 1}}
        l1.dirty = True
        l2.entries = {"b": {"test": 2}}
        l2.dirty = True

        observed_tmps = []
        real_open = open

        def tracking_open(file, *args, **kwargs):
            if isinstance(file, str) and file.endswith(".tmp"):
                observed_tmps.append(file)
            return real_open(file, *args, **kwargs)

        with mock.patch("kanjo.ledger.open", side_effect=tracking_open):
            l1.save()
            l2.save()

        self.assertEqual(len(observed_tmps), 2)
        self.assertNotEqual(observed_tmps[0], observed_tmps[1])
        self.assertTrue(observed_tmps[0].endswith(".tmp"))
        self.assertTrue(observed_tmps[1].endswith(".tmp"))
        self.assertIn(str(os.getpid()), observed_tmps[0])
        self.assertIn(str(os.getpid()), observed_tmps[1])
        self.assertEqual([name for name in os.listdir(self.data) if name.endswith(".tmp")], [])

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

    def disk_roots(self):
        return {
            "claude_projects": [self.projects],
            "scratch": os.path.join(self.tmp, "scratch"),
            "codex_dirs": [self.codex],
            "antigravity_dirs": [self.agy],
            "grok": os.path.join(self.tmp, "grok"),
            "claude_app": os.path.join(self.tmp, "app"),
        }

    def codex_sessions(self, doc):
        found = [e for a in doc["agents"] if a["agent"] == "codex" for e in a["entries"] if e["kind"] == "sessions"]
        self.assertEqual(len(found), 1, found)
        return found[0]

    def output_of(self, doc, sid):
        for project in doc["projects"]:
            for session in project["sessions_detail"]:
                if session["id"] == sid:
                    return session["tokens"]["output"]
        for name in ("unattributed", "excluded"):
            for session in doc["buckets"][name]["sessions_detail"]:
                if session["id"] == sid:
                    return session["tokens"]["output"]
        return None

    def write_rollout(self, name, session_id, output):
        path = os.path.join(self.codex, "sessions", "2026", "07", "01", "rollout-%s.jsonl" % name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        meta = {"id": session_id, "cwd": self.tmp, "timestamp": "2026-07-01T01:00:03.000Z"}
        usage = {
            "type": "token_count",
            "info": {
                "total_token_usage": {"input_tokens": 10, "output_tokens": output},
                "last_token_usage": {"input_tokens": 10, "output_tokens": output, "cached_input_tokens": 0},
            },
        }
        lines = [
            {"timestamp": "2026-07-01T01:00:03.000Z", "type": "session_meta", "payload": meta},
            {"timestamp": "2026-07-01T01:00:0%d.000Z" % (4 + output), "type": "event_msg", "payload": usage},
        ]
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(line) + "\n" for line in lines))
        return path

    def test_same_session_id_records_every_file_and_orphans_when_all_are_gone(self):
        same = "019f1750-7277-7f50-8187-804ff9c04f25"
        path_a = self.write_rollout("a", same, 2)
        doc = self.export()
        self.assertEqual(self.output_of(doc, same), 2)
        path_b = self.write_rollout("b", same, 3)
        doc = self.export()
        self.assertEqual(self.ids(doc).count(same), 1)
        self.assertEqual(self.output_of(doc, same), 5)
        sessions = [entry for entry in Ledger(directory=self.data).entries.values() if "session" in entry]
        self.assertEqual(len(sessions), 1)
        entry = sessions[0]
        self.assertEqual(entry["source_paths"], sorted([path_a, path_b]))
        self.assertEqual(entry["source_path"], sorted([path_a, path_b])[0])
        counted = self.codex_sessions(disk.report(roots=self.disk_roots()))
        self.assertEqual((counted["imported_files"], counted["log_files"], counted["blocked"]), (2, 2, []))
        blob = self._ledger_bytes()
        self.export()
        self.assertEqual(self._ledger_bytes(), blob)
        os.remove(path_a)
        doc = self.export()
        self.assertEqual(self.ids(doc).count(same), 1)
        self.assertEqual(self.output_of(doc, same), 3)
        self.assertEqual(doc["ledger"]["orphaned"], 0)
        os.remove(path_b)
        doc = self.export()
        self.assertEqual(self.output_of(doc, same), 5)
        self.assertGreaterEqual(doc["ledger"]["orphaned"], 1)
        self.assertEqual(doc["ledger"]["empty"], 0)
        self.assertEqual(doc["ledger"]["errors"], 0)

    def test_empty_log_is_imported_and_not_exported(self):
        path = os.path.join(self.codex, "rollout-empty.jsonl")
        os.makedirs(self.codex, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")
        doc = self.export()
        self.assertNotIn("rollout-empty", self.ids(doc))
        self.assertEqual((doc["ledger"]["sessions"], doc["ledger"]["empty"], doc["ledger"]["errors"]), (0, 1, 0))
        ledger = Ledger(directory=self.data)
        markers = [entry for entry in ledger.entries.values() if entry.get("empty")]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["source_paths"], [path])
        self.assertNotIn("session", markers[0])
        self.assertNotIn("error", markers[0])
        counted = self.codex_sessions(disk.report(roots=self.disk_roots()))
        self.assertEqual((counted["imported_files"], counted["log_files"], counted["blocked"]), (1, 1, []))
        code, out, _ = self.cli("ledger")
        self.assertEqual(code, 0)
        self.assertIn("empty: 1", out)
        self.assertIn("errors: 0", out)
        blob = self._ledger_bytes()
        doc = self.export()
        self.assertEqual(self._ledger_bytes(), blob)
        self.assertNotIn("rollout-empty", self.ids(doc))
        os.remove(path)
        doc = self.export()
        self.assertNotIn("rollout-empty", self.ids(doc))
        self.assertEqual(doc["ledger"]["sessions"], 0)

    def test_parse_error_log_is_imported_and_counted_under_errors(self):
        path = os.path.join(self.codex, "rollout-bad.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("this is not json\n")
        doc = self.export()
        self.assertEqual(self.ids(doc), [])
        self.assertEqual(doc["buckets"]["parse_failed"]["files"], [path])
        self.assertEqual((doc["ledger"]["sessions"], doc["ledger"]["empty"], doc["ledger"]["errors"]), (0, 0, 1))
        ledger = Ledger(directory=self.data)
        markers = [entry for entry in ledger.entries.values() if "error" in entry]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["source_paths"], [path])
        self.assertTrue(markers[0]["error"])
        self.assertNotIn("session", markers[0])
        self.assertNotIn("empty", markers[0])
        counted = self.codex_sessions(disk.report(roots=self.disk_roots()))
        self.assertEqual((counted["imported_files"], counted["log_files"], counted["blocked"]), (1, 1, []))
        code, out, _ = self.cli("ledger")
        self.assertEqual(code, 0)
        self.assertIn("errors: 1", out)
        self.assertIn("empty: 0", out)
        blob = self._ledger_bytes()
        self.export()
        self.assertEqual(self._ledger_bytes(), blob)

    def test_old_ledger_without_source_paths_still_imports(self):
        path = self.write_log()
        self.export()
        ledger_path = os.path.join(self.data, "ledger.json")
        with open(ledger_path, encoding="utf-8") as handle:
            stored = json.load(handle)
        raw = next(iter(stored["entries"].values()))
        raw.pop("source_paths", None)
        raw.pop("path_sigs", None)
        self.assertEqual(raw["source_path"], path)
        with open(ledger_path, "w", encoding="utf-8") as handle:
            json.dump(stored, handle)
            handle.write("\n")
        loaded = Ledger(directory=self.data)
        entry = next(iter(loaded.entries.values()))
        self.assertEqual(entry["source_paths"], [path])
        self.assertEqual(entry["source_path"], path)
        with open(ledger_path, encoding="utf-8") as handle:
            on_disk = next(iter(json.load(handle)["entries"].values()))
        self.assertNotIn("source_paths", on_disk)
        counted = disk.report(roots=self.disk_roots())
        claude = [e for a in counted["agents"] if a["agent"] == "claude" for e in a["entries"] if e["id"] == "claude:sessions"]
        self.assertEqual(len(claude), 1)
        self.assertEqual((claude[0]["imported_files"], claude[0]["log_files"], claude[0]["blocked"]), (1, 1, []))
        os.remove(path)
        doc = self.export()
        self.assertIn(SID, self.ids(doc))
        self.assertEqual(doc["ledger"]["orphaned"], 1)


if __name__ == "__main__":
    unittest.main()
