"""End-to-end: fixture logs -> CONTRACT.md JSON."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from aicost import cli
from aicost.config import Config
from aicost.export import build_export, check_invariants

from tests.support import ALICE, FIXTURE_DIRS, FIXTURES, GITHUB, standard_fs, validate_contract

FOCUS = "github.com/alice/focusapp"
TCF = GITHUB + "/tcf-canada"


class FixtureExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fs = standard_fs()
        cls.doc = build_export(dirs=FIXTURE_DIRS, fs_root=cls.fs.root, home=ALICE)
        cls.by_id = {p["id"]: p for p in cls.doc["projects"]}

    @classmethod
    def tearDownClass(cls):
        cls.fs.cleanup()

    def test_contract(self):
        validate_contract(self, self.doc)
        self.assertEqual(check_invariants(self.doc), [])

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
                           config=Config(dominant_threshold=1.0))
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
            doc = build_export(dirs=dirs, fs_root=fs.root, home=ALICE)
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
        self.assertGreater(len(doc["projects"]), 1)
        text = json.dumps(doc)
        self.assertNotIn("/Users/dogecoin", text)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {
            "AICOST_CLAUDE_DIR": FIXTURE_DIRS["claude"][0],
            "AICOST_ANTIGRAVITY_DIR": FIXTURE_DIRS["antigravity"][0],
            "AICOST_CODEX_DIR": FIXTURE_DIRS["codex"][0],
            "AICOST_CACHE_DIR": self.cache,
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


if __name__ == "__main__":
    unittest.main()
