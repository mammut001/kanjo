"""Concurrent `kanjo config set` calls must not lose each other's overrides.json edits."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
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

    def set_in_threads(self, plans):
        """Start every `config set` at once; each read is held 0.2 s so unserialized writes would overlap."""
        barrier = threading.Barrier(len(plans))
        real_read = config_cmd.read_overrides
        errors = []

        def slow_read(path):
            data = real_read(path)
            time.sleep(0.2)
            return data

        def run(email, plan):
            try:
                barrier.wait()
                code = cli.main(["config", "set", "antigravity_accounts.%s.plan" % email, plan])
                if code != 0:
                    errors.append((email, code))
            except Exception as exc:  # surfaced in the main thread below
                errors.append((email, exc))

        threads = [threading.Thread(target=run, args=item) for item in plans.items()]
        # redirect_stdout swaps a process-wide sys.stdout, so do it once around all threads.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch.object(config_cmd, "read_overrides", slow_read):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(errors, [])

    def test_concurrent_sets_keep_every_account(self):
        plans = {"a@example.com": "google_ai_pro", "b@example.com": "google_ai_ultra"}
        self.set_in_threads(plans)
        accounts = self.read_overrides()["antigravity_accounts"]
        self.assertEqual({email: spec["plan"] for email, spec in accounts.items()}, plans)

    def test_harness_overlaps_without_lock(self):
        # Without the lock the same harness loses a write, so the test above really runs concurrently.
        with mock.patch.object(config_cmd, "_locked_overrides", lambda path: contextlib.nullcontext()):
            self.set_in_threads({"a@example.com": "google_ai_pro", "b@example.com": "google_ai_ultra"})
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
