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
from kanjo.cache import RepoCache, SessionCache
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


if __name__ == "__main__":
    unittest.main()
