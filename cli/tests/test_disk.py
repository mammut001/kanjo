"""Disk report and Trash-only clean. Every path is under a temp directory."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from datetime import datetime
from unittest import mock

from kanjo import cli
from kanjo import disk, disk_cache
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
        return disk.report(roots=self.roots, now=time.time() if now is None else now, rescan=True)

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

    def test_older_than_does_not_follow_symlinked_entry_root(self):
        outside = os.path.join(self.tmp, "outside")
        target = self.write(os.path.join(outside, "valuable"), "data")
        os.makedirs(self.claude, exist_ok=True)
        os.symlink(outside, self.shell)
        old = time.time() - 10 * DAY
        os.utime(target, (old, old))
        self.clean(["claude:shell-snapshots"], older_than_days=5, yes=True)
        self.assertTrue(os.path.exists(target))

    def test_sizes_counts_and_deletable_defaults(self):
        now = time.time()
        old = now - 3 * DAY
        self.write(os.path.join(self.projects, "slug", "s.jsonl"), "{}\n")
        self.write(os.path.join(self.shell, "snap.txt"), "snap")
        self.write(os.path.join(self.debug, "debug.log"), "debug")
        self.write(os.path.join(self.scratch, "enc-a", "sess", "scratchpad", "a.txt"), "a")
        self.write(os.path.join(self.scratch, "enc-b", "sess", "scratchpad", "b.txt"), "b")
        self.write(os.path.join(self.scratch, "loose.log"), "loose")
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
            "claude:scratch": ("scratch", "when_clean", [], 1),
            "claude:scratch:enc-a/sess": ("scratch", "when_clean", [], 1),
            "claude:scratch:enc-b/sess": ("scratch", "when_clean", [], 1),
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
        # One entry per session folder; together they add up to the whole scratch root.
        parts = [self.entry(doc, e) for e in seen if e.startswith("claude:scratch")]
        self.assertEqual(len(parts), 3)
        self.assertEqual(sum(p["files"] for p in parts), 3)
        self.assertEqual(sum(p["bytes"] for p in parts), disk.measure(self.scratch, now)["bytes"])
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

    @unittest.skipIf(os.name == "nt", "os.chmod does not make a directory unreadable on Windows")
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
            expect[path] = disk._stat_bytes(os.lstat(path))
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
        self.assertIn("active", self.entry(self.report(now), "claude:scratch:enc/sess")["blocked"])
        set_tree_mtime(self.scratch, now - ACTIVE_INSIDE)
        self.assertIn("active", self.entry(self.report(now), "claude:scratch:enc/sess")["blocked"])
        set_tree_mtime(self.scratch, now - DAY)
        entry = self.entry(self.report(now), "claude:scratch:enc/sess")
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
        expect = disk._stat_bytes(os.lstat(old))
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

    def _assistant_line(self, msg_id, output_tokens):
        return json.dumps({
            "type": "assistant",
            "timestamp": "2026-10-02T19:50:00.000Z",
            "cwd": self.tmp,
            "sessionId": SID,
            "uuid": "u-" + msg_id,
            "message": {
                "model": "claude-opus-5-5",
                "id": msg_id,
                "content": [],
                "usage": {"input_tokens": 10, "output_tokens": output_tokens},
            },
        }) + "\n"

    def _ledger_output_tokens(self):
        ledger = Ledger(directory=self.data)
        return sum(m.output for _key, session in ledger.orphan_sessions() for m in session.messages)

    def test_usage_written_after_the_last_import_is_kept_by_clean(self):
        path = self.write_claude()
        from kanjo.export import scan
        scan(self.scan_dirs(), cache=None)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(self._assistant_line("msg_disk_later", 50000))
        self.assertEqual(self.entry(self.report(), "claude:sessions")["blocked"], [])
        self.clean(["claude:sessions"], yes=True)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self._ledger_output_tokens(), 50004)

    def test_session_imported_while_empty_is_reimported_before_clean(self):
        path = self.write(os.path.join(self.projects, "slug", SID + ".jsonl"), json.dumps({
            "type": "user", "timestamp": "2026-10-02T19:48:00.000Z", "cwd": self.tmp,
            "sessionId": SID, "uuid": "u0", "message": {"role": "user", "content": "hi"},
        }) + "\n")
        from kanjo.export import scan
        scan(self.scan_dirs(), cache=None)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(self._assistant_line("msg_disk_reply", 7))
        self.clean(["claude:sessions"], yes=True)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self._ledger_output_tokens(), 7)

    def test_claude_memory_is_never_moved_with_the_sessions(self):
        log = self.write_claude()
        memory = self.write(os.path.join(self.projects, "slug", "memory", "MEMORY.md"), "- remember\n")
        topic = self.write(os.path.join(self.projects, "slug", "memory", "topic.md"), "notes\n")
        from kanjo.export import scan
        scan(self.scan_dirs(), cache=None)
        now = time.time()
        set_tree_mtime(self.projects, now - 40 * DAY)
        self.assertEqual(self.entry(self.report(now), "claude:sessions")["blocked"], [])

        plan = self.clean(["claude:sessions"], older_than_days=30, dry_run=True, now=now)
        self.assertIn(log, plan["moved"])
        self.assertNotIn(memory, plan["moved"])
        self.assertNotIn(topic, plan["moved"])

        done = self.clean(["claude:sessions"], yes=True, now=now)
        self.assertFalse(os.path.exists(log))
        self.assertTrue(os.path.isfile(memory))
        self.assertTrue(os.path.isfile(topic))
        self.assertNotIn(self.projects, done["moved"])

    def test_tool_home_without_its_sessions_folder_is_not_a_sessions_entry(self):
        subdirs = {
            "workbuddy": "projects", "workbuddy_ai": "projects", "codebuddy": "projects",
            "qodercli": "projects", "qodercli_cn": "projects", "kimicode": "sessions",
            "musecode": "sessions", "prime_agent": "sessions", "omp": "sessions",
            "qwenwork": os.path.join("logs", "sessions"), "grok_bot": "sand-client-persistence",
            "openclaw": "agents",
        }
        for key, sub in subdirs.items():
            home = os.path.join(self.tmp, "home-" + key)
            auth = self.write(os.path.join(home, "auth.json"), "{}")
            set_tree_mtime(home, time.time() - 40 * DAY)
            roots = {key: home}
            doc = disk.report(roots=roots, rescan=True)
            ids = [e["id"] for a in doc["agents"] for e in a["entries"]]
            self.assertEqual(ids, [], key)
            done = disk.clean([key + ":sessions"], yes=True, roots=roots, trash_dir=self.trash)
            self.assertEqual(done["moved"], [], key)
            self.assertTrue(os.path.isfile(auth), key)
            # With the folder present, only that folder is the entry.
            os.makedirs(os.path.join(home, sub))
            doc = disk.report(roots=roots, rescan=True)
            paths = [e["path"] for a in doc["agents"] for e in a["entries"]]
            self.assertEqual(paths, [os.path.join(home, sub)], key)

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

    @unittest.skipIf(os.name == "nt", "os.symlink needs Developer Mode/admin rights on Windows")
    def test_parallel_scratch_matches_sequential_reference(self):
        for name in ("a", "b", "c", "empty"):
            os.makedirs(os.path.join(self.scratch, name))
        self.write(os.path.join(self.scratch, "root-file"), "root")
        for name in ("a", "b", "c"):
            for i in range(5):
                self.write(os.path.join(self.scratch, name, "nested", str(i)), "x" * (i + 4096))
        os.symlink("a", os.path.join(self.scratch, "linked-dir"))
        os.symlink("missing", os.path.join(self.scratch, "dangling"))
        os.symlink("../root-file", os.path.join(self.scratch, "b", "linked-file"))
        old = time.time() - 3 * DAY
        set_tree_mtime(self.scratch, old)
        now = time.time()
        expected = sequential_measure(self.scratch, now)
        # A single-worker pool also checks that splitting cannot deadlock.
        for workers in (1, 4):
            with ThreadPoolExecutor(max_workers=workers) as executor:
                parts = []
                def submit(path, st):
                    parts.append(executor.submit(disk.measure, path, now, _root_stat=st))
                shallow = disk.measure(self.scratch, now, _submit=submit)
                actual = disk._sum_measurements([shallow] + [part.result() for part in parts], now)
            self.assertEqual(actual, expected)
        doc = self.report(now)
        entry = self.entry(doc, "claude:scratch")
        # a/nested, b/nested and c/nested are session folders with entries of their own.
        parts = [e for a in doc["agents"] for e in a["entries"] if e["id"].startswith("claude:scratch")]
        self.assertEqual(sorted(e["id"] for e in parts),
                         ["claude:scratch", "claude:scratch:a/nested", "claude:scratch:b/nested",
                          "claude:scratch:c/nested"])
        for key in ("bytes", "files"):
            self.assertEqual(sum(e[key] for e in parts), expected[key])
        self.assertEqual(sum(e["skipped_errors"] for e in parts), expected["errors"])
        self.assertEqual(entry["oldest"], datetime.fromtimestamp(expected["oldest"]).strftime("%Y-%m-%d"))
        self.assertEqual(entry["newest"], datetime.fromtimestamp(expected["newest"]).strftime("%Y-%m-%d"))
        self.assertEqual([e["blocked"] for e in parts], [[]] * 4)

    def test_entries_and_scratch_children_run_concurrently(self):
        self.write(os.path.join(self.scratch, "a", "f"))
        self.write(os.path.join(self.scratch, "b", "f"))
        self.write(os.path.join(self.logs, "f"))
        paths = {os.path.join(self.scratch, "a"), self.logs}
        barrier = threading.Barrier(len(paths))
        measure = disk.measure
        def synchronized(path, *args, **kwargs):
            if path in paths:
                barrier.wait(timeout=5)
            return measure(path, *args, **kwargs)
        with mock.patch.object(disk.os, "cpu_count", return_value=8), \
                mock.patch.object(disk, "measure", side_effect=synchronized):
            doc = self.report()
        self.assertEqual(self.entry(doc, "claude:scratch")["files"], 2)
        self.assertEqual(self.entry(doc, "codex:logs")["files"], 1)

    def test_cache_written_reused_and_expired(self):
        self.write(os.path.join(self.shell, "f"))
        now = time.time()
        fresh = disk.report(roots=self.roots, now=now)
        self.assertIs(fresh["cached"], False)
        self.assertIsInstance(fresh["scan_seconds"], float)
        self.assertGreaterEqual(fresh["scan_seconds"], 0)
        self.assertAlmostEqual(datetime.fromisoformat(fresh["scanned_at"].replace("Z", "+00:00")).timestamp(),
                               now, places=5)
        with open(disk_cache.cache_path(), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["report"], fresh)
        with mock.patch.object(disk, "_collect", side_effect=AssertionError("cache should skip scan")), \
                mock.patch.object(disk, "Ledger", side_effect=AssertionError("cache should skip ledger")):
            warm = disk.report(roots=self.roots, now=now + 599)
        self.assertEqual(warm, dict(fresh, cached=True))
        self.assertAlmostEqual(disk_cache.cache_age(now + 10), 10, places=5)
        scanned = datetime.fromisoformat(fresh["scanned_at"].replace("Z", "+00:00")).timestamp()
        expired = disk.report(roots=self.roots, now=scanned + 600)
        self.assertIs(expired["cached"], False)
        self.assertNotEqual(expired["scanned_at"], fresh["scanned_at"])

    def test_mtime_tolerance_is_windows_only(self):
        """The coarse-clock tolerance exists for Windows; POSIX stays exact.

        A root whose mtime sits a few milliseconds past the scan boundary (a clock
        tick, not an edit) is accepted on Windows and rejected everywhere else.
        """
        self.write(os.path.join(self.shell, "f"))
        self.write(os.path.join(self.logs, "f"))
        now = time.time()
        self.report(now)
        later = now + 0.02
        os.utime(self.shell, (later, later))

        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            self.assertEqual(disk_cache._sig_tolerance(), 0.0)
            self.assertIs(disk.report(roots=self.roots, now=now + 10)["cached"], False)
        with mock.patch("kanjo.winsupport.is_windows", return_value=True):
            self.assertEqual(disk_cache._sig_tolerance(), 0.05)
            self.assertIs(disk.report(roots=self.roots, now=now + 10)["cached"], True)

        # A real edit past the tolerance still invalidates on Windows.
        os.utime(self.shell, (now + 1, now + 1))
        with mock.patch("kanjo.winsupport.is_windows", return_value=True):
            self.assertIs(disk.report(roots=self.roots, now=now + 2)["cached"], False)

    def test_cli_rescan_and_zero_max_age_ignore_cache(self):
        self.write(os.path.join(self.shell, "f"))
        for flags, expected in (((), False), ((), True), (("--rescan",), False),
                                (("--max-age", "0"), False), (("--max-age", "600"), True)):
            code, out, err = self.cli("disk", "--json", *flags)
            self.assertEqual((code, err), (0, ""))
            self.assertIs(json.loads(out)["cached"], expected)

    def test_root_newer_or_missing_invalidates_whole_cache(self):
        self.write(os.path.join(self.shell, "f"))
        self.write(os.path.join(self.logs, "f"))
        now = time.time()
        disk.report(roots=self.roots, now=now)
        os.utime(self.shell, (now + 1, now + 1))
        with mock.patch.object(disk, "_collect", wraps=disk._collect) as collect:
            fresh = disk.report(roots=self.roots, now=now + 2)
        self.assertIs(fresh["cached"], False)
        collect.assert_called_once()
        shutil.rmtree(self.logs)
        missing = disk.report(roots=self.roots, now=now + 3)
        self.assertIs(missing["cached"], False)
        self.assertNotIn("codex:logs", [e["id"] for a in missing["agents"] for e in a["entries"]])

    def test_changed_roots_and_bad_cache_are_ignored(self):
        self.write(os.path.join(self.shell, "f"))
        self.report()
        other_roots = dict(self.roots, claude_projects=[])
        changed = disk.report(roots=other_roots)
        self.assertIs(changed["cached"], False)
        with open(disk_cache.cache_path(), "w", encoding="utf-8") as handle:
            handle.write('{"report":')
        self.assertIs(disk.report(roots=self.roots)["cached"], False)
        self.assertEqual(os.listdir(self.cache_dir), ["disk-report.json"])

    def test_clean_rescans_active_descendants_and_invalidates_after_move(self):
        path = self.write(os.path.join(self.scratch, "nested", "f"))
        now = time.time()
        set_tree_mtime(self.scratch, now - 3 * DAY)
        doc = self.report(now)
        self.assertEqual(self.entry(doc, "claude:scratch")["blocked"], [])
        # The root's mtime stays old, so the reporting cache is still usable.
        os.utime(path, (now, now))
        self.assertIs(disk.report(roots=self.roots, now=now)["cached"], True)
        with mock.patch.object(disk, "measure", wraps=disk.measure) as measured:
            result = self.clean(["claude:scratch"], now=now, yes=True)
        self.assertTrue(measured.called)
        self.assertEqual(result["skipped"], [{"id": "claude:scratch", "reason": "active"}])
        self.assertTrue(os.path.exists(path))
        self.write(os.path.join(self.shell, "f"))
        self.report()
        self.clean(["claude:shell-snapshots"], dry_run=True, yes=True)
        self.assertTrue(os.path.isfile(disk_cache.cache_path()))
        self.clean(["claude:shell-snapshots"], yes=True)
        self.assertFalse(os.path.exists(disk_cache.cache_path()))
        self.assertFalse(os.path.exists(self.shell))

    def test_failed_cache_replace_preserves_previous_report_and_removes_temp(self):
        self.write(os.path.join(self.shell, "f"))
        fresh = self.report()
        with mock.patch.object(disk_cache.os, "replace", side_effect=OSError("read only")):
            disk_cache.save(dict(fresh, total_bytes=0), self.roots)
        with open(disk_cache.cache_path(), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["report"], fresh)
        self.assertEqual(os.listdir(self.cache_dir), ["disk-report.json"])

    def test_partial_clean_failure_invalidates_cache(self):
        now = time.time()
        paths = []
        for name in ("a.log", "b.log", "c.log", "d.log", "e.log"):
            path = self.write(os.path.join(self.debug, name))
            os.utime(path, (now - 10 * DAY, now - 10 * DAY))
            paths.append(path)
        self.report(now)
        relocate = disk._relocate
        calls = []
        def fail_third(src, dest):
            calls.append(src)
            if len(calls) == 3:
                raise OSError("move failed")
            relocate(src, dest)
        with mock.patch.object(disk, "_relocate", side_effect=fail_third):
            result = self.clean(["claude:debug"], older_than_days=5, yes=True, now=now)
        self.assertEqual(len(calls), 3)
        moved_ok = calls[:2]
        left = set(paths) - set(moved_ok)
        self.assertEqual(set(result["moved"]), set(moved_ok))
        self.assertEqual(len(result["moved"]), 2)
        self.assertGreater(result["freed_bytes"], 0)
        for path in moved_ok:
            self.assertFalse(os.path.exists(path))
        for path in left:
            self.assertTrue(os.path.exists(path))
        file_skips = [row for row in result["skipped"] if row["id"] in set(paths)]
        self.assertEqual({row["id"] for row in file_skips}, left)
        self.assertTrue(all(row["reason"] == "move_failed" for row in file_skips))
        self.assertEqual(result["skipped"][-1], {"id": "claude:debug", "reason": "move_failed"})
        self.assertFalse(os.path.exists(disk_cache.cache_path()))

    def test_idle_scratch_blocked_when_process_probe_unknown(self):
        path = self.write(os.path.join(self.scratch, "p", "s", "scratchpad", "f.txt"), "f")
        set_tree_mtime(self.scratch, time.time() - 3 * DAY)
        with mock.patch.object(disk, "_path_in_use", return_value=None):
            entry = self.entry(self.report(), "claude:scratch:p/s")
        self.assertIn("active", entry["blocked"])
        self.assertTrue(os.path.exists(path))

    def test_scratch_clean_uses_in_use_probe(self):
        self.write(os.path.join(self.scratch, "p", "s", "scratchpad", "f.txt"), "f")
        set_tree_mtime(self.scratch, time.time() - 3 * DAY)
        self.report()
        busy = os.path.join(self.scratch, "p", "s")
        with mock.patch.object(disk, "_run_path_probe", return_value=[busy]):
            result = self.clean(["claude:scratch:p/s"], yes=True)
        self.assertEqual(result["moved"], [])
        self.assertEqual(result["skipped"], [{"id": "claude:scratch:p/s", "reason": "active"}])

    def test_scratch_clean_skips_when_probe_unknown(self):
        self.write(os.path.join(self.scratch, "loose.log"), "l")
        set_tree_mtime(self.scratch, time.time() - 3 * DAY)
        self.report()
        with mock.patch.object(disk, "_run_path_probe", return_value=None):
            result = self.clean(["claude:scratch"], yes=True)
        self.assertEqual(result["moved"], [])
        self.assertIn({"id": "claude:scratch", "reason": "active"}, result["skipped"])

    def test_scratch_in_use_from_one_lsof_probe(self):
        s1 = os.path.join(self.scratch, "proj", "sess1")
        s2 = os.path.join(self.scratch, "proj", "sess2")
        s3 = os.path.join(self.scratch, "proj", "sess3")
        self.write(os.path.join(s1, "scratchpad", "cwd.log"), "c")
        open_file = self.write(os.path.join(s2, "scratchpad", "keep.log"), "k")
        self.write(os.path.join(s3, "scratchpad", "idle.log"), "i")
        set_tree_mtime(self.scratch, time.time() - 3 * DAY)
        lsof_out = b"\n".join([
            b"p99991", b"fcwd", ("n" + os.path.realpath(s1)).encode(),
            b"p99992", b"f5", ("n" + open_file).encode(),
        ]) + b"\n"

        class FakeProc:
            def communicate(self, timeout=None):
                return lsof_out, b""

            def kill(self):
                pass

        popen_calls = []

        def fake_popen(args, **kwargs):
            popen_calls.append(args)
            return FakeProc()

        with mock.patch.object(disk, "_lsof_bin", return_value="/usr/sbin/lsof"), \
                mock.patch.object(disk.subprocess, "Popen", side_effect=fake_popen):
            doc = self.report()
        self.assertEqual(len(popen_calls), 1)
        self.assertIn("active", self.entry(doc, "claude:scratch:proj/sess1")["blocked"])
        self.assertIn("active", self.entry(doc, "claude:scratch:proj/sess2")["blocked"])
        self.assertEqual(self.entry(doc, "claude:scratch:proj/sess3")["blocked"], [])

        popen_calls.clear()
        with mock.patch.object(disk, "_lsof_bin", return_value="/usr/sbin/lsof"), \
                mock.patch.object(disk.subprocess, "Popen", side_effect=fake_popen):
            result = self.clean(
                ["claude:scratch:proj/sess1", "claude:scratch:proj/sess2", "claude:scratch:proj/sess3"],
                yes=True,
            )
        # One lsof for the rescan report, one for the clean-time scratch recheck.
        self.assertEqual(len(popen_calls), 2)
        self.assertEqual(result["moved"], [s3])
        skipped_ids = {row["id"] for row in result["skipped"]}
        self.assertEqual(skipped_ids, {"claude:scratch:proj/sess1", "claude:scratch:proj/sess2"})

    def test_doctor_prints_disk_cache_path_and_age(self):
        self.report()
        code, out, err = self.cli("doctor", "--no-cache")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("disk cache: " + disk_cache.cache_path(), out)
        self.assertRegex(out, r"age: [0-9.]+ seconds")

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


def sequential_measure(root, now):
    stats = [os.lstat(root)]
    files = 0
    for path, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            full = os.path.join(path, name)
            stats.append(os.lstat(full))
            if name in names or os.path.islink(full):
                files += 1
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(path, name))]
    newest = max(st.st_mtime for st in stats)
    return {"bytes": sum(disk._stat_bytes(st) for st in stats), "files": files,
            "oldest": min(st.st_mtime for st in stats), "newest": newest,
            "errors": 0, "active": now - newest < disk.ACTIVE_SECONDS}


def set_tree_mtime(path, ts):
    """Pin the mtime of ``path`` and everything under it.

    ``follow_symlinks=False`` is unavailable on Windows (``os.utime`` raises
    NotImplementedError there), and the tests never pin a symlink's own mtime, so
    the plain call is used where the flag is unsupported.
    """
    for dirpath, dirnames, filenames in os.walk(path):
        for name in filenames + dirnames:
            entry = os.path.join(dirpath, name)
            try:
                os.utime(entry, (ts, ts), follow_symlinks=False)
            except NotImplementedError:
                if not os.path.islink(entry):
                    os.utime(entry, (ts, ts))
    os.utime(path, (ts, ts))


def git(cwd, *args):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    cmd = ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false",
           "-c", "user.email=kanjo@example.com", "-c", "user.name=kanjo"] + list(args)
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise AssertionError("%s\n%s" % (" ".join(cmd), proc.stderr))


def _excludes(entry, doc):
    """Paths of the other entries inside ``entry`` (they are measured on their own)."""
    root = entry["path"].rstrip(os.sep) + os.sep
    inner = [e["path"] for a in doc["agents"] for e in a["entries"] if e["path"].startswith(root)]
    return inner or None


def _session_ids(doc):
    found = []
    for project in doc["projects"]:
        found.extend(s["id"] for s in project["sessions_detail"])
    for name in ("unattributed", "excluded"):
        found.extend(s["id"] for s in doc["buckets"][name]["sessions_detail"])
    return found


ACTIVE_INSIDE = 23 * 3600


class DiskRootIsolationTest(unittest.TestCase):
    """``KANJO_DATA_DIR`` must not point scratch or the Claude app cache at the real home."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-disk-roots-")
        self.data = os.path.join(self.tmp, "data")
        self.scratch = os.path.join(self.tmp, "scratch")
        self.app = os.path.join(self.tmp, "ClaudeApp")
        os.makedirs(self.data)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_data_dir_hides_real_scratch_and_claude_app(self):
        with mock.patch.dict(os.environ, {"KANJO_DATA_DIR": self.data}, clear=True):
            roots = disk.default_roots()
        self.assertIsNone(roots["scratch"])
        self.assertIsNone(roots["claude_app"])

    def test_explicit_scratch_and_claude_app_still_win(self):
        env = {
            "KANJO_DATA_DIR": self.data,
            "KANJO_SCRATCH_DIR": self.scratch,
            "KANJO_CLAUDE_APP_CACHE": self.app,
        }
        with mock.patch.dict(os.environ, env, clear=True):
            roots = disk.default_roots()
        self.assertEqual(roots["scratch"], self.scratch)
        self.assertEqual(roots["claude_app"], self.app)

    def test_unisolated_defaults_are_names_only(self):
        seen = []
        real_isdir = os.path.isdir

        def tracking(path):
            seen.append(os.path.abspath(os.fspath(path)))
            return real_isdir(path)

        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("os.path.isdir", tracking):
            roots = disk.default_roots()
        home = os.path.abspath(os.path.expanduser("~"))
        self.assertEqual(roots["scratch"], disk._default_scratch())
        self.assertEqual(
            roots["claude_app"],
            os.path.join(home, "Library", "Application Support", "Claude"),
        )
        for path in seen:
            self.assertFalse(path == home or path.startswith(home + os.sep), path)



class LsofNonAsciiTest(unittest.TestCase):
    """lsof escapes non-ASCII bytes as \\xNN in the C locale; the probe must still match."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-lsof-")
        self.dir = os.path.join(self.tmp, "\u9879\u76ee wt")
        os.makedirs(self.dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_escaped_name_counts_as_in_use(self):
        raw = os.path.realpath(self.dir).encode("utf-8")
        escaped = b"".join(b"\\x%02x" % c if c >= 0x80 else bytes([c]) for c in raw)

        class FakeProc:
            def communicate(self, timeout=None):
                return b"p1\nR1\nfcwd\nn" + escaped + b"\n", b""

        paths = disk._finish_cwd_probe(FakeProc())
        with mock.patch.object(disk, "_lsof_bin", return_value="/usr/sbin/lsof"), \
             mock.patch.object(disk.winsupport, "is_windows", return_value=False):
            self.assertTrue(disk._path_in_use(self.dir, paths))

    def test_probe_runs_lsof_in_a_utf8_locale(self):
        seen = {}

        def fake_popen(argv, **kwargs):
            seen["env"] = kwargs.get("env")
            raise OSError("no lsof here")

        with mock.patch.object(disk.winsupport, "is_windows", return_value=False), \
             mock.patch.object(disk.shutil, "which", return_value="/usr/sbin/lsof"), \
             mock.patch.object(disk.subprocess, "Popen", side_effect=fake_popen):
            self.assertIsNone(disk._start_cwd_probe())
        self.assertIn("UTF-8", (seen["env"] or {}).get("LC_ALL", ""))


if __name__ == "__main__":
    unittest.main()
