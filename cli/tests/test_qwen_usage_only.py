"""Qwen sessions that exist only in usage/token-usage-*.jsonl: every one is billed
once, and ledgers / parse caches written by the previous release stay consistent."""

import json
import os
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from kanjo.cache import SessionCache, _dump_session
from kanjo.export import build_export, dedupe, scan
from kanjo.ledger import Ledger
from kanjo.sources import qwen
from kanjo.sources.base import ParseError

HERE = os.path.dirname(os.path.abspath(__file__))
CHAT = "projects/-Users-alice-proj/chats"


# The last release before usage-only Qwen sessions were billed per session. Pinned to a tag:
# origin/main already contains the change, so comparing against it tests the code against itself.
OLD_REF = "v0.6.11"


def old_qwen():
    """OLD_REF's qwen.py as a module, like test_ledger_scaling's old_ledger()."""
    try:
        source = subprocess.check_output(["git", "show", f"{OLD_REF}:cli/kanjo/sources/qwen.py"],
                                         cwd=HERE, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        raise unittest.SkipTest(f"{OLD_REF} is not available")
    module = types.ModuleType("kanjo.sources.old_qwen")
    module.__package__ = "kanjo.sources"
    exec(compile(source, f"{OLD_REF}:cli/kanjo/sources/qwen.py", "exec"), module.__dict__)
    return module


def rec(rid, sid, ts, inp=100, out=10):
    row = {"schemaVersion": 1, "timestamp": ts, "sessionId": sid, "model": "qwen3-coder-plus",
           "inputTokens": inp, "outputTokens": out, "cachedTokens": 0, "thoughtsTokens": 0}
    if rid is not None:
        row["id"] = rid
    return row


class QwenUsageOnlyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-qwen-usage-only-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "qwen")
        self.data = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        env = mock.patch.dict(os.environ, {"KANJO_DATA_DIR": self.data, "KANJO_CACHE_DIR": self.cache_dir,
                                           "KANJO_QWEN_DIR": self.root})
        env.start()
        self.addCleanup(env.stop)
        qwen._USAGE_CACHE.clear()
        self.oct = os.path.join(self.root, "usage", "token-usage-2026-10.jsonl")
        self.nov = os.path.join(self.root, "usage", "token-usage-2026-11.jsonl")

    def mixed_layout(self):
        # Oct: chat A first, then usage-only U1 (spills into Nov), U2, runtime-only R.
        self.write("usage/token-usage-2026-10.jsonl", [
            rec("a1", "A", "2026-10-01T10:00:00Z"), rec("u1a", "U1", "2026-10-02T10:00:00Z"),
            rec("u2a", "U2", "2026-10-03T10:00:00Z"), rec("r1", "R", "2026-10-04T10:00:00Z"),
            rec("u1b", "U1", "2026-10-31T23:59:00Z")])
        self.write("usage/token-usage-2026-11.jsonl", [
            rec("u1c", "U1", "2026-11-01T00:01:00Z"), rec("u3a", "U3", "2026-11-02T10:00:00Z")])
        self.write(CHAT + "/A.jsonl", [{"type": "user", "timestamp": "2026-10-01T10:00:00Z",
                                        "cwd": "/Users/alice/proj", "message": {"parts": [{"text": "hi"}]}}])
        with open(os.path.join(self.root, CHAT, "R.runtime.json"), "w") as handle:
            json.dump({"work_dir": "/Users/alice/rproj"}, handle)

    def usage_first_layout(self, ids=True):
        # No chat transcript at all; the first record of Oct is usage-only U1.
        r = (lambda rid, *a: rec(rid, *a)) if ids else (lambda rid, *a: rec(None, *a))
        self.write("usage/token-usage-2026-10.jsonl", [
            r("u1a", "U1", "2026-10-02T10:00:00Z"), r("u2a", "U2", "2026-10-03T10:00:00Z"),
            r("u1b", "U1", "2026-10-31T23:59:00Z")])
        self.write("usage/token-usage-2026-11.jsonl", [
            r("u1c", "U1", "2026-11-01T00:01:00Z"), r("u3a", "U3", "2026-11-02T10:00:00Z")])

    def write(self, rel, rows, mode="w"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as handle:
            for row in rows:
                handle.write((row if isinstance(row, str) else json.dumps(row)) + "\n")
        return path

    def all_records(self):
        out = []
        for name in sorted(os.listdir(os.path.join(self.root, "usage"))):
            with open(os.path.join(self.root, "usage", name)) as handle:
                out.extend(json.loads(line) for line in handle if line.strip())
        return out

    def all_keys(self):
        return sorted("qwen:%s:%s" % (r["sessionId"], r["id"]) for r in self.all_records())

    def run_scan(self, module=None, cache=True):
        qwen._USAGE_CACHE.clear()
        c = SessionCache(self.cache_dir) if cache else None
        if module is None:
            res = scan({"qwen": [self.root]}, cache=c, ledger=Ledger(self.data))
        else:
            module._USAGE_CACHE.clear()
            with mock.patch.object(qwen, "discover", module.discover), \
                    mock.patch.object(qwen, "parse_file", module.parse_file):
                res = scan({"qwen": [self.root]}, cache=c, ledger=Ledger(self.data))
        doc = build_export(dirs={"qwen": [self.root]}, scan_result=res, cache=c)
        sessions = dedupe(list(res.sessions))
        billed = sorted(m.key for s in sessions for m in s.messages)
        self.last_cache, self.last_sessions = c, sessions
        return doc, billed

    def rows(self):
        out = {}
        for key, entry in Ledger(self.data).entries.items():
            if isinstance(entry, dict) and isinstance(entry.get("session"), dict):
                out[key] = sorted({m[10] for m in entry["session"]["messages"]})
        return out

    def assert_one_row_per_sid(self):
        owners = {}
        for key, keys in self.rows().items():
            agent, sid, parent = key.split("\0")
            self.assertEqual((agent, parent), ("qwen", ""))
            self.assertNotIn("::", sid)
            for k in keys:
                self.assertTrue(k.startswith("qwen:%s:" % sid), (key, k))
                self.assertNotIn(k, owners)  # no record in two rows
                owners[k] = key
        return owners

    # --- the bug -------------------------------------------------------------

    def test_two_and_three_usage_only_sessions_in_one_file(self):
        for sids in (["S1", "S2"], ["S1", "S2", "S3"]):
            with self.subTest(sessions=len(sids)):
                shutil.rmtree(self.root, True)
                shutil.rmtree(self.data, True)
                shutil.rmtree(self.cache_dir, True)
                rows = []
                for n in range(3):  # interleaved: S1, S2, S3, S1, S2, S3, ...
                    rows.extend(rec("%s-%d" % (s, n), s, "2026-10-0%dT10:00:00Z" % (n + 1), inp=100 * (i + 1))
                                for i, s in enumerate(sids))
                self.write("usage/token-usage-2026-10.jsonl", rows)
                doc, billed = self.run_scan()
                self.assertEqual(billed, self.all_keys())
                totals = {s.id: sum(m.input for m in s.messages) for s in self.last_sessions}
                self.assertEqual(totals, {s: 300 * (i + 1) for i, s in enumerate(sids)})
                self.assertEqual(doc["totals"]["tokens"]["input"], sum(r["inputTokens"] for r in rows))
                self.assert_one_row_per_sid()

    def test_mixed_chat_and_usage_only_sessions_are_all_billed_once(self):
        self.mixed_layout()
        doc, billed = self.run_scan()
        self.assertEqual(billed, self.all_keys())
        self.assertEqual(doc["totals"]["tokens"]["input"], 100 * len(self.all_keys()))
        self.assertEqual(sorted(s.id for s in self.last_sessions), ["A", "R", "U1", "U2", "U3"])
        self.assertEqual(sorted(self.rows()), ["qwen\0%s\0" % s for s in ("A", "R", "U1", "U2", "U3")])
        self.assert_one_row_per_sid()

    def test_every_usage_only_session_is_discovered(self):
        self.mixed_layout()
        found = [p for p, _ in qwen.discover([self.root])]
        # The entries the old discover returned are still there, in order.
        self.assertEqual([p for p in found if "::" not in p],
                         [os.path.join(self.root, CHAT, "A.jsonl"), self.oct,
                          os.path.join(self.root, CHAT, "R.runtime.json"), self.nov])
        # One "<newest usage file>::<sessionId>" per session without a chat transcript.
        self.assertEqual(sorted(p for p in found if "::" in p),
                         sorted([self.nov + "::U1", self.oct + "::U2", self.oct + "::R", self.nov + "::U3"]))
        u1 = qwen.parse_file(self.nov + "::U1")
        self.assertEqual((u1.id, [m.key for m in u1.messages]), ("U1", ["qwen:U1:u1a", "qwen:U1:u1b", "qwen:U1:u1c"]))
        # Runtime-only sessions are billed under their real id, with runtime.json's cwd.
        r = qwen.parse_file(self.oct + "::R")
        self.assertEqual((r.id, r.cwd, len(r.messages)), ("R", "/Users/alice/rproj", 1))

    def test_runtime_json_entry_is_unchanged(self):
        self.mixed_layout()
        runtime = os.path.join(self.root, CHAT, "R.runtime.json")
        self.assertIn((runtime, None), qwen.discover([self.root]))
        session = qwen.parse_file(runtime)
        self.assertEqual((session.id, session.messages), ("R.runtime", []))
        self.assertEqual(_dump_session(session), _dump_session(old_qwen().parse_file(runtime)))

    def test_warm_export_equals_cold(self):
        self.mixed_layout()
        cold, cold_billed = self.run_scan()
        warm, warm_billed = self.run_scan()
        self.assertEqual(warm["totals"], cold["totals"])
        self.assertEqual(warm_billed, cold_billed)
        self.assertFalse(self.last_cache.modified_keys)
        shutil.rmtree(self.cache_dir)
        shutil.rmtree(self.data)
        nocache, _ = self.run_scan(cache=False)
        self.assertEqual(nocache["totals"], cold["totals"])

    # --- upgrade from a ledger and cache written by OLD_REF -------------------

    def test_old_paths_parse_identically_and_stay_cache_hits(self):
        old = old_qwen()
        for layout in ("mixed", "ids", "no-ids"):
            with self.subTest(layout=layout):
                for d in (self.root, self.data, self.cache_dir):
                    shutil.rmtree(d, True)
                if layout == "mixed":
                    self.mixed_layout()
                else:
                    self.usage_first_layout(ids=layout == "ids")
                old._USAGE_CACHE.clear()
                old_found = old.discover([self.root])
                qwen._USAGE_CACHE.clear()
                new_found = qwen.discover([self.root])
                self.assertEqual([e for e in new_found if "::" not in e[0]], old_found)
                for path, parent in old_found:
                    self.assertEqual(_dump_session(qwen.parse_file(path, parent)),
                                     _dump_session(old.parse_file(path, parent)), path)
                self.run_scan(old)
                self.run_scan()
                # Old cache entries are still valid: no CACHE_VERSION bump needed.
                self.assertFalse({p for p, _ in old_found} & self.last_cache.modified_keys)
                self.assertTrue(all("::" in p for p in self.last_cache.modified_keys))

    def test_ledger_written_by_origin_main_upgrades_without_double_counting(self):
        old = old_qwen()
        for layout in ("mixed", "ids"):
            with self.subTest(layout=layout):
                for d in (self.root, self.data, self.cache_dir):
                    shutil.rmtree(d, True)
                self.mixed_layout() if layout == "mixed" else self.usage_first_layout()
                _, old_billed = self.run_scan(old)
                old_rows = self.rows()
                doc, billed = self.run_scan()
                new_rows = self.rows()
                for key, keys in old_rows.items():
                    self.assertEqual(new_rows[key], keys)  # no session lost, same records
                owners = self.assert_one_row_per_sid()
                self.assertTrue(set(old_billed) < set(billed))
                self.assertEqual(billed, self.all_keys())
                self.assertFalse([s.id for s in self.last_sessions if "::" in s.id])
                # Warm (old cache + new entries) == cold.
                warm = doc["totals"]
                saved_data = self.data + "-saved"
                shutil.copytree(self.data, saved_data)
                shutil.rmtree(self.cache_dir)
                shutil.rmtree(self.data)
                cold, _ = self.run_scan()
                self.assertEqual(warm, cold["totals"])
                # Logs deleted afterwards: the ledger still bills every record exactly once.
                shutil.rmtree(self.data)
                os.rename(saved_data, self.data)
                shutil.rmtree(self.root)
                os.makedirs(self.root)
                _, orphaned = self.run_scan()
                self.assertEqual(orphaned, sorted(owners))

    def test_growth_and_month_rollover_warm_equals_cold(self):
        self.mixed_layout()
        self.run_scan()
        self.write("usage/token-usage-2026-11.jsonl", [rec("u3b", "U3", "2026-11-03T10:00:00Z")], mode="a")
        self.write("usage/token-usage-2026-12.jsonl", [rec("u3c", "U3", "2026-12-01T10:00:00Z")])
        warm, billed = self.run_scan()
        self.assertEqual(billed, self.all_keys())
        u3 = Ledger(self.data).entries["qwen\0U3\0"]
        self.assertEqual([os.path.basename(p) for p in u3["source_paths"]],
                         ["token-usage-2026-11.jsonl::U3", "token-usage-2026-12.jsonl::U3"])
        shutil.rmtree(self.cache_dir)
        cold, _ = self.run_scan(cache=False)
        self.assertEqual(warm["totals"], cold["totals"])

    def test_oldest_usage_file_deleted_loses_no_record_on_disk(self):
        self.usage_first_layout()
        self.run_scan()
        os.remove(self.oct)
        _, billed = self.run_scan()
        for key in self.all_keys():
            self.assertIn(key, billed)

    # --- parse_file details ---------------------------------------------------

    def test_record_index_matches_full_scan_without_ids(self):
        self.write("usage/token-usage-2026-10.jsonl", [
            "not json", rec(None, "U1", "2026-10-01T10:00:00Z"), "[]", {"sessionId": 7},
            {"sessionId": ""}, rec(None, "U2", "2026-10-02T10:00:00Z"), "",
            rec(None, "U1", "2026-10-03T10:00:00Z"), {"sessionId": None}])
        self.write("usage/token-usage-2026-11.jsonl", [
            rec(None, "U2", "2026-11-01T10:00:00Z"), "{broken", rec(None, "U1", "2026-11-02T10:00:00Z")])
        records = [r for r in self.all_records_lenient() if isinstance(r, dict)]
        for path, _ in qwen.discover([self.root]):
            if "::" not in path:
                continue
            sid = path.split("::", 1)[1]
            expected = ["qwen:%s:req_%d" % (sid, n)
                        for n, r in enumerate(r for r in records if r.get("sessionId") == sid)]
            self.assertEqual([m.key for m in qwen.parse_file(path).messages], expected, path)

    def all_records_lenient(self):
        out = []
        for name in sorted(os.listdir(os.path.join(self.root, "usage"))):
            with open(os.path.join(self.root, "usage", name)) as handle:
                for line in handle:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        return out

    def test_odd_session_ids(self):
        sids = ["first", "token-usage-x", "a::b", "a/b"]
        self.write("usage/token-usage-2026-10.jsonl",
                   [rec("r%d" % i, sid, "2026-10-0%dT10:00:00Z" % (i + 1)) for i, sid in enumerate(sids)])
        found = [p for p, _ in qwen.discover([self.root])]
        self.assertEqual(sorted(p for p in found if "::" in p), sorted(self.oct + "::" + s for s in sids))
        for sid in sids:
            session = qwen.parse_file(self.oct + "::" + sid)
            self.assertEqual((session.id, [m.key for m in session.messages]),
                             (sid, ["qwen:%s:r%d" % (sid, sids.index(sid))]))
        _, billed = self.run_scan()
        self.assertEqual(billed, self.all_keys())

    def test_vanished_usage_session_is_an_error_not_an_empty_row(self):
        self.mixed_layout()
        with self.assertRaises(ParseError):
            qwen.parse_file(self.nov + "::GONE")

    def test_root_with_double_colon_keeps_old_behaviour(self):
        self.mixed_layout()
        odd = os.path.join(self.tmp, "a::b")
        shutil.copytree(self.root, odd)
        self.assertFalse([p for p, _ in qwen.discover([odd]) if p.startswith(odd) and p.count("::") > 1])
        self.assertEqual(qwen.parse_file(os.path.join(odd, CHAT, "A.jsonl")).id, "A")


if __name__ == "__main__":
    unittest.main()
