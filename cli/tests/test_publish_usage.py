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

    def test_first_publish_success(self):
        code, out, err = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code, 0, err)
        res = json.loads(out.strip())
        self.assertEqual(res["status"], "pushed")
        self.assertEqual(res["file"], "src/data/token-usage.json")
        self.assertTrue(res["commit"])
        self.assertTrue(res["period"])

        target_file = os.path.join(self.work_repo, "src/data/token-usage.json")
        self.assertTrue(os.path.isfile(target_file))

        # Check commit message format
        log_res = subprocess.run(["git", "-C", self.work_repo, "log", "-1", "--pretty=%s"],
                                 capture_output=True, text=True, check=True)
        expected_msg = "chore: update AI token usage (%s)" % res["period"]
        self.assertEqual(log_res.stdout.strip(), expected_msg)

    def test_second_publish_unchanged(self):
        # First publish
        code1, _, _ = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code1, 0)

        # Get commit sha
        sha1 = subprocess.run(["git", "-C", self.work_repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()

        # Second publish without changing logs
        code2, out2, _ = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code2, 0)
        res2 = json.loads(out2.strip())
        self.assertEqual(res2["status"], "unchanged")

        # Confirm no new commit
        sha2 = subprocess.run(["git", "-C", self.work_repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(sha1, sha2)

    def test_commit_does_not_commit_unrelated_staged_or_unstaged_changes(self):
        # Create an unrelated file and stage it
        staged_file = os.path.join(self.work_repo, "unrelated_staged.txt")
        with open(staged_file, "w", encoding="utf-8") as f:
            f.write("I am staged\n")
        subprocess.run(["git", "-C", self.work_repo, "add", "unrelated_staged.txt"],
                       check=True, capture_output=True)

        # Create an unstaged change
        unstaged_file = os.path.join(self.work_repo, "README.md")
        with open(unstaged_file, "a", encoding="utf-8") as f:
            f.write("An unstaged edit\n")

        # Run publish-usage
        code, out, err = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code, 0, err)

        # Verify git status
        status_res = subprocess.run(["git", "-C", self.work_repo, "status", "--porcelain"],
                                    capture_output=True, text=True, check=True)
        lines = [line.strip() for line in status_res.stdout.splitlines() if line.strip()]

        # unrelated_staged.txt should still be staged (starts with 'A ')
        self.assertTrue(any(line == "A  unrelated_staged.txt" for line in lines),
                        "Expected unrelated_staged.txt to remain staged, got: %s" % lines)
        # README.md should still be unstaged modified (starts with ' M ')
        self.assertTrue(any(line == "M README.md" or line == " M README.md" for line in lines),
                        "Expected README.md to remain unstaged, got: %s" % lines)

        # Confirm token-usage.json is NOT in status (it was committed)
        self.assertFalse(any("token-usage.json" in line for line in lines))

    def test_wrong_branch_and_non_git_repo(self):
        # Non-git repo
        non_git = os.path.join(self.tmp, "not_git")
        os.makedirs(non_git, exist_ok=True)
        code1, out1, _ = self._run_cli("publish-usage", "--repo", non_git)
        self.assertNotEqual(code1, 0)
        res1 = json.loads(out1.strip())
        self.assertEqual(res1["status"], "error")
        self.assertIn("not a git repository", res1["message"])

        # Wrong branch
        code2, out2, _ = self._run_cli("publish-usage", "--repo", self.work_repo, "--branch", "develop")
        self.assertNotEqual(code2, 0)
        res2 = json.loads(out2.strip())
        self.assertEqual(res2["status"], "error")
        self.assertIn("does not match required branch", res2["message"])

    def test_dry_run_does_not_commit_or_push(self):
        target_file = os.path.join(self.work_repo, "src/data/token-usage.json")
        self.assertFalse(os.path.exists(target_file))

        sha_before = subprocess.run(["git", "-C", self.work_repo, "rev-parse", "HEAD"],
                                    capture_output=True, text=True, check=True).stdout.strip()

        code, out, _ = self._run_cli("publish-usage", "--repo", self.work_repo, "--dry-run")
        self.assertEqual(code, 0)

        # Output should be the JSON document
        doc = json.loads(out)
        self.assertEqual(doc["kind"], "kanjo-public-summary")

        # File must not exist on disk
        self.assertFalse(os.path.exists(target_file))

        # HEAD commit must be unchanged
        sha_after = subprocess.run(["git", "-C", self.work_repo, "rev-parse", "HEAD"],
                                   capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(sha_before, sha_after)

    def test_push_retry_on_remote_update(self):
        # Another clone pushes a commit to origin
        second_clone = os.path.join(self.tmp, "clone2")
        subprocess.run(["git", "clone", self.bare_remote, second_clone],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", second_clone, "config", "user.name", "Clone 2"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", second_clone, "config", "user.email", "clone2@example.com"],
                       check=True, capture_output=True)

        with open(os.path.join(second_clone, "remote_edit.txt"), "w", encoding="utf-8") as f:
            f.write("edit on origin\n")
        subprocess.run(["git", "-C", second_clone, "add", "remote_edit.txt"], check=True, capture_output=True)
        subprocess.run(["git", "-C", second_clone, "commit", "-m", "remote update"], check=True, capture_output=True)
        subprocess.run(["git", "-C", second_clone, "push", "origin", "main"], check=True, capture_output=True)

        # Now running publish-usage on work_repo should pull origin and push successfully
        code, out, err = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code, 0, err)
        res = json.loads(out.strip())
        self.assertEqual(res["status"], "pushed")

        # Check that remote_edit.txt was pulled in
        self.assertTrue(os.path.isfile(os.path.join(self.work_repo, "remote_edit.txt")))

    def _head(self, repo):
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()

    def _set_push_rejected(self, rejected):
        hook = os.path.join(self.bare_remote, "hooks", "pre-receive")
        if rejected:
            with open(hook, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\necho rejected >&2\nexit 1\n")
            os.chmod(hook, 0o755)
        elif os.path.exists(hook):
            os.remove(hook)

    def test_commit_left_by_failed_push_is_pushed_on_next_run(self):
        self._set_push_rejected(True)
        code1, out1, _ = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertNotEqual(code1, 0)
        self.assertEqual(json.loads(out1.strip())["status"], "error")
        local_sha = self._head(self.work_repo)
        self.assertNotEqual(local_sha, self._head(self.bare_remote))

        # Same data, push works again: the pending commit must reach the remote.
        self._set_push_rejected(False)
        code2, out2, err2 = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code2, 0, err2)
        res2 = json.loads(out2.strip())
        self.assertEqual(res2["status"], "pushed")
        self.assertTrue(res2["pending"])
        self.assertEqual(res2["commit"], local_sha)
        self.assertEqual(self._head(self.bare_remote), local_sha)

        # Nothing left to push: a plain no-op.
        code3, out3, _ = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code3, 0)
        self.assertEqual(json.loads(out3.strip())["status"], "unchanged")

    def test_push_retry_rebases_with_unrelated_uncommitted_changes(self):
        # Another clone pushes right before our first push, so that push is rejected and
        # the retry has to rebase while README.md has an unrelated unstaged edit.
        second_clone = os.path.join(self.tmp, "clone2")
        subprocess.run(["git", "clone", self.bare_remote, second_clone], check=True, capture_output=True)
        subprocess.run(["git", "-C", second_clone, "config", "user.name", "Clone 2"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", second_clone, "config", "user.email", "clone2@example.com"],
                       check=True, capture_output=True)

        with open(os.path.join(self.work_repo, "README.md"), "a", encoding="utf-8") as f:
            f.write("local unstaged edit\n")

        from kanjo import publish
        real_git = publish._git
        state = {"moved": False}

        def git_moving_remote_before_first_push(repo, *args):
            if args[:1] == ("push",) and not state["moved"]:
                state["moved"] = True
                with open(os.path.join(second_clone, "remote_edit.txt"), "w", encoding="utf-8") as f:
                    f.write("edit on origin\n")
                subprocess.run(["git", "-C", second_clone, "add", "remote_edit.txt"],
                               check=True, capture_output=True)
                subprocess.run(["git", "-C", second_clone, "commit", "-m", "remote update"],
                               check=True, capture_output=True)
                subprocess.run(["git", "-C", second_clone, "push", "origin", "main"],
                               check=True, capture_output=True)
            return real_git(repo, *args)

        with mock.patch.object(publish, "_git", side_effect=git_moving_remote_before_first_push):
            code, out, err = self._run_cli("publish-usage", "--repo", self.work_repo)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(json.loads(out.strip())["status"], "pushed")
        self.assertEqual(self._head(self.work_repo), self._head(self.bare_remote))
        self.assertTrue(os.path.isfile(os.path.join(self.work_repo, "remote_edit.txt")))
        with open(os.path.join(self.work_repo, "README.md"), encoding="utf-8") as f:
            self.assertIn("local unstaged edit", f.read())


if __name__ == "__main__":
    unittest.main()
