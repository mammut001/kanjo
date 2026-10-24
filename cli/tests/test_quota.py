"""quota_windows: Tokei caches, staleness, manual config."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from kanjo import cli, config, quota
from kanjo.config import ConfigError
from kanjo.export import build_export

from tests.support import ALICE, FIXTURE_DIRS, check_quota_windows, standard_fs

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc).timestamp()
HOUR = 3600
DAY = 86400


def ts(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def claude_cache(updated, q7, q5):
    # structure of a real ~/.tokei/claude_quota_swift_cache.json (paths trimmed)
    return {"snapshot": {"updated": updated, "q5": 13, "q7": 57, "qfReset": q7, "qf": 65,
                         "q7Reset": q7, "q5Reset": q5},
            "lastFullScan": updated - 11000, "scanModified": updated + 180.5,
            "scanBoundary": ["/Users/alice/Library/Application Support/Claude/Cache/Cache_Data/x_0|1|2"],
            "candidate": {"path": "/Users/alice/Library/Application Support/Claude/Cache/Cache_Data/y_0",
                          "modified": updated + 0.5, "size": 4514},
            "version": 3}


def codex_cache(fetched, weekly, five, window_minutes=10080):
    # structure of a real ~/.tokei/codex_quota_cache.json (keys anonymized)
    return {"fetched_at": fetched + 0.805192,
            "limits": {"limit_id": "codex", "limit_name": None,
                       "primary": {"used_percent": 0.0, "window_minutes": 300, "resets_at": five},
                       "secondary": {"used_percent": 0.0, "window_minutes": window_minutes, "resets_at": weekly},
                       "credits": {"has_credits": False, "unlimited": False, "overage_limit_reached": False,
                                   "balance": "0", "approx_local_messages": [0, 0],
                                   "approx_cloud_messages": [0, 0]},
                       "plan_type": "plus", "rate_limit_reached_type": None},
            "plan": "plus", "account_key": "0" * 64, "auth_key": "1" * 64, "source": "live"}


class QuotaTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kanjo-tokei-")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, name, data):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as h:
            json.dump(data, h)

    def write_both(self, age=HOUR):
        self.write(quota.CLAUDE_FILE, claude_cache(NOW - age, ts("2026-10-27T14:00:00Z"), ts("2026-10-24T16:30:00Z")))
        self.write(quota.CODEX_FILE, codex_cache(NOW - age, ts("2026-10-31T04:53:24Z"), ts("2026-10-24T17:05:49Z")))

    def test_tokei_files_present(self):
        self.write_both()
        qw = quota.quota_windows(directory=self.dir, now=NOW)
        self.assertEqual(qw, {
            "claude": {"weekly_resets_at": "2026-10-27T14:00:00Z", "weekly_window_hours": 168,
                       "five_hour_resets_at": "2026-10-24T16:30:00Z", "source": "tokei"},
            "codex": {"weekly_resets_at": "2026-10-31T04:53:24Z", "weekly_window_hours": 168,
                      "five_hour_resets_at": "2026-10-24T17:05:49Z", "source": "tokei"},
        })
        check_quota_windows(self, qw)

    def test_tokei_missing(self):
        self.assertEqual(quota.quota_windows(directory=self.dir, now=NOW), {})
        self.assertEqual(quota.quota_windows(directory=os.path.join(self.dir, "nope"), now=NOW), {})
        # unreadable / unexpected content is skipped too
        with open(os.path.join(self.dir, quota.CLAUDE_FILE), "w") as h:
            h.write("{not json")
        self.write(quota.CODEX_FILE, {"limits": {"secondary": {"resets_at": "soon"}}, "fetched_at": NOW})
        self.assertEqual(quota.quota_windows(directory=self.dir, now=NOW), {})
        # only one agent available
        self.write(quota.CODEX_FILE, codex_cache(NOW - HOUR, ts("2026-10-31T04:53:24Z"), None))
        qw = quota.quota_windows(directory=self.dir, now=NOW)
        self.assertEqual(list(qw), ["codex"])
        self.assertIsNone(qw["codex"]["five_hour_resets_at"])

    def test_tokei_stale(self):
        self.write_both(age=15 * DAY)
        self.assertEqual(quota.quota_windows(directory=self.dir, now=NOW), {})
        self.write_both(age=13 * DAY)
        self.assertEqual(set(quota.quota_windows(directory=self.dir, now=NOW)), {"claude", "codex"})

    def test_past_resets_roll_forward(self):
        # fetched 3 days ago: weekly reset passed once, 5-hour reset long gone
        self.write(quota.CLAUDE_FILE, claude_cache(NOW - 3 * DAY, ts("2026-10-22T14:00:00Z"), ts("2026-10-21T16:30:00Z")))
        self.write(quota.CODEX_FILE, codex_cache(NOW - 3 * DAY, ts("2026-10-24T11:00:00Z"), ts("2026-10-21T17:00:00Z"),
                                                 window_minutes=4320))
        qw = quota.quota_windows(directory=self.dir, now=NOW)
        self.assertEqual(qw["claude"]["weekly_resets_at"], "2026-10-29T14:00:00Z")
        self.assertIsNone(qw["claude"]["five_hour_resets_at"])
        self.assertEqual(qw["codex"]["weekly_window_hours"], 72)
        self.assertEqual(qw["codex"]["weekly_resets_at"], "2026-10-27T11:00:00Z")

    def test_manual_overrides_tokei(self):
        self.write_both()
        cfg = config.from_dict(config.parse_toml_subset(
            '[quota_windows.claude]\n'
            'weekly_resets_at = "2026-10-27T10:00:00Z"\n'
            'weekly_window_hours = 168\n'))
        qw = quota.quota_windows(cfg.quota_windows, directory=self.dir, now=NOW)
        self.assertEqual(qw["claude"], {"weekly_resets_at": "2026-10-27T10:00:00Z", "weekly_window_hours": 168,
                                        "five_hour_resets_at": None, "source": "manual"})
        self.assertEqual(qw["codex"]["source"], "tokei")
        # manual works without Tokei, and an old anchor rolls forward to the next reset
        cfg = config.from_dict({"quota_windows": {"codex": {"weekly_resets_at": "2026-09-01T08:00:00+02:00"}}})
        qw = quota.quota_windows(cfg.quota_windows, directory=os.path.join(self.dir, "nope"), now=NOW)
        self.assertEqual(qw, {"codex": {"weekly_resets_at": "2026-10-27T06:00:00Z", "weekly_window_hours": 168,
                                        "five_hour_resets_at": None, "source": "manual"}})

    def test_manual_config_parsing(self):
        text = ('dominant_threshold = 0.7\n'
                '[quota_windows.claude]\n'
                'weekly_resets_at = 2026-10-27T10:00:00Z   # bare TOML datetime\n'
                'weekly_window_hours = 168\n'
                'five_hour_resets_at = "2026-10-24T13:30:00Z"\n'
                '[quota_windows.codex]\n'
                'weekly_resets_at = "2026-10-31T04:53:24Z"\n'
                'exclude = ["/Users/alice/scratch"]\n')
        cfg = config.from_dict(config._parse_text(text, "attribution.toml"))
        self.assertEqual(cfg.dominant_threshold, 0.7)
        self.assertEqual(cfg.exclude, ["/Users/alice/scratch"])
        self.assertEqual(cfg.quota_windows["claude"]["weekly_resets_at"], ts("2026-10-27T10:00:00Z"))
        self.assertEqual(cfg.quota_windows["claude"]["five_hour_resets_at"], ts("2026-10-24T13:30:00Z"))
        self.assertEqual(cfg.quota_windows["codex"]["weekly_window_hours"], 168)
        # the built-in subset parser (Python < 3.11) agrees
        self.assertEqual(config.from_dict(config.parse_toml_subset(text)).quota_windows, cfg.quota_windows)
        for bad in ({"claude": {"weekly_window_hours": 168}},
                    {"claude": {"weekly_resets_at": "next tuesday"}},
                    {"claude": {"weekly_resets_at": "2026-10-27T10:00:00Z", "weekly_window_hours": 0}},
                    {"claude": "2026-10-27T10:00:00Z"}):
            with self.assertRaises(ConfigError):
                config.from_dict({"quota_windows": bad})

    def test_export_and_env_override(self):
        self.write_both()
        fs = standard_fs()
        try:
            now = datetime.fromtimestamp(NOW, timezone.utc)
            with mock.patch.dict(os.environ, {"KANJO_TOKEI_DIR": self.dir}):
                doc = build_export(dirs=FIXTURE_DIRS, fs_root=fs.root, home=ALICE, now=now)
            self.assertEqual(set(doc["quota_windows"]), {"claude", "codex"})
            check_quota_windows(self, doc["quota_windows"])
        finally:
            fs.cleanup()

    def test_cli_export_reads_manual_config(self):
        cache = tempfile.mkdtemp()
        try:
            path = os.path.join(cache, "attribution.json")
            with open(path, "w") as h:
                json.dump({"quota_windows": {"claude": {"weekly_resets_at": "2099-01-05T10:00:00Z"}}}, h)
            env = {"KANJO_CLAUDE_DIR": FIXTURE_DIRS["claude"][0],
                   "KANJO_ANTIGRAVITY_DIR": FIXTURE_DIRS["antigravity"][0],
                   "KANJO_CODEX_DIR": FIXTURE_DIRS["codex"][0],
                   "KANJO_CACHE_DIR": cache, "KANJO_TOKEI_DIR": self.dir}
            out = io.StringIO()
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["export", "--config", path, "--no-cache"]), 0)
            self.assertEqual(json.loads(out.getvalue())["quota_windows"], {
                "claude": {"weekly_resets_at": "2099-01-05T10:00:00Z", "weekly_window_hours": 168,
                           "five_hour_resets_at": None, "source": "manual"}})
        finally:
            shutil.rmtree(cache)


if __name__ == "__main__":
    unittest.main()
