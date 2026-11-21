"""Concurrent `kanjo config set` calls must not lose each other's overrides.json edits."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from kanjo import cli, config_cmd

CLI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ConfigConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kanjo-config-lock-")
        self.addCleanup(self.temp.cleanup)
        root = self.temp.name
        self.config_dir = os.path.join(root, "config")
        os.mkdir(self.config_dir)
        self.overrides = os.path.join(self.config_dir, "overrides.json")
        self.env = {
            "KANJO_CONFIG_DIR": self.config_dir,
            "KANJO_CACHE_DIR": os.path.join(root, "cache"),
            "KANJO_DATA_DIR": os.path.join(root, "data"),
            "KANJO_TOKEI_DIR": root,
            "KANJO_CLAUDE_CONFIG": os.path.join(root, "claude.json"),
            "KANJO_CLAUDE_DIR": os.path.join(root, "claude"),
            "KANJO_CODEX_DIR": os.path.join(root, "codex"),
            "KANJO_ANTIGRAVITY_DIR": os.path.join(root, "antigravity"),
        }
        patch = mock.patch.dict(os.environ, self.env)
        patch.start()
        self.addCleanup(patch.stop)

    def read_overrides(self):
        with open(self.overrides, encoding="utf-8") as handle:
            return json.load(handle)

    def set_in_threads(self, plans, expect_overlap=False):
        """Start every `config set` at once so unserialized read-modify-writes overlap deterministically."""
        n = len(plans)
        start_barrier = threading.Barrier(n)
        read_barrier = threading.Barrier(n)
        real_lock = config_cmd._locked_overrides
        real_read = config_cmd.read_overrides
        real_write = config_cmd._write
        write_guard = threading.Lock()
        overlapped = threading.Event()
        errors = []

        @contextlib.contextmanager
        def aligned_lock(path):
            # Sync right before acquiring the lock so argparse/setup jitter cannot serialize threads.
            start_barrier.wait(timeout=10)
            with real_lock(path):
                yield

        def sync_read(path):
            data = real_read(path)
            # Without the lock, every thread meets here after reading the same pre-write snapshot,
            # guaranteeing an overlapping read-modify-write. With the lock, the first thread times
            # out here while the others wait on the lock, proving mutual exclusion.
            try:
                read_barrier.wait(timeout=10 if expect_overlap else 0.15)
                overlapped.set()
            except threading.BrokenBarrierError:
                pass
            return data

        def guarded_write(path, data):
            # When the lock is intentionally disabled, serialize only the final rename so Windows
            # does not raise PermissionError on simultaneous os.replace of the same target.
            if expect_overlap:
                with write_guard:
                    return real_write(path, data)
            return real_write(path, data)

        def run(email, plan):
            try:
                code = cli.main(["config", "set", "antigravity_accounts.%s.plan" % email, plan])
                if code != 0:
                    errors.append((email, code))
                    start_barrier.abort()
                    read_barrier.abort()
            except Exception as exc:  # surfaced in the main thread below
                errors.append((email, exc))
                start_barrier.abort()
                read_barrier.abort()

        threads = [threading.Thread(target=run, args=item) for item in plans.items()]
        # redirect_stdout swaps a process-wide sys.stdout, so do it once around all threads.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch.object(config_cmd, "_locked_overrides", aligned_lock), \
                mock.patch.object(config_cmd, "read_overrides", sync_read), \
                mock.patch.object(config_cmd, "_write", guarded_write):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(errors, [])
        return overlapped.is_set()

    def test_concurrent_sets_keep_every_account(self):
        plans = {"a@example.com": "google_ai_pro", "b@example.com": "google_ai_ultra"}
        overlapped = self.set_in_threads(plans)
        self.assertFalse(overlapped)
        accounts = self.read_overrides()["antigravity_accounts"]
        self.assertEqual({email: spec["plan"] for email, spec in accounts.items()}, plans)

    def test_harness_overlaps_without_lock(self):
        # Without the lock the same harness loses a write, so the test above really runs concurrently.
        with mock.patch.object(config_cmd, "_locked_overrides", lambda path: contextlib.nullcontext()):
            overlapped = self.set_in_threads(
                {"a@example.com": "google_ai_pro", "b@example.com": "google_ai_ultra"},
                expect_overlap=True,
            )
        self.assertTrue(overlapped)
        self.assertEqual(len(self.read_overrides()["antigravity_accounts"]), 1)

    def test_concurrent_processes_keep_every_account(self):
        env = dict(os.environ, **self.env)
        env["PYTHONPATH"] = CLI_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        plans = {"user%d@example.com" % i: ("google_ai_pro", "google_ai_ultra")[i % 2] for i in range(6)}
        procs = [subprocess.Popen([sys.executable, "-m", "kanjo", "config", "set",
                                   "antigravity_accounts.%s.plan" % email, plan],
                                  cwd=CLI_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for email, plan in plans.items()]
        for proc in procs:
            _, err = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, err.decode("utf-8", "replace"))
        accounts = self.read_overrides()["antigravity_accounts"]
        self.assertEqual({email: spec["plan"] for email, spec in accounts.items()}, plans)

    def test_none_round_trip(self):
        key = "antigravity_accounts.a@example.com.plan"
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["config", "set", key, "google_ai_pro"]), 0)
            self.assertEqual(cli.main(["config", "set", key, "none"]), 0)
        self.assertEqual(self.read_overrides()["antigravity_accounts"]["a@example.com"]["plan"], "none")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["config", "get", key]), 0)
        self.assertIn('"none"', out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["config", "set", key, "google_ai_ultra"]), 0)
        self.assertEqual(self.read_overrides()["antigravity_accounts"]["a@example.com"]["plan"], "google_ai_ultra")


if __name__ == "__main__":
    unittest.main()
