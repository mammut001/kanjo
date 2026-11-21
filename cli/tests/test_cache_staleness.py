"""Persistent caches must give the same answer as a --no-cache run after the
inputs they summarize change (nested repos, new remotes, in-place updates)."""

import os
import shutil
import tempfile
import unittest

from kanjo.cache import RepoCache, SessionCache
from kanjo.export import ScanResult, build_export
from kanjo.identity import Resolver
from kanjo.sources.base import Message, Session
from tests.support import ALICE, FakeFS

MONO = ALICE + "/code/mono"
SUB = MONO + "/tools/sub"
PROJ = ALICE + "/code/proj"


def make_session(sid, cwd, calls=(), msg_count=2, t0=1790000000.0, agent="claude"):
    s = Session(id=sid, agent=agent, file="/x/" + sid, cwd=cwd)
    s.note_cwd(cwd)
    s.tool_paths = [list(c) for c in calls]
    s.messages = [Message(ts=t0 + i, model="claude-opus-4-5", input=100, output=100,
                          cwd=cwd, branch="main", key="%s:m%d" % (sid, i))
                  for i in range(msg_count)]
    for m in s.messages:
        s.note_time(m.ts)
    return s


def project_summary(doc):
    return sorted((p["id"], p["remote"], round(p["cost"], 6),
                   sorted(d["id"] for d in p["sessions_detail"])) for p in doc["projects"])


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


class RemoteChangeCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-stale-test-")
        self.fs = FakeFS()
        self.fs.repo(PROJ)
        self.fs.write(PROJ + "/src/a.py", "")

    def tearDown(self):
        self.fs.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def export(self, sessions, cached=True):
        return build_export(scan_result=ScanResult(list(sessions), [], {}),
                            cache=SessionCache(self.tmp) if cached else None,
                            home=ALICE, fs_root=self.fs.root)

    def add_remote(self):
        cfg = self.fs.real(PROJ + "/.git/config")
        st = os.stat(cfg)
        with open(cfg, "a", encoding="utf-8") as handle:
            handle.write('[remote "origin"]\n\turl = https://github.com/alice/proj.git\n')
        os.utime(cfg, ns=(st.st_atime_ns, st.st_mtime_ns + 5 * 10 ** 9))

    def test_remote_added_after_first_scan(self):
        s1 = make_session("s1", PROJ, [[PROJ + "/src/a.py"]])
        first = self.export([s1])
        self.assertEqual([p["id"] for p in first["projects"]], [PROJ])
        self.add_remote()
        s2 = make_session("s2", PROJ, [[PROJ + "/src/a.py"]], t0=1790100000.0)
        cached = self.export([s1, s2])
        fresh = self.export([s1, s2], cached=False)
        self.assertEqual(project_summary(cached), project_summary(fresh))
        self.assertEqual([p["id"] for p in cached["projects"]], ["github.com/alice/proj"])

    def test_unchanged_inputs_reuse_cached_decisions(self):
        from unittest import mock
        from kanjo import attribution as attr
        sessions = [make_session("s1", PROJ, [[PROJ + "/src/a.py"]]),
                    make_session("s2", PROJ, [[PROJ + "/src/a.py", PROJ + "/src"]], t0=1790100000.0)]
        self.export(sessions)
        with mock.patch.object(attr, "decide", wraps=attr.decide) as decide:
            self.export(sessions)
        self.assertEqual(decide.call_count, 0)

    def test_repo_cache_entry_expires_when_config_changes(self):
        cache = RepoCache(self.tmp)
        Resolver(fs_root=self.fs.root, home=ALICE, repo_cache=cache).resolve(PROJ + "/src")
        cache.save()
        self.add_remote()
        cache = RepoCache(self.tmp)
        r = Resolver(fs_root=self.fs.root, home=ALICE, repo_cache=cache)
        self.assertEqual(r.resolve(PROJ + "/src").id, "github.com/alice/proj")


class InPlaceUpdateCacheTest(unittest.TestCase):
    export = RemoteChangeCacheTest.export
    tearDown = RemoteChangeCacheTest.tearDown

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-stale-test-")
        self.fs = FakeFS()
        self.fs.repo(PROJ, [("origin", "https://github.com/alice/proj.git")])
        self.fs.write(PROJ + "/src/a.py", "")

    def details(self, doc):
        return sorted((d["id"], d["title"], round(d["cost"], 6), d["tokens"]["output"])
                      for p in doc["projects"] for d in p["sessions_detail"])

    def test_tokens_rewritten_in_place_and_title_change(self):
        before = make_session("ses_00", PROJ, [[PROJ + "/src/a.py"]], agent="opencode")
        before.title = "hello 0"
        before.messages[-1].output = 10
        self.export([before])
        after = make_session("ses_00", PROJ, [[PROJ + "/src/a.py"]], agent="opencode")
        after.title = "Fix login redirect"
        after.messages[-1].output = 20000
        cached = self.export([after])
        fresh = self.export([after], cached=False)
        self.assertEqual(self.details(cached), self.details(fresh))
        self.assertEqual(self.details(cached)[0][1], "Fix login redirect")
        self.assertEqual(cached["totals"]["cost"], fresh["totals"]["cost"])


if __name__ == "__main__":
    unittest.main()
