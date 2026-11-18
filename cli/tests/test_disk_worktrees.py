import unittest
import os
import shutil
import tempfile
import subprocess
from kanjo import disk

class TestDiskWorktrees(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        os.mkdir(self.repo)
        self._git(["init"])
        self._git(["checkout", "-b", "main"])
        with open(os.path.join(self.repo, "README.md"), "w") as f: f.write("hello")
        self._git(["add", "."])
        self._git(["commit", "-m", "initial"])

    def _git(self, args):
        subprocess.run(["git", "-C", self.repo] + args, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_merge_detection(self):
        wt = os.path.join(self.tmp, "wt")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", wt, "-b", "feature"], check=True)
        with open(os.path.join(wt, "file"), "w") as f: f.write("content")
        subprocess.run(["git", "-C", wt, "add", "."], check=True)
        subprocess.run(["git", "-C", wt, "commit", "-m", "feat"], check=True)
        
        # Test merged
        subprocess.run(["git", "-C", self.repo, "checkout", "main"], check=True)
        subprocess.run(["git", "-C", self.repo, "merge", "feature"], check=True)
        merged, _ = disk._is_merged(wt)
        self.assertTrue(merged)

    def test_squash_merged(self):
        wt = os.path.join(self.tmp, "wt_squash")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", wt, "-b", "feature_squash"], check=True)
        with open(os.path.join(wt, "file"), "w") as f: f.write("content")
        subprocess.run(["git", "-C", wt, "add", "."], check=True)
        subprocess.run(["git", "-C", wt, "commit", "-m", "feat"], check=True)
        
        # Squash
        subprocess.run(["git", "-C", self.repo, "checkout", "main"], check=True)
        subprocess.run(["git", "-C", self.repo, "merge", "--squash", "feature_squash"], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-m", "squash"], check=True)
        
        merged, _ = disk._is_merged(wt)
        self.assertTrue(merged)

    def test_unmerged(self):
        wt = os.path.join(self.tmp, "wt_un")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", wt, "-b", "feature_un"], check=True)
        with open(os.path.join(wt, "file"), "w") as f: f.write("content")
        subprocess.run(["git", "-C", wt, "add", "."], check=True)
        subprocess.run(["git", "-C", wt, "commit", "-m", "feat"], check=True)
        
        merged, _ = disk._is_merged(wt)
        self.assertFalse(merged)

if __name__ == "__main__":
    unittest.main()
