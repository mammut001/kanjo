"""Disk report and Trash-only clean. Every path is under a temp directory."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from datetime import datetime
from unittest import mock

from kanjo import cli
from kanjo import disk
from kanjo.export import build_export
from kanjo.ledger import Ledger

from tests.support import ALICE

SID = "22222222-2222-2222-2222-222222222222"
DAY = 86400


class DiskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-disk-")
        self.trash = os.path.join(self.tmp, "trash")
        self.data = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        os.makedirs(self.trash)
        os.makedirs(self.data)
        self.claude = os.path.join(self.tmp, "claude")
        self.projects = os.path.join(self.claude, "projects")
        self.shell = os.path.join(self.claude, "shell-snapshots")
        self.debug = os.path.join(self.claude, "debug")
        self.scratch = os.path.join(self.tmp, "scratch")
        self.codex = os.path.join(self.tmp, "codex")
        self.sessions = os.path.join(self.codex, "sessions")
        self.archived = os.path.join(self.codex, "archived_sessions")
        self.worktrees = os.path.join(self.codex, "worktrees")
        self.logs = os.path.join(self.codex, "logs")
        self.agy = os.path.join(self.tmp, "gemini", "antigravity-cli")
        self.conversations = os.path.join(self.agy, "conversations")
        self.brain = os.path.join(self.agy, "brain")
        self.agy_cache = os.path.join(self.agy, "cache")
        self.grok = os.path.join(self.tmp, "grok")
        self.app = os.path.join(self.tmp, "ClaudeApp")
        self.repo = os.path.join(self.tmp, "main-repo")
        self.roots = {
            "claude_projects": [self.projects],
            "scratch": self.scratch,
            "codex_dirs": [self.sessions, self.archived],
            "antigravity_dirs": [self.conversations],
            "grok": self.grok,
            "claude_app": self.app,
        }
        self.env = mock.patch.dict(os.environ, {
            "KANJO_DATA_DIR": self.data,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_TRASH_DIR": self.trash,
            "KANJO_CLAUDE_DIR": self.projects,
            "KANJO_CODEX_DIR": self.sessions + os.pathsep + self.archived,
            "KANJO_ANTIGRAVITY_DIR": self.conversations,
            "KANJO_SCRATCH_DIR": self.scratch,
            "KANJO_GROK_DIR": self.grok,
            "KANJO_CLAUDE_APP_CACHE": self.app,
            "KANJO_TOKEI_DIR": os.path.join(self.tmp, "no-tokei"),
            "KANJO_CLAUDE_CONFIG": os.path.join(self.tmp, "no-claude.json"),
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        for dirpath, dirnames, filenames in os.walk(self.tmp, topdown=True):
            try:
                os.chmod(dirpath, 0o755)
            except OSError:
                pass
            for name in list(dirnames) + list(filenames):
                try:
                    os.chmod(os.path.join(dirpath, name), 0o755)
                except OSError:
                    pass
        shutil.rmtree(self.tmp)

    def write(self, path, text="x"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def report(self, now=None):
        return disk.report(roots=self.roots, now=time.time() if now is None else now)

    def entry(self, doc, eid):
        for agent in doc["agents"]:
            for entry in agent["entries"]:
                if entry["id"] == eid:
                    return entry
        self.fail("missing entry %s in %s" % (eid, [e["id"] for a in doc["agents"] for e in a["entries"]]))

    def clean(self, ids, **kw):
        kw.setdefault("roots", self.roots)
        kw.setdefault("trash_dir", self.trash)
        return disk.clean(ids, **kw)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_sizes_counts_and_deletable_defaults(self):
        now = time.time()
        old = now - 3 * DAY
        self.write(os.path.join(self.projects, "slug", "s.jsonl"), "{}\n")
        self.write(os.path.join(self.shell, "snap.txt"), "snap")
        self.write(os.path.join(self.debug, "debug.log"), "debug")
        self.write(os.path.join(self.scratch, "enc-a", "sess", "scratchpad", "a.txt"), "a")
        self.write(os.path.join(self.scratch, "enc-b", "sess", "scratchpad", "b.txt"), "b")
        self.write(os.path.join(self.sessions, "2026", "01", "01", "rollout-a.jsonl"), "{}\n")
        self.write(os.path.join(self.archived, "rollout-b.jsonl"), "{}\n")
        self.write(os.path.join(self.logs, "codex.log"), "log")
        self.write(os.path.join(self.conversations, "abc.db"), "db")
        self.write(os.path.join(self.brain, "b1", "notes.md"), "memory")
        self.write(os.path.join(self.brain, "b1", "scratch", "s.txt"), "s")
        self.write(os.path.join(self.brain, "b2", "scratch", "s.txt"), "s2")
        self.write(os.path.join(self.agy_cache, "c.bin"), "c")
        self.write(os.path.join(self.grok, "sessions", "g.jsonl"), "g")
        self.write(os.path.join(self.grok, "bundled", "bundle.bin"), "b")
        self.write(os.path.join(self.app, "Cache", "a"), "a")
        self.write(os.path.join(self.app, "Code Cache", "b"), "b")
        self.write(os.path.join(self.app, "GPUCache", "c"), "c")
        for path in (self.scratch, self.brain, self.shell, self.debug, self.logs, self.agy_cache, self.app):
            set_tree_mtime(path, old)

        doc = self.report(now)
        expected = {
            "claude:sessions": ("sessions", "after_import", ["not_imported"], 1),
            "claude:shell-snapshots": ("cache", "always", [], 1),
            "claude:debug": ("cache", "always", [], 1),
            "claude:scratch": ("scratch", "when_clean", [], 2),
            "codex:sessions": ("sessions", "after_import", ["not_imported"], 1),
            "codex:archived_sessions": ("sessions", "after_import", ["not_imported"], 1),
            "codex:logs": ("cache", "always", [], 1),
            "antigravity:sessions": ("sessions", "after_import", ["not_imported"], 1),
            "antigravity:scratch:b1": ("scratch", "when_clean", [], 1),
            "antigravity:scratch:b2": ("scratch", "when_clean", [], 1),
            "antigravity:memory": ("memory", "never", [], 1),
            "antigravity:cache": ("cache", "always", [], 1),
            "grok:sessions": ("sessions", "after_import", ["not_imported"], 1),
            "grok:bundled": ("other", "never", [], 1),
            "claude-desktop:cache": ("cache", "always", [], 1),
            "claude-desktop:code-cache": ("cache", "always", [], 1),
            "claude-desktop:gpucache": ("cache", "always", [], 1),
        }
        seen = [e["id"] for a in doc["agents"] for e in a["entries"]]
        self.assertEqual(sorted(seen), sorted(expected))
        day = datetime.fromtimestamp(old).strftime("%Y-%m-%d")
        for eid, (kind, deletable, blocked, files) in expected.items():
            entry = self.entry(doc, eid)
            self.assertEqual(entry["kind"], kind, eid)
            self.assertEqual(entry["deletable"], deletable, eid)
            self.assertEqual(entry["blocked"], blocked, eid)
            self.assertEqual(entry["files"], files, eid)
            if kind == "sessions":
                self.assertEqual(entry["log_files"], files, eid)
                self.assertEqual(entry["imported_files"], 0, eid)
            else:
                self.assertNotIn("log_files", entry, eid)
            self.assertEqual(entry["bytes"], disk.measure(entry["path"], now, exclude=_excludes(entry, doc))["bytes"], eid)
            self.assertGreater(entry["bytes"], 0, eid)
            self.assertEqual(entry["skipped_errors"], 0, eid)
            self.assertTrue(entry["path"].startswith(self.tmp), entry["path"])
            if eid != "antigravity:memory":
                self.assertEqual(entry["newest"], day if eid != "claude:sessions" and not eid.startswith("codex:") and eid != "antigravity:sessions" and not eid.startswith("grok:") else entry["newest"])
        scratch = self.entry(doc, "claude:scratch")
        self.assertEqual(scratch["files"], 2)
        self.assertEqual(len([e for e in seen if e.startswith("claude:scratch")]), 1)
        memory = self.entry(doc, "antigravity:memory")
        scratches = [self.entry(doc, "antigravity:scratch:b1"), self.entry(doc, "antigravity:scratch:b2")]
        whole = disk.measure(self.brain, now)
        self.assertEqual(memory["bytes"] + sum(s["bytes"] for s in scratches), whole["bytes"])
        self.assertEqual(memory["files"] + sum(s["files"] for s in scratches), whole["files"])
        self.assertEqual(scratch["newest"], day)
        flat = [e for a in doc["agents"] for e in a["entries"]]
        self.assertEqual(doc["total_bytes"], sum(e["bytes"] for e in flat))
        reclaim = sum(e["bytes"] for e in flat if e["deletable"] != "never" and not e["blocked"])
        self.assertEqual(doc["reclaimable_bytes"], reclaim)
        self.assertLess(doc["reclaimable_bytes"], doc["total_bytes"])
        self.assertNotIn(memory["bytes"], (doc["reclaimable_bytes"],))  # memory is never reclaimable on its own
        self.assertEqual(doc["schema_version"], 1)

    def test_permission_errors_are_counted(self):
        secret = os.path.join(self.logs, "secret")
        self.write(os.path.join(secret, "hidden"), "nope")
        os.chmod(secret, 0)
        try:
            doc = self.report()
            entry = self.entry(doc, "codex:logs")
            self.assertGreaterEqual(entry["skipped_errors"], 1)
            self.assertEqual(entry["files"], 0)
        finally:
            os.chmod(secret, 0o755)

    def test_not_imported_clears_after_import(self):
        self.write_claude()
        doc = self.report()
        self.assertEqual(self.entry(doc, "claude:sessions")["blocked"], ["not_imported"])
        self.assertEqual(self.entry(doc, "claude:sessions")["log_files"], 1)
        self.assertEqual(self.entry(doc, "claude:sessions")["imported_files"], 0)
        from kanjo.export import scan
        scan(self.scan_dirs(), cache=None)
        doc = self.report()
        entry = self.entry(doc, "claude:sessions")
        self.assertEqual(entry["blocked"], [])
        self.assertEqual(entry["deletable"], "after_import")
        self.assertEqual(entry["log_files"], 1)
        self.assertEqual(entry["imported_files"], 1)

    def test_changed_signature_still_counts_as_imported(self):
        path = self.write_claude()
        from kanjo.cache import _signature
        from kanjo.export import scan
        scan(self.scan_dirs(), cache=None)
        stored = next(iter(Ledger(directory=self.data).entries.values()))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write('{"type":"user","message":{"content":"later"}}\n')
        self.assertNotEqual(stored["file_sig"], _signature(path))
        self.assertEqual(stored["source_path"], path)
        doc = self.report()
        entry = self.entry(doc, "claude:sessions")
        self.assertEqual(entry["blocked"], [])
        self.assertEqual(entry["log_files"], 1)
        self.assertEqual(entry["imported_files"], 1)
        now = time.time()
        os.utime(path, (now - 10 * DAY, now - 10 * DAY))
        done = self.clean(["claude:sessions"], older_than_days=5, yes=True, now=now)
        self.assertEqual(done["moved"], [path])
        self.assertEqual(done["skipped"], [])
        self.assertFalse(os.path.exists(path))

    def test_missing_ledger_entry_blocks_and_older_than_skips_that_file(self):
        now = time.time()
        imported = self.write_claude()
        from kanjo.export import scan
        scan(self.scan_dirs(), cache=None)
        slug = os.path.join(self.projects, "slug")
        extra = self.write(os.path.join(slug, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"), "{}\n")
        image = self.write(os.path.join(slug, "shot.png"), "img")
        meta = self.write(os.path.join(slug, "meta.json"), "{}")
        packed = self.write(os.path.join(slug, "old.zst"), "z")
        store = self.write(os.path.join(slug, ".DS_Store"), "ds")
        recent = self.write(os.path.join(slug, "recent.png"), "new")
        for path in (imported, extra, image, meta, packed, store):
            os.utime(path, (now - 10 * DAY, now - 10 * DAY))

        doc = self.report(now)
        entry = self.entry(doc, "claude:sessions")
        self.assertEqual(entry["log_files"], 2)
        self.assertEqual(entry["imported_files"], 1)
        self.assertEqual(entry["blocked"], ["not_imported"])
        self.assertGreater(entry["files"], entry["log_files"])

        code, out, _ = self.cli("disk", "--json")
        self.assertEqual(code, 0)
        listed = self.entry(json.loads(out), "claude:sessions")
        self.assertEqual(listed["log_files"], 2)
        self.assertEqual(listed["imported_files"], 1)
        code, table, _ = self.cli("disk")
        self.assertEqual(code, 0)
        self.assertIn("1/2", table)
        self.assertIn("claude:sessions", table)

        refused = self.clean(["claude:sessions"], yes=True, now=now)
        self.assertEqual(refused["moved"], [])
        self.assertEqual(refused["skipped"], [{"id": "claude:sessions", "reason": "not_imported"}])
        self.assertTrue(os.path.exists(imported))
        self.assertTrue(os.path.exists(extra))

        expect = {}
        for path in (imported, image, meta, packed, store):
            expect[path] = os.lstat(path).st_blocks * 512
        done = self.clean(["claude:sessions"], older_than_days=5, yes=True, now=now)
        self.assertEqual(set(done["moved"]), set(expect))
        self.assertEqual(done["freed_bytes"], sum(expect.values()))
        self.assertEqual(done["skipped"], [{"id": extra, "reason": "not_imported"}])
        self.assertFalse(any(os.path.exists(path) for path in expect))
        self.assertTrue(os.path.exists(extra))
        self.assertTrue(os.path.exists(recent))
        self.assertTrue(os.path.isdir(self.projects))

    def test_grok_sessions_stay_blocked_for_older_than(self):
        now = time.time()
        path = self.write(os.path.join(self.grok, "sessions", "g.jsonl"), "g")
        os.utime(path, (now - 10 * DAY, now - 10 * DAY))
        entry = self.entry(self.report(now), "grok:sessions")
        self.assertEqual(entry["blocked"], ["not_imported"])
        self.assertEqual(entry["imported_files"], 0)
        self.assertEqual(entry["log_files"], 1)
        done = self.clean(["grok:sessions"], older_than_days=5, yes=True, now=now)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(done["moved"], [])
        self.assertEqual(done["skipped"], [{"id": "grok:sessions", "reason": "not_imported"}])

    def test_active_detection(self):
        path = self.write(os.path.join(self.scratch, "enc", "sess", "scratchpad", "f.txt"), "f")
        now = time.time()
        self.assertIn("active", self.entry(self.report(now), "claude:scratch")["blocked"])
        set_tree_mtime(self.scratch, now - ACTIVE_INSIDE)
        self.assertIn("active", self.entry(self.report(now), "claude:scratch")["blocked"])
        set_tree_mtime(self.scratch, now - DAY)
        entry = self.entry(self.report(now), "claude:scratch")
        self.assertNotIn("active", entry["blocked"])
        self.assertEqual(entry["blocked"], [])
        self.assertTrue(os.path.exists(path))

    def test_uncommitted_changes_and_worktree_remove(self):
        now = time.time()
        dirty = self.make_worktree("dirty")
        with open(os.path.join(dirty, "README"), "a", encoding="utf-8") as handle:
            handle.write("dirty\n")
        set_tree_mtime(dirty, now - 3 * DAY)
        clean = self.make_worktree("clean")
        set_tree_mtime(clean, now - 3 * DAY)

        doc = self.report(now)
        dirty_entry = self.entry(doc, "codex:worktree:dirty")
        clean_entry = self.entry(doc, "codex:worktree:clean")
        self.assertEqual(dirty_entry["deletable"], "when_clean")
        self.assertIn("uncommitted_changes", dirty_entry["blocked"])
        self.assertNotIn("active", dirty_entry["blocked"])
        self.assertEqual(clean_entry["blocked"], [])
        self.assertEqual(clean_entry["kind"], "worktrees")

        refused = self.clean(["codex:worktree:dirty"], yes=True, now=now)
        self.assertEqual(refused["moved"], [])
        self.assertEqual(refused["skipped"], [{"id": "codex:worktree:dirty", "reason": "uncommitted_changes"}])
        self.assertTrue(os.path.isdir(dirty))

        plan = self.clean(["codex:worktree:clean"], yes=False, now=now)
        self.assertEqual(plan["moved"], [clean])
        self.assertEqual(plan["freed_bytes"], clean_entry["bytes"])
        self.assertEqual(plan["skipped"], [])
        self.assertTrue(os.path.isdir(clean))
        again = self.clean(["codex:worktree:clean"], yes=True, dry_run=True, now=now)
        self.assertTrue(os.path.isdir(clean))
        self.assertEqual(again["freed_bytes"], clean_entry["bytes"])

        done = self.clean(["codex:worktree:clean"], yes=True, now=now)
        self.assertEqual(done["moved"], [clean])
        self.assertEqual(done["freed_bytes"], clean_entry["bytes"])
        self.assertFalse(os.path.exists(clean))
        self.assertTrue(os.path.isdir(self.repo))
        listed = subprocess.check_output(["git", "-C", self.repo, "worktree", "list"], text=True)
        self.assertNotIn(clean, listed)
        self.assertEqual(os.listdir(self.trash), [])

    def test_dry_run_moves_nothing_and_yes_matches_freed_bytes(self):
        path = self.write(os.path.join(self.shell, "a.txt"), "hello-disk")
        doc = self.report()
        entry = self.entry(doc, "claude:shell-snapshots")
        plan = self.clean(["claude:shell-snapshots"], yes=False)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(plan["moved"], [self.shell])
        self.assertEqual(plan["freed_bytes"], entry["bytes"])
        self.assertEqual(os.listdir(self.trash), [])
        held = self.clean(["claude:shell-snapshots"], yes=True, dry_run=True)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(held["freed_bytes"], entry["bytes"])
        done = self.clean(["claude:shell-snapshots"], yes=True)
        self.assertFalse(os.path.exists(self.shell))
        self.assertEqual(done["freed_bytes"], entry["bytes"])
        self.assertEqual(done["skipped"], [])
        names = []
        stamp = None
        for dirpath, _dirs, files in os.walk(self.trash):
            names.extend(files)
            base = os.path.basename(dirpath)
            if base.startswith("kanjo-"):
                stamp = base
        self.assertIn("a.txt", names)
        self.assertIsNotNone(stamp)

    def test_older_than_keeps_newer_files(self):
        now = time.time()
        old = self.write(os.path.join(self.debug, "old.log"), "old")
        new = self.write(os.path.join(self.debug, "new.log"), "new")
        os.utime(old, (now - 10 * DAY, now - 10 * DAY))
        os.utime(new, (now - DAY, now - DAY))
        expect = os.lstat(old).st_blocks * 512
        done = self.clean(["claude:debug"], older_than_days=5, yes=True, now=now)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))
        self.assertTrue(os.path.isdir(self.debug))
        self.assertEqual(done["moved"], [old])
        self.assertEqual(done["freed_bytes"], expect)
        self.assertEqual(done["skipped"], [])
        found = []
        for _dirpath, _dirs, files in os.walk(self.trash):
            found.extend(files)
        self.assertEqual(found, ["old.log"])

    def test_clean_refuses_never_and_unknown_ids(self):
        path = self.write(os.path.join(self.grok, "bundled", "keep.bin"), "keep")
        out = self.clean(["grok:bundled", "missing"], yes=True)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(out["moved"], [])
        self.assertEqual(out["skipped"], [
            {"id": "grok:bundled", "reason": "never"},
            {"id": "missing", "reason": "not_found"},
        ])

    def test_cleaning_sessions_keeps_them_in_the_ledger(self):
        path = self.write_claude()
        from kanjo.export import scan
        scan(self.scan_dirs(), cache=None)
        doc = self.report()
        entry = self.entry(doc, "claude:sessions")
        self.assertEqual(entry["blocked"], [])
        done = self.clean(["claude:sessions"], yes=True)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(done["moved"], [self.projects])
        self.assertEqual(done["freed_bytes"], entry["bytes"])
        self.assertEqual(done["skipped"], [])
        ledger = Ledger(directory=self.data)
        self.assertEqual(len(ledger.entries), 1)
        stored = next(iter(ledger.entries.values()))
        self.assertEqual(stored["source_path"], path)
        exported = build_export(dirs=self.scan_dirs(), cache=None, home=ALICE,
                                 tokei_dir=os.path.join(self.tmp, "no-tokei"))
        self.assertIn(SID, _session_ids(exported))
        self.assertGreaterEqual(exported["ledger"]["orphaned"], 1)
        self.assertGreaterEqual(exported["ledger"]["sessions"], 1)

    def test_cli_table_and_json_stay_inside_the_temp_tree(self):
        path = self.write(os.path.join(self.shell, "a.txt"), "a")
        code, out, _ = self.cli("disk", "--json")
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["schema_version"], 1)
        self.assertIn("reclaimable_bytes", doc)
        for agent in doc["agents"]:
            for entry in agent["entries"]:
                self.assertTrue(os.path.abspath(entry["path"]).startswith(self.tmp), entry["path"])
        code, out, _ = self.cli("disk")
        self.assertEqual(code, 0)
        self.assertIn("Deletable", out)
        self.assertIn("claude:shell-snapshots", out)
        self.assertIn("total", out)
        code, out, err = self.cli("disk", "clean", "--older-than", "nope", "claude:shell-snapshots")
        self.assertEqual(code, 2)
        self.assertIn("30d", err)
        code, out, _ = self.cli("disk", "clean", "claude:shell-snapshots")
        self.assertEqual(code, 0)
        plan = json.loads(out)
        self.assertEqual(plan["moved"], [self.shell])
        self.assertTrue(os.path.exists(path))
        self.assertEqual(os.listdir(self.trash), [])

    def scan_dirs(self):
        return {"claude": [self.projects], "codex": [self.sessions], "antigravity": [self.conversations]}

    def write_claude(self):
        return self.write(os.path.join(self.projects, "slug", SID + ".jsonl"), json.dumps({
            "type": "assistant",
            "timestamp": "2026-10-02T19:48:05.461Z",
            "cwd": self.tmp,
            "sessionId": SID,
            "uuid": "u1",
            "message": {
                "model": "claude-opus-5-5",
                "id": "msg_disk_1",
                "content": [],
                "usage": {"input_tokens": 10, "output_tokens": 4},
            },
        }) + "\n")

    def make_worktree(self, name):
        if not os.path.isdir(os.path.join(self.repo, ".git")):
            os.makedirs(self.repo)
            git(self.repo, "init")
            self.write(os.path.join(self.repo, "README"), "v1\n")
            git(self.repo, "add", "README")
            git(self.repo, "commit", "-m", "init")
        os.makedirs(self.worktrees, exist_ok=True)
        path = os.path.join(self.worktrees, name)
        git(self.repo, "worktree", "add", "-b", name, path)
        return path


def set_tree_mtime(path, ts):
    for dirpath, dirnames, filenames in os.walk(path):
        for name in filenames + dirnames:
            os.utime(os.path.join(dirpath, name), (ts, ts))
    os.utime(path, (ts, ts))


def git(cwd, *args):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    cmd = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
           "-c", "user.email=kanjo@example.com", "-c", "user.name=kanjo"] + list(args)
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise AssertionError("%s\n%s" % (" ".join(cmd), proc.stderr))


def _excludes(entry, doc):
    if entry["id"] != "antigravity:memory":
        return None
    return [e["path"] for a in doc["agents"] for e in a["entries"] if e["id"].startswith("antigravity:scratch:")]


def _session_ids(doc):
    found = []
    for project in doc["projects"]:
        found.extend(s["id"] for s in project["sessions_detail"])
    for name in ("unattributed", "excluded"):
        found.extend(s["id"] for s in doc["buckets"][name]["sessions_detail"])
    return found


ACTIVE_INSIDE = 23 * 3600


if __name__ == "__main__":
    unittest.main()
