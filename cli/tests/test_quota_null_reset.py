"""A provider that reports no weekly reset must never yield weekly_resets_at: null (CONTRACT.md §2)."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from kanjo import export, quota, quota_fetch
from kanjo.config import Config
from tests.support import ALICE, FIXTURE_DIRS, FIXTURES, standard_fs

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def live_entries(now: float) -> dict:
    claude = quota_fetch.parse_claude_usage(  # what Claude returns after a week idle
        {"five_hour": {"utilization": 0.0, "resets_at": None},
         "seven_day": {"utilization": 0.0, "resets_at": None}}, now)
    codex = quota_fetch.parse_codex_usage(  # an account with only a primary (5h) window
        {"rate_limit": {"primary_window": {"used_percent": 12, "reset_after_seconds": 3600}}}, now)
    grok = quota_fetch.parse_grok_usage(  # creditUsagePercent but no period end
        {"config": {"creditUsagePercent": 40}}, now)
    for entry in (claude, codex, grok):
        assert entry is not None and entry["weekly_resets_at"] is None
    valid = {"weekly_resets_at": "2026-11-25T00:00:00Z", "weekly_window_hours": 168,
             "weekly_used_percent": 10, "source": "live"}
    return {"claude": claude, "codex": codex, "grok": grok, "antigravity": valid}


class NullWeeklyResetTest(unittest.TestCase):
    def setUp(self):
        self.tokei = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tokei, ignore_errors=True))

    def assert_no_null_reset(self, windows: dict):
        for agent, entry in windows.items():
            self.assertIsInstance(entry.get("weekly_resets_at"), str, agent)
        self.assertEqual(sorted(windows), ["antigravity"])

    def test_quota_windows_drops_live_entries_without_weekly_reset(self):
        now = NOW.timestamp()
        with mock.patch.object(quota_fetch, "fetch_all_quotas", return_value=live_entries(now)), \
                mock.patch.dict(quota.TOKEI_READERS, {}, clear=True):
            self.assert_no_null_reset(quota.quota_windows(directory=self.tokei, now=now))

    def test_tokei_entry_survives_a_live_entry_without_weekly_reset(self):
        now = NOW.timestamp()
        tokei_entry = quota.window(now + 3600, 168, None, "tokei", now)
        with mock.patch.object(quota_fetch, "fetch_all_quotas", return_value=live_entries(now)), \
                mock.patch.dict(quota.TOKEI_READERS, {"claude": lambda d, n: tokei_entry}, clear=True):
            windows = quota.quota_windows(directory=self.tokei, now=now)
        self.assertEqual(windows["claude"]["source"], "tokei")
        self.assertNotIn("codex", windows)

    def test_export_mobile_and_family_never_carry_null_weekly_reset(self):
        fs = standard_fs()
        self.addCleanup(fs.cleanup)
        now = NOW.timestamp()
        with mock.patch.object(quota_fetch, "fetch_all_quotas", return_value=live_entries(now)), \
                mock.patch.dict(quota.TOKEI_READERS, {}, clear=True), \
                mock.patch("kanjo.export.build_device_info",
                           return_value={"id": "0123456789abcdef", "name": "device", "os": "macos"}), \
                mock.patch("kanjo.export.load_subscriptions", return_value={}), \
                mock.patch("kanjo.antigravity_accounts.get_account_index", side_effect=RuntimeError):
            full = export.build_export(dirs=FIXTURE_DIRS, fs_root=fs.root, home=ALICE, now=NOW,
                                       tokei_dir=self.tokei)
            mobile = export.mobile_document(full)
            family = export.build_family_report(config=Config(family_agents="all"), dirs=FIXTURE_DIRS,
                                                fs_root=fs.root, home=ALICE, now=NOW,
                                                tokei_dir=self.tokei)
        for doc in (full, mobile, family):
            self.assert_no_null_reset(doc["quota_windows"])
            self.assertNotIn('"weekly_resets_at": null', json.dumps(doc))

    def test_private_quota_windows_drops_entries_without_weekly_reset(self):
        windows = {"claude": {"weekly_resets_at": None, "source": "live"},
                   "codex": {"weekly_resets_at": "2026-11-25T00:00:00Z", "source": "live"}}
        self.assertEqual(sorted(export.private_quota_windows(windows)), ["codex"])

    def test_cached_doc_from_older_build_is_cleaned_on_load(self):
        cdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(cdir, ignore_errors=True))
        doc = {"quota_windows": {"claude": {"weekly_resets_at": None},
                                 "codex": {"weekly_resets_at": "2026-11-25T00:00:00Z"}}}
        export.save_fast_export("fp", doc, directory=cdir, now=1000)
        loaded = export.load_fast_export("fp", directory=cdir, now=1001)
        self.assertEqual(sorted(loaded["quota_windows"]), ["codex"])


if __name__ == "__main__":
    unittest.main()
