"""End-to-end: fixture logs -> CONTRACT.md JSON."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from kanjo import cli
import sqlite3
from kanjo.sources import base, antigravity, codex
from kanjo.cache import RepoCache, SessionCache, _dump_session, _load_session
from kanjo.sources.base import Message, Session, open_sqlite_ro, extract_paths
from kanjo.config import Config
from kanjo.export import _apportion_by_weight, build_export, check_invariants

from tests.support import ALICE, FIXTURE_DIRS, FIXTURES, GITHUB, standard_fs, validate_contract

FOCUS = "github.com/alice/focusapp"
TCF = GITHUB + "/tcf-canada"
NO_TOKEI = os.path.join(FIXTURES, "no-tokei")  # does not exist: keeps the real ~/.tokei out of the tests


class FixtureExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fs = standard_fs()
        cls.doc = build_export(dirs=FIXTURE_DIRS, fs_root=cls.fs.root, home=ALICE, tokei_dir=NO_TOKEI)
        cls.by_id = {p["id"]: p for p in cls.doc["projects"]}

    @classmethod
    def tearDownClass(cls):
        cls.fs.cleanup()

    def test_contract(self):
        validate_contract(self, self.doc)
        self.assertEqual(check_invariants(self.doc), [])
        self.assertIn("ledger", self.doc)
        self.assertEqual(self.doc["ledger"]["orphaned"], 0)
        self.assertGreaterEqual(self.doc["ledger"]["sessions"], self.doc["totals"]["unique_sessions"])

    def test_json_round_trip(self):
        self.assertEqual(json.loads(json.dumps(self.doc)), self.doc)

    def test_projects(self):
        self.assertEqual(set(self.by_id), {FOCUS, TCF})
        focus = self.by_id[FOCUS]
        self.assertEqual((focus["name"], focus["remote"], focus["path_missing"]), ("FocusApp", FOCUS, False))
        self.assertEqual({a["agent"] for a in focus["by_agent"]}, {"claude", "antigravity", "codex"})
        self.assertEqual({a["label"] for a in focus["by_agent"]}, {"Claude Code", "Antigravity CLI", "Codex CLI"})
        tcf = self.by_id[TCF]
        self.assertEqual((tcf["name"], tcf["remote"]), ("tcf-canada", None))

    def test_session_counts_and_subagents(self):
        totals = self.doc["totals"]
        # claude: 2 sessions (+1 sub-agent), antigravity: 2, codex: 1 (+1 guardian sub-agent)
        self.assertEqual(totals["unique_sessions"], 5)
        focus = self.by_id[FOCUS]
        codex = [s for s in focus["sessions_detail"] if s["agent"] == "codex"]
        self.assertEqual(len(codex), 1)
        self.assertEqual(codex[0]["subagents"], 1)
        self.assertIn("codex-auto-review", codex[0]["models"])
        tcf = self.by_id[TCF]["sessions_detail"]
        self.assertEqual([(s["agent"], s["subagents"]) for s in tcf], [("claude", 1)])

    def test_deleted_registered_worktree_scores_for_main_repo(self):
        s = next(s for s in self.by_id[FOCUS]["sessions_detail"] if s["id"].startswith("856b6e70"))
        self.assertEqual(s["attribution"], "dominant")
        self.assertIn("/scratchpad/redesign", s["cwd"])

    def test_by_day_by_agent(self):
        for p in self.doc["projects"]:
            agents = {a["agent"] for a in p["by_agent"]}
            for d in p["by_day"]:
                self.assertIn("by_agent", d)
                self.assertTrue(d["by_agent"])
                self.assertLessEqual(set(d["by_agent"]), agents)
                self.assertLessEqual(abs(sum(d["by_agent"].values()) - d["cost"]), 0.01)
            # per-agent day costs add back up to the project-level by_agent costs
            for a in p["by_agent"]:
                total = sum(d["by_agent"].get(a["agent"], 0) for d in p["by_day"])
                self.assertAlmostEqual(total, a["cost"], delta=0.01)
        # FocusApp uses all three agents, so at least one agent key appears across its days
        focus_agents = set().union(*(d["by_agent"] for d in self.by_id[FOCUS]["by_day"]))
        self.assertEqual(focus_agents, {"claude", "antigravity", "codex"})
        for d in self.doc["buckets"]["unattributed"], self.doc["buckets"]["excluded"]:
            self.assertNotIn("by_day", d)

    def test_by_day_by_agent_mismatch_is_reported(self):
        doc = json.loads(json.dumps(self.doc))
        day = doc["projects"][0]["by_day"][0]
        key = next(iter(day["by_agent"]))
        day["by_agent"][key] += 0.5
        self.assertTrue(any("by_agent sum" in x for x in check_invariants(doc)))
        del day["by_agent"]
        self.assertTrue(any("by_agent sum" in x for x in check_invariants(doc)))

    def test_by_day_by_agent_tokens(self):
        for p in self.doc["projects"]:
            agents = {a["agent"] for a in p["by_agent"]}
            for d in p["by_day"]:
                self.assertIn("by_agent_tokens", d)
                self.assertEqual(set(d["by_agent_tokens"]), set(d["by_agent"]))
                self.assertLessEqual(set(d["by_agent_tokens"]), agents)
                self.assertTrue(all(isinstance(v, int) for v in d["by_agent_tokens"].values()))
                self.assertEqual(sum(d["by_agent_tokens"].values()), d["tokens"])
            # per-agent day tokens add back up to the project-level by_agent tokens (rounding: <= 1 per day)
            for a in p["by_agent"]:
                total = sum(d["by_agent_tokens"].get(a["agent"], 0) for d in p["by_day"])
                self.assertLessEqual(abs(total - a["tokens"]["total"]), len(p["by_day"]))
        focus_agents = set().union(*(d["by_agent_tokens"] for d in self.by_id[FOCUS]["by_day"]))
        self.assertEqual(focus_agents, {"claude", "antigravity", "codex"})

    def test_by_day_by_agent_tokens_mismatch_is_reported(self):
        doc = json.loads(json.dumps(self.doc))
        day = doc["projects"][0]["by_day"][0]
        key = next(iter(day["by_agent_tokens"]))
        day["by_agent_tokens"][key] += 1
        self.assertTrue(any("by_agent_tokens sum" in x for x in check_invariants(doc)))
        del day["by_agent_tokens"]
        self.assertTrue(any("by_agent_tokens sum" in x for x in check_invariants(doc)))

    def test_apportion_by_weight_is_exact(self):
        self.assertEqual(_apportion_by_weight(10, {"a": 1, "b": 1, "c": 1}), {"a": 4, "b": 3, "c": 3})
        self.assertEqual(_apportion_by_weight(7, {"claude": 2.5, "codex": 0.5}), {"claude": 6, "codex": 1})
        self.assertEqual(_apportion_by_weight(5, {"claude": 123.4}), {"claude": 5})
        self.assertEqual(_apportion_by_weight(0, {"a": 0.0, "b": 0.0}), {"a": 0, "b": 0})
        for total in (0, 1, 999, 123457):
            parts = _apportion_by_weight(total, {"a": 0.3333, "b": 1e-9, "c": 7.1, "d": 2.25})
            self.assertEqual(sum(parts.values()), total)

    def test_quota_windows_empty_without_tokei(self):
        self.assertEqual(self.doc["quota_windows"], {})
        keys = list(self.doc)
        self.assertEqual(keys.index("quota_windows"), keys.index("config") + 1)

    def test_titles_and_branches(self):
        for p in self.doc["projects"]:
            for s in p["sessions_detail"]:
                self.assertEqual(s["title"], "(redacted prompt)")
        focus_branches = {b["branch"] for b in self.by_id[FOCUS]["by_branch"]}
        self.assertTrue({"main", "claude/redesign-on-main"} <= focus_branches)

    def test_estimated_flag(self):
        models = {(m["model"], m["agent"]): m["estimated"] for m in self.by_id[FOCUS]["by_model"]}
        self.assertFalse(models[("claude-opus-5-5", "claude")])
        self.assertTrue(models[("codex-auto-review", "codex")])

    def test_buckets_present(self):
        b = self.doc["buckets"]
        self.assertEqual(b["parse_failed"], {"sessions": 0, "files": []})
        self.assertEqual(b["excluded"]["sessions"], 0)
        self.assertEqual(b["excluded"]["cost"], 0)

    def test_threshold_is_reported(self):
        doc = build_export(dirs=FIXTURE_DIRS, fs_root=self.fs.root, home=ALICE,
                           config=Config(dominant_threshold=1.0), tokei_dir=NO_TOKEI)
        self.assertEqual(doc["config"]["dominant_threshold"], 1.0)
        validate_contract(self, doc)


class ParseFailedTest(unittest.TestCase):
    def test_broken_files_are_listed_and_do_not_break_invariant(self):
        fs = standard_fs()
        tmp = tempfile.mkdtemp()
        try:
            claude_dir = os.path.join(tmp, "claude")
            shutil.copytree(os.path.join(FIXTURES, "claude"), claude_dir)
            broken = os.path.join(claude_dir, "-Users-alice-x", "broken.jsonl")
            os.makedirs(os.path.dirname(broken))
            with open(broken, "w") as h:
                h.write("this is not json\n{also not\n")
            bad_db = os.path.join(tmp, "antigravity", "bad.db")
            os.makedirs(os.path.dirname(bad_db))
            with open(bad_db, "wb") as h:
                h.write(b"not a sqlite file at all" * 100)
            dirs = dict(FIXTURE_DIRS, claude=[claude_dir],
                        antigravity=FIXTURE_DIRS["antigravity"] + [os.path.dirname(bad_db)])
            doc = build_export(dirs=dirs, fs_root=fs.root, home=ALICE, tokei_dir=NO_TOKEI)
            validate_contract(self, doc)
            self.assertEqual(doc["buckets"]["parse_failed"], {"sessions": 2, "files": sorted([broken, bad_db])})
            self.assertEqual(doc["totals"]["unique_sessions"], 5)
        finally:
            shutil.rmtree(tmp)
            fs.cleanup()


class SampleFileTest(unittest.TestCase):
    """tests/fixtures/export_sample.json is a sanitized real export used by the UI."""

    def test_sample_follows_contract(self):
        with open(os.path.join(FIXTURES, "export_sample.json"), encoding="utf-8") as h:
            doc = json.load(h)
        validate_contract(self, doc)
        self.assertEqual(check_invariants(doc), [])
        self.assertGreater(len(doc["projects"]), 1)
        self.assertTrue(doc["subscriptions"])
        text = json.dumps(doc)
        self.assertNotIn("/Users/dogecoin", text)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {
            "KANJO_CLAUDE_DIR": FIXTURE_DIRS["claude"][0],
            "KANJO_ANTIGRAVITY_DIR": FIXTURE_DIRS["antigravity"][0],
            "KANJO_CODEX_DIR": FIXTURE_DIRS["codex"][0],
            "KANJO_CACHE_DIR": self.cache,
            "KANJO_TOKEI_DIR": NO_TOKEI,
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.cache)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_export_stdout_is_pure_json_and_cache_is_stable(self):
        code, out, err = self.run_cli("export")
        self.assertEqual(code, 0)
        first = json.loads(out)
        self.assertEqual(check_invariants(first), [])
        code, out2, _ = self.run_cli("export", "--compact")  # second run is served from the cache
        second = json.loads(out2)
        first.pop("generated_at"), second.pop("generated_at")
        self.assertEqual(first, second)

    def test_export_to_file_with_threshold(self):
        path = os.path.join(self.cache, "out.json")
        code, out, err = self.run_cli("export", "-o", path, "--threshold", "0.5", "--no-cache")
        self.assertEqual((code, out), (0, ""))
        with open(path) as h:
            self.assertEqual(json.load(h)["config"]["dominant_threshold"], 0.5)

    def test_projects_and_doctor(self):
        code, out, _ = self.run_cli("projects", "--no-cache")
        self.assertEqual(code, 0)
        self.assertIn("Unattributed", out)
        self.assertIn("Not actual subscription spend", out)
        code, out, _ = self.run_cli("doctor", "--no-cache")
        self.assertEqual(code, 0)
        for label in ("Claude Code", "Antigravity CLI", "Codex CLI"):
            self.assertIn(label, out)

    def test_bad_config_and_threshold(self):
        self.assertEqual(self.run_cli("export", "--config", "/nonexistent/attribution.toml")[0], 2)
        self.assertEqual(self.run_cli("export", "--threshold", "1.5")[0], 2)


class CacheExportComparisonTest(unittest.TestCase):
    def setUp(self):
        self.fs = standard_fs()
        self.cache_dir = tempfile.mkdtemp(prefix="kanjo-test-cache-")

    def tearDown(self):
        self.fs.cleanup()
        shutil.rmtree(self.cache_dir, ignore_errors=True)

    def test_build_export_byte_identical_with_and_without_caches(self):
        # 1. build_export without any caches
        doc_no_cache = build_export(dirs=FIXTURE_DIRS, fs_root=self.fs.root, home=ALICE, tokei_dir=NO_TOKEI)

        # 2. build_export with cold cache (populates parse cache and repo cache)
        cache_cold = SessionCache(self.cache_dir)
        doc_cold = build_export(dirs=FIXTURE_DIRS, fs_root=self.fs.root, home=ALICE, tokei_dir=NO_TOKEI, cache=cache_cold)

        # Verify repo cache file was saved
        repo_cache_path = os.path.join(self.cache_dir, "repo-cache-v1.json")
        self.assertTrue(os.path.exists(repo_cache_path))
        with open(repo_cache_path, "r", encoding="utf-8") as h:
            cached_data = json.load(h)
        self.assertIn("paths", cached_data)
        self.assertGreater(len(cached_data["paths"]), 0)

        # 3. build_export with warm cache (fresh SessionCache loading from disk)
        cache_warm = SessionCache(self.cache_dir)
        doc_warm = build_export(dirs=FIXTURE_DIRS, fs_root=self.fs.root, home=ALICE, tokei_dir=NO_TOKEI, cache=cache_warm)

        # Exclude generated_at from comparison
        time_no_cache = doc_no_cache.pop("generated_at")
        time_cold = doc_cold.pop("generated_at")
        time_warm = doc_warm.pop("generated_at")
        self.assertTrue(time_no_cache and time_cold and time_warm)

        # Verify documents are 100% byte-identical
        json_no_cache = json.dumps(doc_no_cache, indent=2, sort_keys=True)
        json_cold = json.dumps(doc_cold, indent=2, sort_keys=True)
        json_warm = json.dumps(doc_warm, indent=2, sort_keys=True)

        self.assertEqual(json_no_cache, json_cold)
        self.assertEqual(json_no_cache, json_warm)

    def test_repo_cache_invalidation_when_repo_deleted(self):
        # Populate cache
        cache = SessionCache(self.cache_dir)
        doc_before = build_export(dirs=FIXTURE_DIRS, fs_root=self.fs.root, home=ALICE, tokei_dir=NO_TOKEI, cache=cache)
        self.assertTrue(any(p["id"] == FOCUS for p in doc_before["projects"]))

        # Invalidate repo by deleting its .git directory
        dotgit_real = self.fs.real(GITHUB + "/FocusApp/.git")
        shutil.rmtree(dotgit_real)

        # Warm cache run: validity check on FocusApp/.git must fail (file missing),
        # invalidating the cached repo resolution.
        cache_warm = SessionCache(self.cache_dir)
        hit, _ = cache_warm.repo_cache.get(GITHUB + "/FocusApp/Focus/App.swift", fs_root=self.fs.root)
        self.assertFalse(hit)

        # build_export runs and handles the invalidated repo gracefully
        doc_after = build_export(dirs=FIXTURE_DIRS, fs_root=self.fs.root, home=ALICE, tokei_dir=NO_TOKEI, cache=cache_warm)
        self.assertEqual(check_invariants(doc_after), [])

    def test_repo_cache_negative_ttl_invalidation(self):
        repo_cache = RepoCache(self.cache_dir)
        dummy_path = "/nonexistent/test/path"

        # Fresh negative entry (current timestamp)
        now = 1000.0
        repo_cache.put(dummy_path, None, now=now)
        hit, val = repo_cache.get(dummy_path, now=now + 300)  # 5 min later: within 10 min TTL
        self.assertTrue(hit)
        self.assertIsNone(val)

        # Expired negative entry (11 min later)
        hit_expired, _ = repo_cache.get(dummy_path, now=now + 660)  # 11 min later: past 10 min TTL
        self.assertFalse(hit_expired)


class ColdExportOptimizationsTest(unittest.TestCase):
    def setUp(self):
        self.fs = standard_fs()
        self.cache_dir = tempfile.mkdtemp(prefix="kanjo-test-cold-cache-")
        self.data_dir = tempfile.mkdtemp(prefix="kanjo-test-cold-data-")
        self.orig_data_dir = os.environ.get("KANJO_DATA_DIR")
        os.environ["KANJO_DATA_DIR"] = self.data_dir

    def tearDown(self):
        self.fs.cleanup()
        shutil.rmtree(self.cache_dir, ignore_errors=True)
        shutil.rmtree(self.data_dir, ignore_errors=True)
        if self.orig_data_dir is not None:
            os.environ["KANJO_DATA_DIR"] = self.orig_data_dir
        else:
            os.environ.pop("KANJO_DATA_DIR", None)

    def test_cold_export_byte_identical_with_all_nine_agents(self):
        nine_dirs = {
            "claude": [os.path.join(FIXTURES, "claude")],
            "antigravity": [os.path.join(FIXTURES, "antigravity")],
            "codex": [os.path.join(FIXTURES, "codex")],
            "copilot": [os.path.join(FIXTURES, "copilot"), os.path.join(FIXTURES, "copilot_db")],
            "grok": [os.path.join(FIXTURES, "grok")],
            "qwen": [os.path.join(FIXTURES, "qwen")],
            "commandcode": [os.path.join(FIXTURES, "commandcode")],
            "minimax": [os.path.join(FIXTURES, "minimax")],
            "opencode": [os.path.join(FIXTURES, "opencode")],
        }

        # 1. Without cache
        doc_no_cache = build_export(dirs=nine_dirs, fs_root=self.fs.root, home=ALICE, tokei_dir=NO_TOKEI)
        self.assertEqual(check_invariants(doc_no_cache), [])

        # 2. Cold cache
        cache_cold = SessionCache(self.cache_dir)
        doc_cold = build_export(dirs=nine_dirs, fs_root=self.fs.root, home=ALICE, tokei_dir=NO_TOKEI, cache=cache_cold)
        self.assertEqual(check_invariants(doc_cold), [])

        # 3. Warm cache
        cache_warm = SessionCache(self.cache_dir)
        doc_warm = build_export(dirs=nine_dirs, fs_root=self.fs.root, home=ALICE, tokei_dir=NO_TOKEI, cache=cache_warm)
        self.assertEqual(check_invariants(doc_warm), [])

        doc_no_cache.pop("generated_at", None)
        doc_cold.pop("generated_at", None)
        doc_warm.pop("generated_at", None)

        json_no_cache = json.dumps(doc_no_cache, indent=2, sort_keys=True)
        json_cold = json.dumps(doc_cold, indent=2, sort_keys=True)
        json_warm = json.dumps(doc_warm, indent=2, sort_keys=True)

        self.assertEqual(json_no_cache, json_cold)
        self.assertEqual(json_no_cache, json_warm)

    def test_sqlite_direct_open_avoids_copy_and_fallback_works(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            conn = sqlite3.connect(f.name)
            conn.execute("CREATE TABLE t (x INTEGER);")
            conn.execute("INSERT INTO t VALUES (42);")
            conn.commit()
            conn.close()

            # Direct read-only open succeeds without shutil.copy2
            with mock.patch("shutil.copy2") as mock_copy:
                with open_sqlite_ro(f.name) as c:
                    val = c.execute("SELECT x FROM t").fetchone()[0]
                    self.assertEqual(val, 42)
                mock_copy.assert_not_called()

            # When direct connect fails, falls back to copying
            orig_connect = sqlite3.connect
            def fail_direct(db, *args, **kwargs):
                if str(db).startswith("file:"):
                    raise sqlite3.OperationalError("mock direct failure")
                return orig_connect(db, *args, **kwargs)

            with mock.patch("sqlite3.connect", side_effect=fail_direct):
                with open_sqlite_ro(f.name) as c:
                    val = c.execute("SELECT x FROM t").fetchone()[0]
                    self.assertEqual(val, 42)

    def test_never_uses_immutable_when_wal_exists(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            conn = sqlite3.connect(f.name)
            conn.execute("CREATE TABLE t (x);")
            conn.commit()
            conn.close()

            wal = f.name + "-wal"
            with open(wal, "w") as wf:
                wf.write("dummy wal")

            opened_uris = []
            orig_connect = sqlite3.connect
            def spy_connect(db, *args, **kwargs):
                opened_uris.append(str(db))
                return orig_connect(db, *args, **kwargs)

            with mock.patch("sqlite3.connect", side_effect=spy_connect):
                try:
                    with open_sqlite_ro(f.name):
                        pass
                except Exception:
                    pass

            if os.path.exists(wal):
                os.remove(wal)

            for u in opened_uris:
                self.assertNotIn("immutable=1", u)

    def test_antigravity_protobuf_varint_and_filtering(self):
        # 1-byte vs multi-byte varints
        cases = [(0, b"\x00"), (1, b"\x01"), (127, b"\x7f"), (128, b"\x80\x01"), (300, b"\xac\x02")]
        for val, wire in cases:
            v, off = antigravity.decode_varint(wire, 0)
            self.assertEqual(v, val)
            self.assertEqual(off, len(wire))

        # parse_fields with wanted filtering matches unconstrained on wanted keys
        blob = b"\x08\x01\x12\x04test\x18\x2a\x22\x03abc"
        all_fields = antigravity.parse_fields(blob)
        filtered = antigravity.parse_fields(blob, wanted={1, 3})
        self.assertEqual([(f[0], f[2]) for f in filtered], [(1, 1), (3, 42)])
        self.assertEqual(len(filtered), 2)

        # parse_file equivalence on fixture
        ag_db = os.path.join(FIXTURES, "antigravity", "856b6e70-8027-4c17-91f0-c7575939aa34.db")
        sess = antigravity.parse_file(ag_db)
        self.assertEqual(sess.agent, "antigravity")
        self.assertGreater(len(sess.messages), 0)
        self.assertTrue(sess.origin_ts is not None)

    def test_codex_prefiltering_identity(self):
        for f in [
            os.path.join(FIXTURES, "codex", "2026", "07", "01", "rollout-2026-07-01T01-00-03-019f1c0c-6a90-7281-b963-a5dab473915f.jsonl"),
            os.path.join(FIXTURES, "codex", "2026", "06", "30", "rollout-2026-06-30T02-56-16-019f1750-7277-7f50-8187-804ff9c04f25.jsonl"),
        ]:
            sess = codex.parse_file(f)
            self.assertEqual(sess.agent, "codex")
            self.assertGreater(len(sess.messages), 0)

        # Verify assistant message mentioning 'user' does not trigger json.loads
        line_assistant_with_user = b'{"timestamp":"2026-07-01T01:00:03Z","type":"response_item","payload":{"role":"assistant","content":[{"text":"help the user with authentication"}]}}\n'
        with mock.patch("json.loads", wraps=json.loads) as mock_loads:
            # Create a minimal temp codex file
            with tempfile.NamedTemporaryFile(suffix=".jsonl") as tf:
                meta = b'{"timestamp":"2026-07-01T01:00:00Z","type":"session_meta","payload":{"id":"test-1"}}\n'
                tf.write(meta)
                tf.write(line_assistant_with_user)
                tf.flush()
                codex.parse_file(tf.name)
                # json.loads should be called for session_meta, but NOT for line_assistant_with_user
                loaded_lines = [call.args[0] for call in mock_loads.call_args_list if call.args]
                self.assertNotIn(line_assistant_with_user, loaded_lines)

    def test_custom_dump_and_load_session_equivalence(self):
        s = Session(
            id="test-sess",
            agent="codex",
            file="/path/to/log.jsonl",
            started=1000.0,
            ended=2000.0,
            origin_ts=1000.0,
            cwd="/Users/alice/repo",
            branch="main",
            messages=[
                Message(ts=1000.0, model="gpt-4o", input=10, output=20, cache_read=5, cache_write=2, cache_write_1h=0, thinking=1, cwd="/Users/alice/repo", branch="main", key="k1"),
                Message(ts=1050.0, model="gpt-4o", input=30, output=40, cache_read=10, cache_write=0, cache_write_1h=0, thinking=0, cwd="/Users/alice/repo", branch="main", key="k2"),
            ],
            tool_paths=[["/Users/alice/repo/a.py", "/Users/alice/repo/b.py"]],
            subagent_of=None,
            title="A sample task title",
            cwd_counts={"/Users/alice/repo": 2},
            remote_hints={"/Users/alice/repo": "https://github.com/alice/repo"},
        )
        dumped = _dump_session(s)
        self.assertEqual(dumped["id"], "test-sess")
        self.assertEqual(len(dumped["messages"]), 2)
        loaded = _load_session(dumped)
        self.assertEqual(loaded.id, s.id)
        self.assertEqual(loaded.agent, s.agent)
        self.assertEqual(len(loaded.messages), 2)
        self.assertEqual(loaded.messages[0].model, "gpt-4o")
        self.assertEqual(loaded.messages[1].input, 30)
        self.assertEqual(loaded.tool_paths, s.tool_paths)
        self.assertEqual(loaded.remote_hints, s.remote_hints)

    def test_extract_paths_equivalence(self):
        cases = [
            ("git diff /Users/alice/repo/file.py", ["/Users/alice/repo/file.py"]),
            ('python3 "/Users/alice/my project/main.py" --arg /tmp/test.txt', ["/Users/alice/my project/main.py", "/tmp/test.txt"]),
            ("echo hello world no paths here", []),
            ("cat ~/Documents/notes.txt /etc/hosts", [os.path.expanduser("~") + "/Documents/notes.txt", "/etc/hosts"]),
            ("invalid /!notapath /#bad", []),
        ]
        for text, expected in cases:
            self.assertEqual(extract_paths(text), expected)


if __name__ == "__main__":
    unittest.main()
