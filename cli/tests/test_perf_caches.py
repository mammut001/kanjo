"""Tests for incremental export caches:
- WorktreeCache (infer_deleted_worktrees caching and invalidation)
- AttributionCache (unit attribution caching and invalidation)
- RepoCache (directory inode / negative cache validation)
- Verification that cached path produces results identical to the uncached path.
"""

import hashlib
import json
import os
import shutil
import tempfile
import time
import unittest

from kanjo import attribution as attr
from kanjo.cache import AttributionCache, RepoCache, SessionCache, WorktreeCache
from kanjo.config import Config
from kanjo.export import ScanResult, build_export, build_units, dedupe
from kanjo.identity import Resolver, ScratchpadDecoder
from kanjo.sources.base import Message, Session
from tests.support import ALICE, FakeFS

APP_DIR = ALICE + "/code/app"
WT_DIR = ALICE + "/code/wt-feature"
PROJ_ID = "github.com/alice/app"


def make_session(sid="s1", cwd=WT_DIR, calls=(), agent="claude", msg_count=2):
    s = Session(id=sid, agent=agent, file=f"/x/{sid}", cwd=cwd)
    if cwd:
        s.note_cwd(cwd)
    s.tool_paths = [list(c) for c in calls]
    s.messages = [
        Message(ts=1790000000.0 + i, model="claude-opus-5-5", input=100, output=100,
                cwd=cwd, branch="main", key=f"{sid}:m{i}")
        for i in range(msg_count)
    ]
    for m in s.messages:
        s.note_time(m.ts)
    return s


class PerfCachesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-cache-test-")
        self.fs = FakeFS()
        self.fs.repo(APP_DIR, [("origin", "https://github.com/alice/app.git")])
        self.fs.write(APP_DIR + "/src/Button.tsx", "export const Button = () => null;\n")

    def tearDown(self):
        self.fs.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_worktree_cache_roundtrip_and_invalidation(self):
        wt_cache = WorktreeCache(self.tmp)
        s1 = make_session("s1", cwd=WT_DIR, calls=[[WT_DIR + "/src/Button.tsx"]])

        # Initially uncached
        r1 = Resolver(fs_root=self.fs.root, home=ALICE, worktree_cache=wt_cache)
        r1.resolve(APP_DIR)
        r1.infer_deleted_worktrees([s1])
        res1 = r1.resolve(WT_DIR, allow_missing_fallback=False)
        self.assertIsNotNone(res1)
        self.assertEqual(res1.id, PROJ_ID)
        wt_cache.save()

        # Reload cache from disk
        wt_cache_loaded = WorktreeCache(self.tmp)
        self.assertIn(WT_DIR, wt_cache_loaded.entries)

        # Run 2: uses cached worktree inference
        r2 = Resolver(fs_root=self.fs.root, home=ALICE, worktree_cache=wt_cache_loaded)
        r2.resolve(APP_DIR)
        r2.infer_deleted_worktrees([s1])
        res2 = r2.resolve(WT_DIR, allow_missing_fallback=False)
        self.assertIsNotNone(res2)
        self.assertEqual(res2.id, PROJ_ID)

        # Invalidation: session changes (new message added)
        s1_changed = make_session("s1", cwd=WT_DIR, calls=[[WT_DIR + "/src/Button.tsx"]], msg_count=5)
        sigs = {s1_changed.id: f"{s1_changed.cwd}:{len(s1_changed.messages)}:1:{s1_changed.ended}"}
        known = {PROJ_ID: [APP_DIR]}
        cached_pid = wt_cache_loaded.get_worktree(WT_DIR, sigs, known, lambda _: False)
        self.assertIsNone(cached_pid, "WorktreeCache should invalidate when session signature changes")

        # Invalidation: directory recreated on filesystem
        self.fs.mkdir(WT_DIR)
        cached_pid = wt_cache_loaded.get_worktree(WT_DIR, {"s1": f"{WT_DIR}:2:1:{s1.ended}"}, known,
                                                  lambda p: self.fs.real(p) is not None and os.path.exists(self.fs.real(p)))
        self.assertIsNone(cached_pid, "WorktreeCache should invalidate if path now exists on disk")

    def test_deleting_worktree_directory_inferred_and_cached(self):
        wt_cache = WorktreeCache(self.tmp)
        # Create worktree on disk initially
        self.fs.mkdir(WT_DIR)
        s = make_session("s1", cwd=WT_DIR, calls=[[WT_DIR + "/src/Button.tsx"]])

        # While on disk, it's not a deleted worktree candidate
        r1 = Resolver(fs_root=self.fs.root, home=ALICE, worktree_cache=wt_cache)
        r1.resolve(APP_DIR)
        r1.infer_deleted_worktrees([s])
        self.assertNotIn(WT_DIR, wt_cache.entries)

        # Now delete worktree directory
        shutil.rmtree(self.fs.real(WT_DIR))
        r2 = Resolver(fs_root=self.fs.root, home=ALICE, worktree_cache=wt_cache)
        r2.resolve(APP_DIR)
        r2.infer_deleted_worktrees([s])
        res = r2.resolve(WT_DIR, allow_missing_fallback=False)
        self.assertIsNotNone(res)
        self.assertEqual(res.id, PROJ_ID)
        self.assertIn(WT_DIR, wt_cache.entries)

    def test_attribution_cache_roundtrip_and_invalidation(self):
        attr_cache = AttributionCache(self.tmp)
        s1 = make_session("s1", cwd=APP_DIR)
        cfg = Config(dominant_threshold=0.8)
        scratch = ScratchpadDecoder(fs_root=self.fs.root)
        resolver = Resolver(fs_root=self.fs.root, home=ALICE)
        worktree_sig = "wt_sig_1"
        config_sig = "cfg_sig_1"

        # Initially uncached
        cached_dec = attr_cache.get(s1, worktree_sig, config_sig)
        self.assertIsNone(cached_dec)

        # Compute and put
        dec = attr.decide(s1, resolver, scratch, cfg)
        attr_cache.put(s1, {
            "kind": dec.kind,
            "shares": dec.shares,
            "scores": dec.scores,
            "paths": {PROJ_ID: [APP_DIR]},
        }, worktree_sig, config_sig)
        attr_cache.save()

        # Reload cache
        loaded_attr_cache = AttributionCache(self.tmp)
        cached_dec = loaded_attr_cache.get(s1, worktree_sig, config_sig)
        self.assertIsNotNone(cached_dec)
        self.assertEqual(cached_dec["kind"], dec.kind)
        self.assertEqual([tuple(x) for x in cached_dec["shares"]], dec.shares)

        # Invalidation 1: session modified
        s1_modified = make_session("s1", cwd=APP_DIR, msg_count=10)
        self.assertIsNone(loaded_attr_cache.get(s1_modified, worktree_sig, config_sig))

        # Invalidation 2: worktree config changed
        self.assertIsNone(loaded_attr_cache.get(s1, "wt_sig_2", config_sig))

        # Invalidation 3: user config changed
        self.assertIsNone(loaded_attr_cache.get(s1, worktree_sig, "cfg_sig_2"))

    def test_repo_cache_negative_lookup_and_invalidation(self):
        repo_cache = RepoCache(self.tmp)
        non_repo = ALICE + "/plain_dir"
        self.fs.mkdir(non_repo)

        # First lookup: miss
        hit, val = repo_cache.get(non_repo, fs_root=self.fs.root)
        self.assertFalse(hit)

        # Put negative entry
        repo_cache.put(non_repo, None)
        repo_cache.save()

        # Reload and check hit
        loaded_repo_cache = RepoCache(self.tmp)
        hit, val = loaded_repo_cache.get(non_repo, fs_root=self.fs.root)
        self.assertTrue(hit)
        self.assertIsNone(val)

        # TTL expiration
        hit, val = loaded_repo_cache.get(non_repo, fs_root=self.fs.root, now=time.time() + 700)
        self.assertFalse(hit, "RepoCache should invalidate negative entry after TTL expires")

    def test_cached_results_equal_uncached_path(self):
        s1 = make_session("s1", cwd=APP_DIR, calls=[[APP_DIR + "/src/Button.tsx"]])
        s2 = make_session("s2", cwd=WT_DIR, calls=[[WT_DIR + "/src/Button.tsx"]])

        # 1. Uncached path
        r_uncached = Resolver(fs_root=self.fs.root, home=ALICE)
        r_uncached.resolve(APP_DIR)
        r_uncached.infer_deleted_worktrees([s1, s2])
        dec1_uncached = attr.decide(s1, r_uncached, None, Config())
        dec2_uncached = attr.decide(s2, r_uncached, None, Config())

        # 2. Cached path
        cache = SessionCache(self.tmp)
        r_cached = Resolver(fs_root=self.fs.root, home=ALICE,
                            repo_cache=cache.repo_cache, worktree_cache=cache.worktree_cache)
        r_cached.resolve(APP_DIR)
        r_cached.infer_deleted_worktrees([s1, s2])
        cache.save()

        dec1_cached = attr.decide(s1, r_cached, None, Config())
        dec2_cached = attr.decide(s2, r_cached, None, Config())

        self.assertEqual(dec1_uncached.kind, dec1_cached.kind)
        self.assertEqual(dec1_uncached.shares, dec1_cached.shares)
        self.assertEqual(dec2_uncached.kind, dec2_cached.kind)
        self.assertEqual(dec2_uncached.shares, dec2_cached.shares)
        self.assertEqual(r_uncached.resolve(WT_DIR).id, r_cached.resolve(WT_DIR).id)


if __name__ == "__main__":
    unittest.main()
