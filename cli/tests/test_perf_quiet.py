"""Performance and quiet background refresh tests:
fingerprint hit, cache dirty checks, and disk cache partial re-measurement.
"""

import io
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from kanjo import cli, disk, disk_cache, export, ledger
from tests.support import FIXTURE_DIRS


class PerfQuietTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-perf-test-")
        self.data_dir = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.logs_dir = os.path.join(self.tmp, "logs")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)

        # Copy claude fixture to a writable temp dir so we can touch files
        self.claude_src = os.path.join(self.logs_dir, "claude")
        shutil.copytree(FIXTURE_DIRS["claude"][0], self.claude_src)

        self.env = {
            "KANJO_DATA_DIR": self.data_dir,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_CLAUDE_DIR": self.claude_src,
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
        shutil.rmtree(self.tmp)

    def _run_cli(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, self.env), mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_fingerprint_hit_returns_identical_output(self):
        code1, out1, _ = self._run_cli("export")
        self.assertEqual(code1, 0)
        fast_cache = os.path.join(self.cache_dir, "export-last.json")
        self.assertTrue(os.path.isfile(fast_cache))

        code2, out2, _ = self._run_cli("export")
        self.assertEqual(code2, 0)
        self.assertEqual(out1, out2)

        # Fast path with mobile and compact flags
        code_m1, out_m1, _ = self._run_cli("export", "--mobile")
        code_m2, out_m2, _ = self._run_cli("export", "--mobile")
        self.assertEqual(code_m1, 0)
        self.assertEqual(code_m2, 0)
        self.assertEqual(out_m1, out_m2)

    def test_touching_one_fixture_file_forces_reparse(self):
        code1, out1, _ = self._run_cli("export")
        self.assertEqual(code1, 0)
        fast_cache = os.path.join(self.cache_dir, "export-last.json")
        with open(fast_cache, encoding="utf-8") as f:
            fp1 = json.load(f)["fingerprint"]

        # Find a log file in claude_src and touch it
        target_file = None
        for root, _, files in os.walk(self.claude_src):
            for file in files:
                if file.endswith(".jsonl"):
                    target_file = os.path.join(root, file)
                    break
            if target_file:
                break
        self.assertIsNotNone(target_file)

        # Touch the file (update mtime)
        new_mtime = time.time() + 10
        os.utime(target_file, (new_mtime, new_mtime))

        code2, out2, _ = self._run_cli("export")
        self.assertEqual(code2, 0)
        with open(fast_cache, encoding="utf-8") as f:
            fp2 = json.load(f)["fingerprint"]

        self.assertNotEqual(fp1, fp2)

    def test_no_cache_ledger_write_when_nothing_changed(self):
        # Initial run populates cache and ledger
        code1, _, _ = self._run_cli("export")
        self.assertEqual(code1, 0)

        ledger_file = os.path.join(self.data_dir, "ledger.json")
        parse_cache = os.path.join(self.cache_dir, "parse-cache-v4.json")
        self.assertTrue(os.path.isfile(ledger_file))
        self.assertTrue(os.path.isfile(parse_cache))

        ledger_mtime_before = os.path.getmtime(ledger_file)
        cache_mtime_before = os.path.getmtime(parse_cache)

        time.sleep(0.05)

        # Second run with --no-cache bypasses export fast path, runs full scan,
        # but because nothing changed in logs, ledger and parse cache must not be re-saved.
        # Wait, if --no-cache is passed, cache is None. Let's test full scan with cache!
        # We test full scan without fast-path by calling export.scan:
        from kanjo.cache import SessionCache
        from kanjo.ledger import Ledger
        sc = SessionCache(self.cache_dir)
        led = Ledger(self.data_dir)
        with mock.patch.dict(os.environ, self.env):
            export.scan(cache=sc, ledger=led)

        self.assertEqual(os.path.getmtime(ledger_file), ledger_mtime_before)
        self.assertEqual(os.path.getmtime(parse_cache), cache_mtime_before)

    def test_disk_cache_survives_unrelated_mtime_change(self):
        # Create two distinct target directories for disk report
        dir_a = os.path.join(self.tmp, "tool_a")
        dir_b = os.path.join(self.tmp, "tool_b")
        os.makedirs(dir_a, exist_ok=True)
        os.makedirs(dir_b, exist_ok=True)
        with open(os.path.join(dir_a, "file.txt"), "w") as f:
            f.write("hello from a\n")
        with open(os.path.join(dir_b, "file.txt"), "w") as f:
            f.write("hello from b\n")

        roots = {
            "claude_projects": [dir_a],
            "scratch": dir_b,
        }

        with mock.patch.dict(os.environ, self.env):
            r1 = disk.report(roots=roots, max_age=3600)
            self.assertFalse(r1.get("cached", False))

            # Hit cache
            r2 = disk.report(roots=roots, max_age=3600)
            self.assertTrue(r2.get("cached", False))

            # Now touch dir_b only (dir_a is unchanged)
            future_time = time.time() + 100
            os.utime(dir_b, (future_time, future_time))

            # Mock measure to ensure dir_a is not re-measured
            original_measure = disk.measure
            measured_paths = []
            def track_measure(path, *margs, **mkwargs):
                measured_paths.append(path)
                return original_measure(path, *margs, **mkwargs)

            with mock.patch("kanjo.disk.measure", side_effect=track_measure):
                r3 = disk.report(roots=roots, max_age=3600)

            # dir_a should NOT have been re-measured!
            self.assertNotIn(dir_a, measured_paths)
            # dir_b should have been re-measured!
            self.assertIn(dir_b, measured_paths)

    def test_paths_command(self):
        code, out, _ = self._run_cli("paths", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("claude", data)
        self.assertTrue(any(self.claude_src in p for p in data["claude"]))
