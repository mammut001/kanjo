"""Tests for ``kanjo publish-usage`` command (spec Part A3)."""

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from kanjo import cli
from tests.support import FIXTURE_DIRS


class PublishUsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-publish-test-")
        self.bare_remote = os.path.join(self.tmp, "remote.git")
        self.work_repo = os.path.join(self.tmp, "work")
        self.data_dir = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

        # 1. git init --bare remote
        subprocess.run(["git", "init", "--bare", "-b", "main", self.bare_remote],
                       check=True, capture_output=True)

        # 2. clone to work_repo
        subprocess.run(["git", "clone", self.bare_remote, self.work_repo],
                       check=True, capture_output=True)

        # 3. configure git user identity and make initial commit on main
        subprocess.run(["git", "-C", self.work_repo, "config", "user.name", "Kanjo Tester"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", self.work_repo, "config", "user.email", "tester@example.com"],
                       check=True, capture_output=True)

        readme_path = os.path.join(self.work_repo, "README.md")
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write("# Resume Website\n")
        subprocess.run(["git", "-C", self.work_repo, "add", "README.md"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", self.work_repo, "commit", "-m", "initial commit"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", self.work_repo, "push", "origin", "main"],
                       check=True, capture_output=True)

        self.env = {
            "KANJO_DATA_DIR": self.data_dir,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_CLAUDE_DIR": FIXTURE_DIRS["claude"][0],
            "KANJO_ANTIGRAVITY_DIR": FIXTURE_DIRS["antigravity"][0],
            "KANJO_CODEX_DIR": FIXTURE_DIRS["codex"][0],
            "KANJO_GROK_DIR": self.tmp,
            "KANJO_QWEN_DIR": self.tmp,
            "KANJO_COMMANDCODE_DIR": self.tmp,
            "KANJO_MINIMAX_DIR": self.tmp,
            "KANJO_OPENCODE_DIR": self.tmp,
            "KANJO_COPILOT_DIR": self.tmp,
            "KANJO_PI_DIR": self.tmp,
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_cli(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, self.env), mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    # ------------------------------------------------------------ helpers
    def _git_out(self, repo, *args):
        return subprocess.run(["git", "-C", repo] + list(args),
                              capture_output=True, text=True, check=True).stdout.strip()

    def _head(self, repo):
        return self._git_out(repo, "rev-parse", "HEAD")

    def _remote_file(self, path="src/data/token-usage.json"):
        res = subprocess.run(["git", "-C", self.bare_remote, "show", "main:" + path],
                             capture_output=True, text=True)
        return res.stdout if res.returncode == 0 else None

    def _remote_has(self, path):
        return self._remote_file(path) is not None

    def _clone2(self):
        second_clone = os.path.join(self.tmp, "clone2")
        subprocess.run(["git", "clone", self.bare_remote, second_clone], check=True, capture_output=True)
        subprocess.run(["git", "-C", second_clone, "config", "user.name", "Clone 2"], check=True, capture_output=True)
        subprocess.run(["git", "-C", second_clone, "config", "user.email", "clone2@example.com"],
                       check=True, capture_output=True)
        return second_clone

    def _remote_commit(self, clone, name, content, message):
        full = os.path.join(clone, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        subprocess.run(["git", "-C", clone, "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", clone, "commit", "-m", message], check=True, capture_output=True)
        subprocess.run(["git", "-C", clone, "push", "origin", "main"], check=True, capture_output=True)

    def _set_push_rejected(self, rejected):
        hook = os.path.join(self.bare_remote, "hooks", "pre-receive")
        if rejected:
            with open(hook, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\necho rejected >&2\nexit 1\n")
            os.chmod(hook, 0o755)
        elif os.path.exists(hook):
            os.remove(hook)

    # ------------------------------------------------------------ tests
    def test_first_publish_success(self):
        head_before = self._head(self.work_repo)
        code, out, err = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code, 0, err)
        res = json.loads(out.strip())
        self.assertEqual(res["status"], "pushed")
        self.assertEqual(res["file"], "src/data/token-usage.json")
        self.assertTrue(res["period"])
        self.assertEqual(self._head(self.bare_remote), res["commit"])

        doc = json.loads(self._remote_file())
        self.assertEqual(doc["kind"], "kanjo-public-summary")
        self.assertEqual(self._git_out(self.bare_remote, "log", "-1", "--pretty=%s", "main"),
                         "chore: update AI token usage (%s)" % res["period"])
        # Only the data file changed, on top of the previous remote commit.
        self.assertEqual(self._git_out(self.bare_remote, "diff-tree", "--no-commit-id", "--name-only", "-r", "main"),
                         "src/data/token-usage.json")
        # The website checkout itself is not touched.
        self.assertEqual(self._head(self.work_repo), head_before)
        self.assertFalse(os.path.exists(os.path.join(self.work_repo, "src/data/token-usage.json")))
        self.assertEqual(self._git_out(self.work_repo, "status", "--porcelain"), "")

    def test_second_publish_unchanged(self):
        code1, _, _ = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code1, 0)
        sha1 = self._head(self.bare_remote)

        code2, out2, _ = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code2, 0)
        self.assertEqual(json.loads(out2.strip())["status"], "unchanged")
        self.assertEqual(self._head(self.bare_remote), sha1)

    def test_publishes_while_another_branch_with_uncommitted_work_is_checked_out(self):
        subprocess.run(["git", "-C", self.work_repo, "checkout", "-b", "feature-x"], check=True, capture_output=True)
        with open(os.path.join(self.work_repo, "staged.txt"), "w", encoding="utf-8") as f:
            f.write("staged\n")
        subprocess.run(["git", "-C", self.work_repo, "add", "staged.txt"], check=True, capture_output=True)
        with open(os.path.join(self.work_repo, "README.md"), "a", encoding="utf-8") as f:
            f.write("unstaged edit\n")
        head_before = self._head(self.work_repo)
        status_before = self._git_out(self.work_repo, "status", "--porcelain")

        code, out, err = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(json.loads(out.strip())["status"], "pushed")
        self.assertTrue(self._remote_has("src/data/token-usage.json"))
        self.assertFalse(self._remote_has("staged.txt"))
        self.assertNotIn("unstaged edit", self._remote_file("README.md"))

        self.assertEqual(self._git_out(self.work_repo, "branch", "--show-current"), "feature-x")
        self.assertEqual(self._head(self.work_repo), head_before)
        self.assertEqual(self._git_out(self.work_repo, "status", "--porcelain"), status_before)

    def test_missing_remote_branch_and_non_git_repo(self):
        non_git = os.path.join(self.tmp, "not_git")
        os.makedirs(non_git, exist_ok=True)
        code1, out1, _ = self._run_cli("publish-usage", "--repo", non_git)
        self.assertNotEqual(code1, 0)
        res1 = json.loads(out1.strip())
        self.assertEqual(res1["status"], "error")
        self.assertIn("not a git repository", res1["message"])

        code2, out2, _ = self._run_cli("publish-usage", "--repo", self.work_repo, "--branch", "develop")
        self.assertNotEqual(code2, 0)
        self.assertEqual(json.loads(out2.strip())["status"], "error")

    def test_dry_run_does_not_commit_or_push(self):
        sha_before = self._head(self.work_repo)
        remote_before = self._head(self.bare_remote)
        code, out, _ = self._run_cli("publish-usage", "--repo", self.work_repo, "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["kind"], "kanjo-public-summary")
        self.assertFalse(os.path.exists(os.path.join(self.work_repo, "src/data/token-usage.json")))
        self.assertEqual(self._head(self.work_repo), sha_before)
        self.assertEqual(self._head(self.bare_remote), remote_before)

    def test_publishes_on_top_of_remote_changes(self):
        self._remote_commit(self._clone2(), "remote_edit.txt", "edit on origin\n", "remote update")
        code, out, err = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out.strip())["status"], "pushed")
        self.assertTrue(self._remote_has("remote_edit.txt"))
        self.assertTrue(self._remote_has("src/data/token-usage.json"))

    def test_failed_push_leaves_nothing_behind_and_next_run_publishes(self):
        head_before = self._head(self.work_repo)
        remote_before = self._head(self.bare_remote)
        self._set_push_rejected(True)
        code1, out1, _ = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertNotEqual(code1, 0)
        self.assertEqual(json.loads(out1.strip())["status"], "error")
        self.assertEqual(self._head(self.bare_remote), remote_before)
        self.assertEqual(self._head(self.work_repo), head_before)
        self.assertEqual(self._git_out(self.work_repo, "status", "--porcelain"), "")

        self._set_push_rejected(False)
        code2, out2, err2 = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code2, 0, err2)
        self.assertEqual(json.loads(out2.strip())["status"], "pushed")
        self.assertTrue(self._remote_has("src/data/token-usage.json"))

    def test_other_machine_numbers_are_replaced_not_conflicted(self):
        self._remote_commit(self._clone2(), "src/data/token-usage.json", "{}\n", "other machine")
        code, out, err = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(json.loads(out.strip())["status"], "pushed")
        self.assertEqual(json.loads(self._remote_file())["kind"], "kanjo-public-summary")
        self.assertEqual(self._git_out(self.work_repo, "branch", "--show-current"), "main")

    def test_users_own_unpushed_commit_is_never_pushed(self):
        with open(os.path.join(self.work_repo, "draft.md"), "w", encoding="utf-8") as f:
            f.write("draft\n")
        subprocess.run(["git", "-C", self.work_repo, "add", "draft.md"], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.work_repo, "commit", "-m", "WIP: draft post (not ready)"],
                       check=True, capture_output=True)
        local_sha = self._head(self.work_repo)

        code, out, err = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(json.loads(out.strip())["status"], "pushed")
        self.assertFalse(self._remote_has("draft.md"))
        self.assertEqual(self._head(self.work_repo), local_sha)

    def test_push_retry_rebuilds_on_the_new_remote_tip(self):
        # Another clone pushes right before our first push, so that push is rejected and
        # the retry has to rebuild the commit on the new remote tip.
        second_clone = self._clone2()
        from kanjo import publish
        real_git = publish._git
        state = {"moved": False}

        def git_moving_remote_before_first_push(repo, *args, **kwargs):
            if args[:1] == ("push",) and not state["moved"]:
                state["moved"] = True
                self._remote_commit(second_clone, "remote_edit.txt", "edit on origin\n", "remote update")
            return real_git(repo, *args, **kwargs)

        with mock.patch.object(publish, "_git", side_effect=git_moving_remote_before_first_push):
            code, out, err = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code, 0, out + err)
        self.assertTrue(state["moved"])
        self.assertEqual(json.loads(out.strip())["status"], "pushed")
        self.assertTrue(self._remote_has("remote_edit.txt"))
        self.assertTrue(self._remote_has("src/data/token-usage.json"))


if __name__ == "__main__":
    unittest.main()
