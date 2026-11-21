"""Merged git worktrees: discovery in scratch folders, merge status, cleaning.

Every repo and worktree is created under a temp directory with real git.
"""

import contextlib
import io
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from kanjo import cli, disk, disk_cache

from tests.test_disk import git, set_tree_mtime

DAY = 86400
HOUR = 3600


class MergedWorktreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="kanjo-wt-"))
        self.repo = os.path.join(self.tmp, "repo")
        self.scratch = os.path.join(self.tmp, "scratch")
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.data = os.path.join(self.tmp, "data")
        self.trash = os.path.join(self.tmp, "trash")
        for path in (self.scratch, self.data, self.trash):
            os.makedirs(path)
        self.projects = os.path.join(self.tmp, "claude", "projects")
        self.roots = {"claude_projects": [self.projects], "scratch": self.scratch}
        self.env = mock.patch.dict(os.environ, {
            "KANJO_DATA_DIR": self.data,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_TRASH_DIR": self.trash,
            "KANJO_CLAUDE_DIR": self.projects,
            "KANJO_CODEX_DIR": os.path.join(self.tmp, "codex", "sessions"),
            "KANJO_ANTIGRAVITY_DIR": os.path.join(self.tmp, "agy", "conversations"),
            "KANJO_SCRATCH_DIR": self.scratch,
            "KANJO_GROK_DIR": os.path.join(self.tmp, "grok"),
            "KANJO_CLAUDE_APP_CACHE": os.path.join(self.tmp, "ClaudeApp"),
            "KANJO_TOKEI_DIR": os.path.join(self.tmp, "no-tokei"),
            "KANJO_CLAUDE_CONFIG": os.path.join(self.tmp, "no-claude.json"),
        })
        self.env.start()
        disk._WORKTREE_MERGE_CACHE.clear()
        disk._WORKTREE_DIRTY_CACHE.clear()
        self.init_repo(self.repo)

    def tearDown(self):
        self.env.stop()
        disk._WORKTREE_MERGE_CACHE.clear()
        disk._WORKTREE_DIRTY_CACHE.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- helpers ------------------------------------------------------------------------
    def init_repo(self, path, branch="main"):
        os.makedirs(path)
        git(path, "init", "-q", "-b", branch)
        self.write(os.path.join(path, "README"), "v1\n")
        self.write(os.path.join(path, "old.txt"), "old\n")
        self.write(os.path.join(path, ".gitignore"), "build/\n")
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", "init")

    def write(self, path, text="x"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def worktree(self, rel, branch, repo=None):
        path = os.path.join(self.scratch, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        git(repo or self.repo, "worktree", "add", "-q", "-b", branch, path)
        return path

    def commit(self, path, files, message="change", deletes=()):
        for name, text in files.items():
            self.write(os.path.join(path, name), text)
        for name in deletes:
            git(path, "rm", "-q", name)
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", message)

    def idle(self, path, age=2 * DAY):
        set_tree_mtime(path, time.time() - age)

    def report(self, now=None, rescan=True):
        return disk.report(roots=self.roots, now=time.time() if now is None else now, rescan=rescan)

    def entries(self, doc):
        return {e["id"]: e for a in doc["agents"] for e in a["entries"]}

    def listed_worktrees(self):
        """``git worktree list`` paths, normalized (git prints forward slashes on Windows)."""
        out = subprocess.check_output(["git", "-C", self.repo, "worktree", "list", "--porcelain"], text=True)
        return {_key(line[len("worktree "):]) for line in out.splitlines() if line.startswith("worktree ")}

    def wt_id(self, rel):
        return "claude:worktree:" + rel

    def build_cases(self):
        """One worktree per case; returns ``{case: path}``, all idle for two days."""
        cases = {}
        cases["ff"] = self.worktree("p/s1/scratchpad/wt-ff", "ff")
        self.commit(cases["ff"], {"ff.txt": "ff\n"})
        git(self.repo, "merge", "-q", "--ff-only", "ff")

        cases["squash"] = self.worktree("p/s2/scratchpad/wt-squash", "squash")
        self.commit(cases["squash"], {"sq.txt": "one\n"}, "first")
        self.commit(cases["squash"], {"sq.txt": "two\n", "README": "v2\n"}, "second", deletes=["old.txt"])
        # The same end state lands on main as one commit, then main moves on.
        self.commit(self.repo, {"sq.txt": "two\n", "README": "v2\n"}, "squash", deletes=["old.txt"])
        self.commit(self.repo, {"later.txt": "later\n"}, "later")

        cases["unmerged"] = self.worktree("p/s3/scratchpad/wt-unmerged", "unmerged")
        self.commit(cases["unmerged"], {"un.txt": "un\n"})

        cases["dirty"] = self.worktree("p/s4/scratchpad/wt-dirty", "dirty")
        self.write(os.path.join(cases["dirty"], "README"), "edited\n")

        cases["untracked"] = self.worktree("p/s5/scratchpad/wt-untracked", "untracked")
        self.write(os.path.join(cases["untracked"], "notes.txt"), "new\n")

        cases["nocommit"] = self.worktree("p/s6/scratchpad/wt-nocommit", "nocommit")
        self.write(os.path.join(cases["nocommit"], "build", "out.bin"), "ignored build output")
        for path in cases.values():
            self.idle(path)
        return cases

    # ---- merge status -------------------------------------------------------------------
    def test_merge_status_and_reclaimable_per_case(self):
        cases = self.build_cases()
        doc = self.report()
        found = self.entries(doc)
        expect = {
            "ff": (True, []),
            "squash": (False, []),
            "unmerged": (False, []),
            "dirty": (True, ["uncommitted_changes"]),
            "untracked": (True, ["uncommitted_changes"]),
            "nocommit": (True, ["uncommitted_changes"]),
        }
        for case, (merged, blocked) in expect.items():
            rel = os.path.relpath(cases[case], self.scratch).replace(os.sep, "/")
            entry = found[self.wt_id(rel)]
            self.assertEqual(entry["kind"], "worktrees", case)
            self.assertIs(entry["merged"], merged, case)
            self.assertEqual(entry["merged_into"], "main", case)
            self.assertEqual(entry["blocked"], blocked, case)
            self.assertEqual(entry["path"], cases[case], case)

    def test_squash_with_later_change_on_main_is_not_merged(self):
        path = self.worktree("p/s/scratchpad/wt", "feature")
        self.commit(path, {"f.txt": "branch\n"})
        self.commit(self.repo, {"f.txt": "branch\n"}, "squash")
        self.commit(self.repo, {"f.txt": "main moved on\n"}, "edit")
        self.idle(path)
        entry = self.entries(self.report())[self.wt_id("p/s/scratchpad/wt")]
        self.assertIs(entry["merged"], False)

    def test_branch_deleting_a_file_still_present_on_main_is_not_merged(self):
        path = self.worktree("p/s/scratchpad/wt", "feature")
        self.commit(path, {}, deletes=["old.txt"])
        self.idle(path)
        entry = self.entries(self.report())[self.wt_id("p/s/scratchpad/wt")]
        self.assertIs(entry["merged"], False)

    def test_origin_head_wins_and_names_merged_into(self):
        remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "clone", "-q", "--bare", self.repo, remote)
        clone = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", remote, clone)
        path = self.worktree("p/s/scratchpad/wt", "feature", repo=clone)
        self.commit(path, {"f.txt": "f\n"})
        # Merged on the remote only; the local main in the clone is behind.
        git(path, "push", "-q", remote, "feature:main")
        git(clone, "fetch", "-q", "origin")
        self.idle(path)
        entry = self.entries(self.report())[self.wt_id("p/s/scratchpad/wt")]
        self.assertEqual(entry["merged_into"], "origin/main")
        self.assertIs(entry["merged"], True)

    def test_no_default_branch_is_unknown(self):
        other = os.path.join(self.tmp, "other")
        self.init_repo(other, branch="trunk")
        path = self.worktree("p/s/scratchpad/wt", "feature", repo=other)
        self.idle(path)
        entry = self.entries(self.report())[self.wt_id("p/s/scratchpad/wt")]
        self.assertIsNone(entry["merged"])
        self.assertIsNone(entry["merged_into"])
        self.assertEqual(entry["blocked"], [])

    def test_merged_needs_one_idle_hour_unmerged_keeps_a_day(self):
        merged = self.worktree("p/s1/scratchpad/wt-merged", "merged")
        unmerged = self.worktree("p/s2/scratchpad/wt-unmerged", "unmerged")
        self.commit(unmerged, {"u.txt": "u\n"})
        self.idle(merged, 2 * HOUR)
        self.idle(unmerged, 2 * HOUR)
        found = self.entries(self.report())
        self.assertEqual(found[self.wt_id("p/s1/scratchpad/wt-merged")]["blocked"], [])
        self.assertEqual(found[self.wt_id("p/s2/scratchpad/wt-unmerged")]["blocked"], ["active"])
        self.idle(merged, HOUR / 2)
        found = self.entries(self.report())
        self.assertEqual(found[self.wt_id("p/s1/scratchpad/wt-merged")]["blocked"], ["active"])

    @unittest.skipIf(os.name == "nt" or not (shutil.which("lsof") or os.path.exists("/usr/sbin/lsof")),
                     "lsof is POSIX only")
    def test_process_working_inside_blocks_a_merged_worktree(self):
        path = self.worktree("p/s/scratchpad/wt", "feature")
        self.idle(path)
        # A grandchild: the scan ignores its own children (the git commands it runs).
        proc = subprocess.Popen(["/bin/sh", "-c", "sleep 30 & wait"], cwd=path, start_new_session=True)
        try:
            time.sleep(0.3)
            entry = self.entries(self.report())[self.wt_id("p/s/scratchpad/wt")]
        finally:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        self.assertIs(entry["merged"], True)
        self.assertEqual(entry["blocked"], ["active"])

    def test_merge_result_is_cached_by_head_and_default_sha(self):
        path = self.worktree("p/s/scratchpad/wt", "feature")
        self.commit(path, {"f.txt": "f\n"})
        git(self.repo, "merge", "-q", "--ff-only", "feature")
        self.idle(path)
        self.assertIs(self.entries(self.report())[self.wt_id("p/s/scratchpad/wt")]["merged"], True)
        with open(disk_cache.cache_path(), encoding="utf-8") as handle:
            saved = json.load(handle)["worktrees"]
        self.assertTrue(any(k.startswith("merge\0" + path + "\0") for k in saved))
        disk._WORKTREE_MERGE_CACHE.clear()
        with mock.patch.object(disk, "_is_merged", side_effect=AssertionError("cache should answer")):
            self.assertIs(self.entries(self.report())[self.wt_id("p/s/scratchpad/wt")]["merged"], True)
        # Moving main changes the key, so the answer is computed again.
        self.commit(self.repo, {"f.txt": "changed\n"}, "edit")
        self.idle(path)
        self.assertIs(self.entries(self.report())[self.wt_id("p/s/scratchpad/wt")]["merged"], True)

    # ---- discovery ----------------------------------------------------------------------
    def test_discovery_in_scratch_tree(self):
        wt_a = self.worktree("proj/sess/scratchpad/wt-a", "a")
        wt_b = self.worktree("proj/sess2/scratchpad/sub/wt-b", "b")
        self.write(os.path.join(wt_a, "big.bin"), "a" * 20000)
        self.write(os.path.join(self.scratch, "proj", "sess", "scratchpad", "notes.md"), "notes")
        # A worktree-looking folder inside node_modules is never visited.
        hidden = os.path.join(self.scratch, "proj", "sess", "scratchpad", "node_modules", "pkg")
        self.write(os.path.join(hidden, ".git"), "gitdir: %s/.git/worktrees/pkg\n" % self.repo)
        # A worktree nested inside a found worktree is not reported twice.
        inner = os.path.join(wt_a, "inner")
        self.write(os.path.join(inner, ".git"), "gitdir: %s/.git/worktrees/inner\n" % self.repo)
        self.write(os.path.join(self.scratch, "loose.log"), "loose")
        self.idle(self.scratch)
        doc = self.report()
        found = self.entries(doc)
        ids = [e["id"] for a in doc["agents"] for e in a["entries"]]
        self.assertEqual(len(ids), len(set(ids)))
        worktrees = sorted(e for e in ids if found[e]["kind"] == "worktrees")
        self.assertEqual(worktrees, [self.wt_id("proj/sess/scratchpad/wt-a"),
                                     self.wt_id("proj/sess2/scratchpad/sub/wt-b")])
        self.assertEqual(found[self.wt_id("proj/sess/scratchpad/wt-a")]["path"], wt_a)
        self.assertEqual(found[self.wt_id("proj/sess2/scratchpad/sub/wt-b")]["path"], wt_b)
        sess = found["claude:scratch:proj/sess"]
        now = time.time()
        self.assertEqual(sess["bytes"], disk.measure(sess["path"], now, exclude=[wt_a])["bytes"])
        self.assertLess(sess["bytes"], disk.measure(sess["path"], now)["bytes"])
        self.assertEqual(found["claude:scratch:proj/sess2"]["files"], 0)
        whole = disk.measure(self.scratch, now)
        claude = [e for e in found.values() if e["path"].startswith(self.scratch)]
        self.assertEqual(sum(e["bytes"] for e in claude), whole["bytes"])
        self.assertEqual(sum(e["files"] for e in claude), whole["files"])
        self.assertEqual(found["claude:scratch"]["files"], 1)

    def test_repo_claude_worktrees_are_found(self):
        path = os.path.join(self.repo, ".claude", "worktrees", "feat")
        git(self.repo, "worktree", "add", "-q", "-b", "feat", path)
        self.idle(path)
        roots = dict(self.roots, repos=[self.repo])
        doc = disk.report(roots=roots, now=time.time(), rescan=True)
        entry = self.entries(doc)["claude:repo-worktree:repo/feat"]
        self.assertEqual(entry["path"], path)
        self.assertIs(entry["merged"], True)

    def test_codex_worktrees_carry_merge_fields(self):
        codex = os.path.join(self.tmp, "codex")
        sessions = os.path.join(codex, "sessions")
        os.makedirs(sessions)
        path = os.path.join(codex, "worktrees", "abc", "repo")
        os.makedirs(os.path.dirname(path))
        git(self.repo, "worktree", "add", "-q", "-b", "codex", path)
        self.idle(path)
        roots = dict(self.roots, codex_dirs=[sessions])
        entry = self.entries(disk.report(roots=roots, now=time.time(), rescan=True))["codex:worktree:abc/repo"]
        self.assertIs(entry["merged"], True)
        self.assertEqual(entry["merged_into"], "main")

    def test_idle_session_is_not_blocked_by_an_active_one(self):
        self.write(os.path.join(self.scratch, "p", "old", "scratchpad", "a.txt"), "a")
        self.idle(self.scratch)
        self.write(os.path.join(self.scratch, "p", "new", "scratchpad", "b.txt"), "b")
        found = self.entries(self.report())
        self.assertEqual(found["claude:scratch:p/old"]["blocked"], [])
        self.assertEqual(found["claude:scratch:p/new"]["blocked"], ["active"])

    def test_matching_independent_commit_is_not_proof_of_merge(self):
        path = self.worktree("p/s/scratchpad/wt", "feature")
        self.commit(path, {"same.txt": "same\n"}, "private commit")
        self.commit(self.repo, {"same.txt": "same\n"}, "independent commit")
        self.idle(path)
        result = disk.clean([], merged_worktrees=True, yes=True, roots=self.roots, trash_dir=self.trash)
        self.assertEqual(result["moved"], [])
        self.assertTrue(os.path.exists(path))

    def test_ignored_worktree_files_are_not_removed(self):
        path = self.worktree("p/s/scratchpad/wt", "feature")
        self.write(os.path.join(path, "build", "valuable.txt"), "data")
        self.idle(path)
        result = disk.clean([], merged_worktrees=True, yes=True, roots=self.roots, trash_dir=self.trash)
        self.assertEqual(result["moved"], [])
        self.assertTrue(os.path.exists(os.path.join(path, "build", "valuable.txt")))

    # ---- clean --------------------------------------------------------------------------
    def test_clean_merged_worktrees_dry_run_then_yes(self):
        cases = self.build_cases()
        doc = self.report()
        found = self.entries(doc)
        ids = {case: self.wt_id(os.path.relpath(p, self.scratch).replace(os.sep, "/"))
               for case, p in cases.items()}
        plan = disk.clean([], merged_worktrees=True, dry_run=True, yes=True, roots=self.roots,
                          trash_dir=self.trash)
        self.assertEqual(sorted(plan["moved"]), [cases["ff"]])
        self.assertEqual(plan["freed_bytes"], found[ids["ff"]]["bytes"])
        skipped = {s["id"]: s["reason"] for s in plan["skipped"]}
        self.assertEqual(skipped, {
            ids["unmerged"]: "not_merged",
            ids["squash"]: "not_merged",
            ids["nocommit"]: "uncommitted_changes",
            ids["dirty"]: "uncommitted_changes",
            ids["untracked"]: "uncommitted_changes",
        })
        for path in cases.values():
            self.assertTrue(os.path.isdir(path))

        done = disk.clean([], merged_worktrees=True, yes=True, roots=self.roots, trash_dir=self.trash)
        self.assertEqual(sorted(done["moved"]), sorted(plan["moved"]))
        listed = self.listed_worktrees()
        for case in ("ff",):
            self.assertFalse(os.path.exists(cases[case]), case)
            self.assertNotIn(_key(cases[case]), listed)
        for case in ("unmerged", "dirty", "untracked", "squash", "nocommit"):
            self.assertIn(_key(cases[case]), listed)
        for case in ("unmerged", "dirty", "untracked", "squash", "nocommit"):
            self.assertTrue(os.path.isdir(cases[case]), case)
        branches = subprocess.check_output(["git", "-C", self.repo, "branch", "--format=%(refname:short)"],
                                           text=True).split()
        for branch in cases:
            self.assertIn(branch, branches)
        self.assertEqual(os.listdir(self.trash), [])
        self.assertFalse(os.path.exists(disk_cache.cache_path()))

    def test_remove_refused_by_git_is_reported(self):
        path = self.worktree("p/s/scratchpad/wt", "feature")
        self.idle(path)
        git(self.repo, "worktree", "lock", path)
        done = disk.clean([], merged_worktrees=True, yes=True, roots=self.roots, trash_dir=self.trash)
        self.assertEqual(done["moved"], [])
        self.assertEqual(len(done["skipped"]), 1)
        self.assertEqual(done["skipped"][0]["reason"], "worktree_remove_failed")
        self.assertIn("detail", done["skipped"][0])
        self.assertTrue(os.path.isdir(path))

    def test_cli_merged_worktrees_flag(self):
        path = self.worktree("p/s/scratchpad/wt", "feature")
        self.idle(path)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["disk", "clean", "--merged-worktrees", "--dry-run"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue())["moved"], [path])
        self.assertTrue(os.path.isdir(path))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["disk", "clean"]), 2)

    def test_scratch_clean_leaves_worktrees_inside_in_place(self):
        path = self.worktree("p/s/scratchpad/wt", "feature")
        notes = self.write(os.path.join(self.scratch, "p", "s", "scratchpad", "notes.md"), "n")
        loose = self.write(os.path.join(self.scratch, "loose.log"), "l")
        self.idle(self.scratch)
        self.report()
        done = disk.clean(["claude:scratch"], yes=True, roots=self.roots, trash_dir=self.trash)
        self.assertEqual(sorted(done["moved"]), sorted([loose, notes]))
        self.assertFalse(os.path.exists(notes))
        self.assertFalse(os.path.exists(loose))
        self.assertTrue(os.path.isdir(path))
        self.assertIn(_key(path), self.listed_worktrees())


def _key(path):
    return os.path.normcase(os.path.normpath(path))


if __name__ == "__main__":
    unittest.main()
