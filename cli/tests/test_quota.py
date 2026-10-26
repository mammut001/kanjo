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


def grok_cache(fetched, reset, window="week", plan="SuperGrok", pct=42.0, stale=False):
    # structure of ~/.tokei/grok_quota_cache.json
    quota_dict = {"reset": reset, "plan": plan, "pct": pct, "stale": stale}
    if window is not None:
        quota_dict["window"] = window
    return {"fetched_at": fetched, "quota": quota_dict}


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

    def write_all(self, age=HOUR):
        self.write_both(age=age)
        self.write(quota.GROK_FILE, grok_cache(NOW - age, ts("2026-10-27T05:00:00Z")))

    def test_tokei_files_present(self):
        self.write_both()
        qw = quota.quota_windows(directory=self.dir, now=NOW)
        self.assertEqual(qw, {
            "claude": {"weekly_resets_at": "2026-10-27T14:00:00Z", "weekly_window_hours": 168,
                       "weekly_used_percent": 57.0,
                       "five_hour_resets_at": "2026-10-24T16:30:00Z", "five_hour_window_hours": 5,
                       "five_hour_used_percent": 13.0, "source": "tokei"},
            "codex": {"weekly_resets_at": "2026-10-31T04:53:24Z", "weekly_window_hours": 168,
                      "weekly_used_percent": 0.0,
                      "five_hour_resets_at": "2026-10-24T17:05:49Z", "five_hour_window_hours": 5,
                      "five_hour_used_percent": 0.0, "source": "tokei"},
        })
        check_quota_windows(self, qw)

    def test_grok_tokei_cache(self):
        self.write_all()
        qw = quota.quota_windows(directory=self.dir, now=NOW)
        self.assertEqual(qw["grok"], {
            "weekly_resets_at": "2026-10-27T05:00:00Z",
            "weekly_window_hours": 168,
            "weekly_used_percent": 42.0,
            "five_hour_resets_at": None,
            "five_hour_window_hours": None,
            "five_hour_used_percent": None,
            "source": "tokei",
        })
        check_quota_windows(self, qw)

    def test_used_percent_edge_cases(self):
        # past weekly reset rolls forward and drops the old window's percent; past 5h drops both
        self.write(quota.CLAUDE_FILE, claude_cache(NOW - HOUR, ts("2026-10-20T14:00:00Z"), ts("2026-10-24T10:00:00Z")))
        c = quota.quota_windows(directory=self.dir, now=NOW)["claude"]
        self.assertEqual(c["weekly_resets_at"], "2026-10-27T14:00:00Z")
        self.assertIsNone(c["weekly_used_percent"])
        self.assertIsNone(c["five_hour_resets_at"])
        self.assertEqual(c["five_hour_window_hours"], 5)  # ended, not absent
        self.assertIsNone(c["five_hour_used_percent"])
        # codex: real percents, clamped; malformed -> null
        data = codex_cache(NOW - HOUR, ts("2026-10-31T04:53:24Z"), ts("2026-10-24T17:05:49Z"))
        data["limits"]["primary"]["used_percent"] = 130
        data["limits"]["secondary"]["used_percent"] = "x"
        self.write(quota.CODEX_FILE, data)
        c = quota.quota_windows(directory=self.dir, now=NOW)["codex"]
        self.assertEqual(c["five_hour_used_percent"], 100.0)
        self.assertIsNone(c["weekly_used_percent"])
        check_quota_windows(self, {"codex": c})

    def test_grok_window_mapping(self):
        # "day" -> 24h
        self.write(quota.GROK_FILE, grok_cache(NOW - HOUR, ts("2026-10-25T05:00:00Z"), window="day"))
        qw = quota.quota_windows(directory=self.dir, now=NOW)
        self.assertEqual(qw["grok"]["weekly_window_hours"], 24)
        self.assertEqual(qw["grok"]["weekly_resets_at"], "2026-10-25T05:00:00Z")

        # None / missing window -> default 168h
        self.write(quota.GROK_FILE, grok_cache(NOW - HOUR, ts("2026-10-27T05:00:00Z"), window=None))
        qw = quota.quota_windows(directory=self.dir, now=NOW)
        self.assertEqual(qw["grok"]["weekly_window_hours"], 168)

        # "month" -> skipped
        self.write(quota.GROK_FILE, grok_cache(NOW - HOUR, ts("2026-10-27T05:00:00Z"), window="month"))
        qw = quota.quota_windows(directory=self.dir, now=NOW)
        self.assertNotIn("grok", qw)

    def test_grok_staleness_and_age(self):
        # stale: true but fresh (1 day old) -> NOT dropped
        self.write(quota.GROK_FILE, grok_cache(NOW - DAY, ts("2026-10-27T05:00:00Z"), stale=True))
        qw = quota.quota_windows(directory=self.dir, now=NOW)
        self.assertIn("grok", qw)

        # stale: true and older than MAX_AGE_DAYS (15 days) -> dropped
        self.write(quota.GROK_FILE, grok_cache(NOW - 15 * DAY, ts("2026-10-27T05:00:00Z"), stale=True))
        qw = quota.quota_windows(directory=self.dir, now=NOW)
        self.assertNotIn("grok", qw)

        # stale: false and older than MAX_AGE_DAYS (15 days) -> dropped
        self.write(quota.GROK_FILE, grok_cache(NOW - 15 * DAY, ts("2026-10-27T05:00:00Z"), stale=False))
        qw = quota.quota_windows(directory=self.dir, now=NOW)
        self.assertNotIn("grok", qw)

    def test_manual_weekly_reset_and_dst(self):
        # Saturday Oct 24, 2026 at 12:00 UTC
        # Config weekly_reset = "tue 05:00" in report timezone America/New_York (EDT, UTC-4)
        # Saturday Oct 24 12:00 UTC is 08:00 EDT.
        # Next Tuesday is Oct 27 at 05:00 EDT = 09:00 UTC (2026-10-27T09:00:00Z).
        cfg = config.from_dict({"quota_windows": {"grok": {"weekly_reset": "tue 05:00"}}})
        qw = quota.quota_windows(cfg.quota_windows, directory=self.dir, now=NOW, timezone_name="America/New_York")
        self.assertEqual(qw["grok"], {
            "weekly_resets_at": "2026-10-27T09:00:00Z",
            "weekly_window_hours": 168,
            "weekly_used_percent": None,
            "five_hour_resets_at": None,
            "five_hour_window_hours": None,
            "five_hour_used_percent": None,
            "source": "manual",
        })

        # Manual beats Tokei
        self.write_all()
        qw_both = quota.quota_windows(cfg.quota_windows, directory=self.dir, now=NOW, timezone_name="America/New_York")
        self.assertEqual(qw_both["grok"]["source"], "manual")
        self.assertEqual(qw_both["claude"]["source"], "tokei")

        # DST transition test:
        # America/New_York falls back on Sunday Nov 1, 2026 (EDT UTC-4 -> EST UTC-5).
        # Suppose now is Saturday Oct 31, 2026 12:00 UTC (08:00 EDT).
        # Target weekly reset is "tue 05:00" which falls on Tuesday Nov 3, 2026 (AFTER the fallback, in EST).
        # 05:00 EST = 10:00 UTC (2026-11-03T10:00:00Z).
        now_pre_dst = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc).timestamp()
        qw_dst = quota.quota_windows(cfg.quota_windows, directory=self.dir, now=now_pre_dst, timezone_name="America/New_York")
        self.assertEqual(qw_dst["grok"]["weekly_resets_at"], "2026-11-03T10:00:00Z")
        from zoneinfo import ZoneInfo
        dt_local = datetime.fromisoformat(qw_dst["grok"]["weekly_resets_at"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        self.assertEqual((dt_local.hour, dt_local.minute), (5, 0))

        # Europe/Paris falls back on Sunday Oct 25, 2026 (CEST UTC+2 -> CET UTC+1).
        # Tuesday Oct 27 at 05:00 CET = 04:00 UTC.
        qw_paris = quota.quota_windows(cfg.quota_windows, directory=self.dir, now=NOW, timezone_name="Europe/Paris")
        self.assertEqual(qw_paris["grok"]["weekly_resets_at"], "2026-10-27T04:00:00Z")
        dt_paris = datetime.fromisoformat(qw_paris["grok"]["weekly_resets_at"].replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Paris"))
        self.assertEqual((dt_paris.hour, dt_paris.minute), (5, 0))

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
                                        "weekly_used_percent": None, "five_hour_resets_at": None,
                                        "five_hour_window_hours": None, "five_hour_used_percent": None,
                                        "source": "manual"})
        self.assertEqual(qw["codex"]["source"], "tokei")
        # manual works without Tokei, and an old anchor rolls forward to the next reset
        cfg = config.from_dict({"quota_windows": {"codex": {"weekly_resets_at": "2026-09-01T08:00:00+02:00"}}})
        qw = quota.quota_windows(cfg.quota_windows, directory=os.path.join(self.dir, "nope"), now=NOW)
        self.assertEqual(qw, {"codex": {"weekly_resets_at": "2026-10-27T06:00:00Z", "weekly_window_hours": 168,
                                        "weekly_used_percent": None, "five_hour_resets_at": None,
                                        "five_hour_window_hours": None, "five_hour_used_percent": None,
                                        "source": "manual"}})

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
                    {"claude": "2026-10-27T10:00:00Z"},
                    {"claude": {"weekly_reset": "someday 05:00"}},
                    {"claude": {"weekly_reset": "tue 25:00"}},
                    {"claude": {"weekly_reset": "tue 5:60"}},
                    {"claude": {"weekly_reset": 123}},
                    {"unknown_agent": {"weekly_reset": "tue 05:00"}}):
            with self.assertRaises(ConfigError):
                config.from_dict({"quota_windows": bad})

        # weekly_reset parsed correctly in toml
        text_wr = ('[quota_windows.grok]\n'
                   'weekly_reset = "tue 05:00"\n')
        cfg_wr = config.from_dict(config.parse_toml_subset(text_wr))
        self.assertEqual(cfg_wr.quota_windows["grok"]["weekly_reset"], "tue 05:00")

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
                           "weekly_used_percent": None, "five_hour_resets_at": None,
                                        "five_hour_window_hours": None, "five_hour_used_percent": None,
                                        "source": "manual"}})
        finally:
            shutil.rmtree(cache)


if __name__ == "__main__":
    unittest.main()
