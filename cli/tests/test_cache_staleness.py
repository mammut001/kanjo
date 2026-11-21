"""Persistent caches must give the same answer as a --no-cache run after the
inputs they summarize change (nested repos, new remotes, in-place updates)."""

import os
import shutil
import tempfile
import unittest

from kanjo.cache import RepoCache
from kanjo.identity import Resolver
from tests.support import ALICE, FakeFS

MONO = ALICE + "/code/mono"
SUB = MONO + "/tools/sub"


class NestedRepoCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-stale-test-")
        self.fs = FakeFS()

    def tearDown(self):
        self.fs.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cached_outer_ancestor_does_not_hide_nested_repo(self):
        self.fs.repo(MONO, [("origin", "https://github.com/alice/mono.git")])
        self.fs.repo(SUB, [("origin", "https://github.com/alice/sub.git")])
        self.fs.write(MONO + "/tools/README.md", "")
        self.fs.write(SUB + "/src/a.py", "")
        cache = RepoCache(self.tmp)
        r1 = Resolver(fs_root=self.fs.root, home=ALICE, repo_cache=cache)
        self.assertEqual(r1.resolve(MONO + "/tools/README.md").id, "github.com/alice/mono")
        cache.save()

        cache = RepoCache(self.tmp)
        r2 = Resolver(fs_root=self.fs.root, home=ALICE, repo_cache=cache)
        self.assertEqual(r2.resolve(SUB + "/src/a.py").id, "github.com/alice/sub")
        self.assertEqual(r2.resolve(SUB + "/src").id, "github.com/alice/sub")
        self.assertEqual(r2.resolve(MONO + "/tools").id, "github.com/alice/mono")


if __name__ == "__main__":
    unittest.main()
