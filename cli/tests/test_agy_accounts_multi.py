"""Tests for Antigravity multi-account daily usage, per-account plans, and last-seen quota."""

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from kanjo import cli, config, export, quota_fetch, subscriptions
from kanjo.antigravity_accounts import (
    LaunchSpan,
    compute_antigravity_accounts_window,
    compute_antigravity_by_day,
    reset_account_index,
)
from kanjo.pricing import default_book
from kanjo.sources.base import Message, Session

from tests.support import FIXTURE_DIRS, check_subscriptions, has_tz_database, validate_contract
from tests.test_agy_login import FakeAccountIndex, FakeKeychainBackend


class AgyAccountsMultiTest(unittest.TestCase):
    def setUp(self):
        reset_account_index()
        self.temp = tempfile.TemporaryDirectory(prefix="kanjo-agy-multi-")
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.config_dir = os.path.join(self.root, "config")
        self.data_dir = os.path.join(self.root, "data")
        self.cache_dir = os.path.join(self.root, "cache")
        self.tokei_dir = os.path.join(self.root, "tokei")
        for d in (self.config_dir, self.data_dir, self.cache_dir, self.tokei_dir):
            os.makedirs(d, exist_ok=True)
        self.env = mock.patch.dict(os.environ, {
            "KANJO_CONFIG_DIR": self.config_dir,
            "KANJO_DATA_DIR": self.data_dir,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_TOKEI_DIR": self.tokei_dir,
            "KANJO_CLAUDE_CONFIG": os.path.join(self.root, "no-claude.json"),
            "KANJO_CODEX_AUTH": os.path.join(self.root, "no-codex.json"),
            "KANJO_GROK_AUTH": os.path.join(self.root, "no-grok.json"),
            "KANJO_CLAUDE_DIR": FIXTURE_DIRS["claude"][0],
            "KANJO_CODEX_DIR": FIXTURE_DIRS["codex"][0],
            "KANJO_ANTIGRAVITY_DIR": FIXTURE_DIRS["antigravity"][0],
            "KANJO_NO_NETWORK": "1",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        from kanjo.agy_login import set_backend
        set_backend(FakeKeychainBackend(saved={}))

    def tearDown(self):
        from kanjo.agy_login import set_backend
        set_backend(None)
        reset_account_index()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_by_day_grouping_sorting_and_all_history(self):
        from kanjo.agy_login import set_backend

        now = datetime(2026, 11, 17, 18, 0, 0, tzinfo=timezone.utc)
        # Day 1 (20 days ago, outside 7-day window): Bob
        ts_old = datetime(2026, 10, 28, 15, 0, 0, tzinfo=timezone.utc).timestamp()
        # Day 2 (2026-11-16): Alex (2 msgs, mixed case), Bob (1 msg), Unknown (None + "unknown")
        ts_d2_a1 = datetime(2026, 11, 16, 10, 0, 0, tzinfo=timezone.utc).timestamp()
        ts_d2_a2 = datetime(2026, 11, 16, 11, 0, 0, tzinfo=timezone.utc).timestamp()
        ts_d2_b = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        ts_d2_u1 = datetime(2026, 11, 16, 13, 0, 0, tzinfo=timezone.utc).timestamp()
        ts_d2_u2 = datetime(2026, 11, 16, 14, 0, 0, tzinfo=timezone.utc).timestamp()

        m_old = Message(ts=ts_old, model="gemini-2.5-pro", input=100, output=50, key="k-old", account="bob@example.com")
        m_a1 = Message(ts=ts_d2_a1, model="gemini-2.5-pro", input=200, output=100, key="k-a1", account="Alex@example.com")
        m_a2 = Message(ts=ts_d2_a2, model="gemini-2.5-flash", input=300, output=100, key="k-a2", account="alex@example.com")
        m_a2_dup = Message(ts=ts_d2_a2, model="gemini-2.5-flash", input=300, output=100, key="k-a2", account="alex@example.com")
        m_b = Message(ts=ts_d2_b, model="gemini-2.5-pro", input=400, output=100, key="k-b", account="bob@example.com")
        m_u1 = Message(ts=ts_d2_u1, model="gemini-2.5-flash", input=50, output=50, key="k-u1", account=None)
        m_u2 = Message(ts=ts_d2_u2, model="gemini-2.5-flash", input=60, output=40, key="k-u2", account="unknown")

        s1 = Session(id="ag-1", agent="antigravity", file="/tmp/1.db", cwd="/repo",
                     messages=[m_old, m_a1, m_a2, m_b, m_u1, m_u2])
        s2 = Session(id="ag-2", agent="antigravity", file="/tmp/2.db", cwd="/repo",
                     messages=[m_a2_dup])
        # Non-antigravity session must be ignored
        s_claude = Session(id="cl-1", agent="claude", file="/tmp/cl.jsonl", cwd="/repo",
                           messages=[Message(ts=ts_d2_a1, model="claude-sonnet-4-5", input=9999, output=9999, key="cl-1")])

        scan_res = export.ScanResult(sessions=[s1, s2, s_claude], failed_files=[], stats={})
        backend = FakeKeychainBackend(saved={"alex@example.com": b"tok"})
        set_backend(backend)
        fake_idx = FakeAccountIndex(
            spans=[LaunchSpan(path="cli-1.log", start=ts_d2_a1 - 60, end=ts_d2_a2 + 60, emails={"alex@example.com"})],
            current="alex@example.com",
        )

        with mock.patch("kanjo.antigravity_accounts.get_account_index", return_value=fake_idx):
            with mock.patch.dict(os.environ, {"TZ": "UTC"}):
                doc = export.build_export(scan_result=scan_res, now=now)

        validate_contract(self, doc)
        agy = doc["antigravity_accounts"]
        by_day = agy["by_day"]

        expected_keys = [(r["day"], r["email"]) for r in by_day]
        self.assertEqual(expected_keys, [
            ("2026-10-28", "bob@example.com"),
            ("2026-11-16", "alex@example.com"),
            ("2026-11-16", "bob@example.com"),
            ("2026-11-16", None),
        ])
        self.assertEqual(by_day[0]["tokens"], 150)
        self.assertEqual(by_day[0]["messages"], 1)
        # Deduped: k-a2 counted once -> 200+100 + 300+100 = 700
        self.assertEqual(by_day[1]["tokens"], 700)
        self.assertEqual(by_day[1]["messages"], 2)
        self.assertGreater(by_day[1]["cost_usd"], 0.0)
        self.assertEqual(by_day[2]["tokens"], 500)
        self.assertEqual(by_day[2]["messages"], 1)
        # Null bucket combines None + "unknown"
        self.assertEqual(by_day[3]["tokens"], 200)
        self.assertEqual(by_day[3]["messages"], 2)

        # compute_antigravity_accounts_window returns matching by_day
        computed = compute_antigravity_accounts_window(
            [s1, s2, s_claude],
            {"timezone": "UTC"},
            now=now,
            current_account="alex@example.com",
        )
        self.assertEqual(computed["by_day"], by_day)

    @unittest.skipUnless(has_tz_database("Asia/Shanghai"), "needs tzdata for Asia/Shanghai")
    def test_by_day_uses_report_timezone(self):
        # 2026-11-16 18:00 UTC is 2026-11-17 02:00 in Asia/Shanghai
        ts = datetime(2026, 11, 16, 18, 0, 0, tzinfo=timezone.utc).timestamp()
        s = Session(id="ag-tz", agent="antigravity", file="/tmp/tz.db",
                    messages=[Message(ts=ts, model="gemini-2.5-pro", input=100, output=50, account="alex@example.com")])
        rows = compute_antigravity_by_day([s], tz_name="Asia/Shanghai", prices=default_book())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["day"], "2026-11-17")

    def test_per_account_plan_config_set_get_unset_toml_and_validation(self):
        key_plan = "antigravity_accounts.alex@example.com.plan"
        key_price = "antigravity_accounts.alex@example.com.monthly_price_usd"

        self.assertEqual(self.run_cli("config", "get", key_plan), (0, f"{key_plan} = unset (default)\n", ""))
        self.assertEqual(self.run_cli("config", "get", key_price), (0, f"{key_price} = unset (default)\n", ""))

        # Set plan -> fills known price
        self.assertEqual(
            self.run_cli("config", "set", key_plan, "google_ai_ultra"),
            (0, f'{key_plan} = "google_ai_ultra" (overrides)\n', ""),
        )
        self.assertEqual(
            self.run_cli("config", "get", key_plan),
            (0, f'{key_plan} = "google_ai_ultra" (overrides)\n', ""),
        )
        self.assertEqual(
            self.run_cli("config", "get", key_price),
            (0, f"{key_price} = 249.99 (overrides)\n", ""),
        )

        # Override price
        self.assertEqual(
            self.run_cli("config", "set", key_price, "199"),
            (0, f"{key_price} = 199.0 (overrides)\n", ""),
        )
        self.assertEqual(
            self.run_cli("config", "get", key_price),
            (0, f"{key_price} = 199.0 (overrides)\n", ""),
        )

        # "none" is allowed
        bob_plan = "antigravity_accounts.bob@example.com.plan"
        bob_price = "antigravity_accounts.bob@example.com.monthly_price_usd"
        self.assertEqual(
            self.run_cli("config", "set", bob_plan, "none"),
            (0, f'{bob_plan} = "none" (overrides)\n', ""),
        )
        self.assertEqual(self.run_cli("config", "get", bob_price), (0, f"{bob_price} = unset (overrides)\n", ""))

        # Unset falls back to TOML when present
        toml_path = os.path.join(self.config_dir, "attribution.toml")
        with open(toml_path, "w", encoding="utf-8") as handle:
            handle.write('[antigravity_accounts."alex@example.com"]\nplan = "google_ai_pro"\n')
        self.assertEqual(self.run_cli("config", "unset", key_price), (0, f"{key_price} = 249.99 (overrides)\n", ""))
        self.assertEqual(self.run_cli("config", "unset", key_plan), (0, f'{key_plan} = "google_ai_pro" (toml)\n', ""))
        self.assertEqual(self.run_cli("config", "unset", bob_plan), (0, f"{bob_plan} = unset (default)\n", ""))

        # overrides.json cleaned up when empty
        overrides_path = os.path.join(self.config_dir, "overrides.json")
        with open(overrides_path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {})
        os.unlink(toml_path)
        os.unlink(overrides_path)

        # Validation errors never write overrides.json
        for args in (
            ("set", key_plan, "bogus_plan"),
            ("set", key_plan, "max_5x"),
            ("set", key_plan, ""),
            ("set", key_price, "-1"),
            ("set", key_price, "nan"),
            ("set", key_price, "free"),
            ("set", "antigravity_accounts.notanemail.plan", "google_ai_pro"),
            ("set", "antigravity_accounts.alex@example.com.badfield", "google_ai_pro"),
            ("set", "antigravity_accounts.alex@example.com", "google_ai_pro"),
            ("get", "antigravity_accounts.notanemail.plan"),
            ("unset", "antigravity_accounts.alex@example.com.bad"),
        ):
            code, out, err = self.run_cli("config", *args)
            self.assertEqual((code, out), (2, ""), (args, err))
            self.assertTrue(len(err.strip()) > 0)
            self.assertFalse(os.path.exists(overrides_path))

    def test_subscriptions_sum_label_accounts_priced_and_account_plan_field(self):
        now = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
        cfg = config.from_dict({
            "subscriptions": {"antigravity": {"anchor_day": 15}},
            "antigravity_accounts": {
                "alex@example.com": {"plan": "google_ai_ultra"},
                "charlie@example.com": {"plan": "google_ai_ultra"},
                "bob@example.com": {"plan": "google_ai_pro"},
                "free@example.com": {"plan": "none"},
            },
        })
        subs = subscriptions.subscriptions(
            cfg.subscriptions,
            directory=self.tokei_dir,
            now=now,
            timezone_name="UTC",
            antigravity_accounts=cfg.antigravity_accounts,
        )
        check_subscriptions(self, subs)
        agy_sub = subs["antigravity"]
        self.assertEqual(agy_sub["monthly_price_usd"], 519.97)
        self.assertEqual(agy_sub["plan_label"], "Google AI Ultra \u00d72 + Google AI Pro")
        self.assertEqual(agy_sub["accounts_priced"], 3)
        self.assertEqual(agy_sub["anchor_day"], 15)
        self.assertEqual(agy_sub["cycle_source"], "manual")
        self.assertEqual(agy_sub["source"], "manual")

        # Single account plan keeps its exact plan key and label without "×1"
        cfg_one = config.from_dict({
            "antigravity_accounts": {"alex@example.com": {"plan": "google_ai_pro", "monthly_price_usd": 15.0}},
        })
        subs_one = subscriptions.subscriptions(
            cfg_one.subscriptions,
            directory=self.tokei_dir,
            now=now,
            timezone_name="UTC",
            antigravity_accounts=cfg_one.antigravity_accounts,
        )
        check_subscriptions(self, subs_one)
        self.assertEqual(subs_one["antigravity"]["plan"], "google_ai_pro")
        self.assertEqual(subs_one["antigravity"]["plan_label"], "Google AI Pro")
        self.assertEqual(subs_one["antigravity"]["monthly_price_usd"], 15.0)
        self.assertEqual(subs_one["antigravity"]["accounts_priced"], 1)

        # Export emits "plan" on configured accounts (not on "none" or unconfigured)
        ts = now.timestamp() - 600
        s = Session(
            id="ag-plan",
            agent="antigravity",
            file="/tmp/plan.db",
            cwd="/repo",
            messages=[
                Message(ts=ts, model="gemini-2.5-pro", input=100, output=50, account="alex@example.com"),
                Message(ts=ts, model="gemini-2.5-pro", input=80, output=40, account="bob@example.com"),
                Message(ts=ts, model="gemini-2.5-pro", input=60, output=30, account="free@example.com"),
                Message(ts=ts, model="gemini-2.5-pro", input=40, output=20, account="unconfigured@example.com"),
            ],
        )
        scan_res = export.ScanResult(sessions=[s], failed_files=[], stats={})
        fake_idx = FakeAccountIndex(
            spans=[LaunchSpan(path="cli-1.log", start=ts - 60, end=ts + 60, emails={"alex@example.com"})],
            current="alex@example.com",
        )
        with mock.patch("kanjo.antigravity_accounts.get_account_index", return_value=fake_idx):
            doc = export.build_export(config=cfg, scan_result=scan_res, now=now)

        validate_contract(self, doc)
        by_email = {a["email"]: a for a in doc["antigravity_accounts"]["accounts"]}
        self.assertEqual(by_email["alex@example.com"]["plan"], {
            "plan": "google_ai_ultra",
            "plan_label": "Google AI Ultra",
            "monthly_price_usd": 249.99,
        })
        self.assertEqual(by_email["bob@example.com"]["plan"], {
            "plan": "google_ai_pro",
            "plan_label": "Google AI Pro",
            "monthly_price_usd": 19.99,
        })
        self.assertNotIn("plan", by_email["free@example.com"])
        self.assertNotIn("plan", by_email["unconfigured@example.com"])

    def test_unchanged_output_when_no_per_account_plans(self):
        now = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
        # Empty antigravity_accounts or only "none" -> identical to no per-account config
        subs_plain = subscriptions.subscriptions({}, directory=self.tokei_dir, now=now, timezone_name="UTC")
        subs_none = subscriptions.subscriptions(
            {},
            directory=self.tokei_dir,
            now=now,
            timezone_name="UTC",
            antigravity_accounts={"alex@example.com": {"plan": "none"}},
        )
        self.assertEqual(subs_plain, subs_none)
        self.assertNotIn("antigravity", subs_none)

        # When [subscriptions.antigravity] is configured alone, no accounts_priced key
        subs_manual = subscriptions.subscriptions(
            {"antigravity": {"plan": "google_ai_pro"}},
            directory=self.tokei_dir,
            now=now,
            timezone_name="UTC",
            antigravity_accounts={"alex@example.com": {"plan": "none"}},
        )
        self.assertNotIn("accounts_priced", subs_manual["antigravity"])
        self.assertEqual(subs_manual["antigravity"]["plan_label"], "Google AI Pro")

    def test_quota_recording_and_ended_windows_in_export(self):
        t0 = datetime(2026, 11, 17, 18, 0, 0, tzinfo=timezone.utc).timestamp()
        t1 = t0 + 3600  # 1 hour later
        t2 = t0 + 6 * 3600  # 6 hours later (5h window from t0 has ended, weekly still active)

        def make_summary(now_ts, weekly_used, five_used, extra_used):
            return {
                "groups": [
                    {
                        "displayName": "Gemini Models",
                        "buckets": [
                            {
                                "window": "weekly",
                                "remainingFraction": 1.0 - (weekly_used / 100.0),
                                "resetTime": now_ts + 5 * 86400,
                                "windowMinutes": 10080,
                            },
                            {
                                "window": "5h",
                                "remainingFraction": 1.0 - (five_used / 100.0),
                                "resetTime": now_ts + 7200,
                                "windowMinutes": 300,
                            },
                        ],
                    },
                    {
                        "displayName": "Claude and GPT Models",
                        "buckets": [
                            {
                                "bucketId": "3p-weekly",
                                "displayName": "Weekly Limit Remaining",
                                "remainingFraction": 1.0 - (extra_used / 100.0),
                                "resetTime": now_ts + 5 * 86400,
                                "windowMinutes": 10080,
                            },
                        ],
                    },
                ]
            }

        class _FakeHTTPResp:
            def __init__(self, payload):
                self._raw = json.dumps(payload).encode("utf-8")

            def read(self, _n=-1):
                return self._raw

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen_factory(summary_payload, status_payload=None):
            def _open(req, timeout=3, context=None):
                if "GetUserStatus" in req.full_url:
                    return _FakeHTTPResp(status_payload or {"userTier": {"name": "Google AI Ultra"}})
                return _FakeHTTPResp(summary_payload)
            return _open

        quota_file = quota_fetch.antigravity_account_quota_path()

        with mock.patch.dict(os.environ, {"KANJO_NO_NETWORK": "0"}):
            with mock.patch.object(quota_fetch, "_find_antigravity_processes", return_value=[{"pid": 1, "csrf_token": "tok", "port": 12345}]), \
                 mock.patch.object(quota_fetch, "_antigravity_ports", return_value=[12345]):

                # 1. Current account is unknown -> never record
                with mock.patch("kanjo.antigravity_accounts.get_account_index", return_value=FakeAccountIndex(current=None)):
                    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen_factory(make_summary(t0, 10.0, 20.0, 5.0))):
                        res = quota_fetch.fetch_antigravity_quota(now=t0)
                self.assertIsNotNone(res)
                self.assertFalse(os.path.exists(quota_file))

                # 2. Current account is alex@example.com -> recorded under alex
                with mock.patch("kanjo.antigravity_accounts.get_account_index", return_value=FakeAccountIndex(current="Alex@example.com")):
                    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen_factory(make_summary(t0, 10.0, 26.0, 15.0))):
                        res_alex = quota_fetch.fetch_antigravity_quota(now=t0)
                self.assertIsNotNone(res_alex)
                self.assertTrue(os.path.exists(quota_file))
                if os.name != "nt":
                    self.assertEqual(stat.S_IMODE(os.stat(quota_file).st_mode), 0o600)

                # 3. Switch to bob@example.com -> recorded under bob via fetch_all_quotas, alex preserved
                with mock.patch("kanjo.antigravity_accounts.get_account_index", return_value=FakeAccountIndex(current="bob@example.com")):
                    with mock.patch.dict(quota_fetch.FETCHERS, {
                        "antigravity": lambda now: quota_fetch.parse_antigravity_summary(make_summary(t1, 40.0, 55.0, 12.0), now=now),
                        "codex": lambda now: None,
                        "claude": lambda now: None,
                        "grok": lambda now: None,
                    }):
                        # Force cache miss by removing quota_cache if any
                        if os.path.exists(quota_fetch.quota_cache_path()):
                            os.unlink(quota_fetch.quota_cache_path())
                        quota_fetch.fetch_all_quotas(now=t1, no_network=False)

                # 4. Update bob again -> keeps one latest reading per email
                with mock.patch("kanjo.antigravity_accounts.get_account_index", return_value=FakeAccountIndex(current="bob@example.com")):
                    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen_factory(make_summary(t1 + 60, 42.0, 60.0, 14.0))):
                        quota_fetch.fetch_antigravity_quota(now=t1 + 60)

        with open(quota_file, "r", encoding="utf-8") as f:
            raw_saved = json.load(f)
        self.assertEqual(sorted(raw_saved["accounts"].keys()), ["alex@example.com", "bob@example.com"])

        # Export at t2:
        # - alex's 5-hour window (t0 + 7200) <= t2 (t0 + 21600) -> used_percent is None!
        # - alex's weekly & 3p-weekly (t0 + 5d) > t2 -> used_percent kept (10.0, 15.0)
        # - bob's 5-hour window (t1 + 60 + 7200 = t0 + 10860) <= t2 -> used_percent is None!
        # - bob's weekly & 3p-weekly (t1 + 60 + 5d) > t2 -> used_percent kept (42.0, 14.0)
        # - charlie has no quota reading -> no "quota" key
        s = Session(
            id="ag-q",
            agent="antigravity",
            file="/tmp/q.db",
            cwd="/repo",
            messages=[
                Message(ts=t0, model="gemini-2.5-pro", input=300, output=100, account="alex@example.com"),
                Message(ts=t1, model="gemini-2.5-pro", input=200, output=100, account="bob@example.com"),
                Message(ts=t1, model="gemini-2.5-pro", input=100, output=50, account="charlie@example.com"),
            ],
        )
        scan_res = export.ScanResult(sessions=[s], failed_files=[], stats={})
        fake_idx = FakeAccountIndex(
            spans=[LaunchSpan(path="cli-1.log", start=t1, end=t2, emails={"bob@example.com"})],
            current="bob@example.com",
        )
        with mock.patch("kanjo.antigravity_accounts.get_account_index", return_value=fake_idx):
            doc = export.build_export(scan_result=scan_res, now=datetime.fromtimestamp(t2, tz=timezone.utc))

        validate_contract(self, doc)
        by_email = {a["email"]: a for a in doc["antigravity_accounts"]["accounts"]}

        alex_q = by_email["alex@example.com"]["quota"]
        self.assertEqual(alex_q["captured_at"], "2026-11-17T18:00:00Z")
        alex_w = {w["id"]: w for w in alex_q["windows"]}
        self.assertEqual(alex_w["weekly"]["used_percent"], 10.0)
        self.assertIsNone(alex_w["five_hour"]["used_percent"])
        self.assertEqual(alex_w["five_hour"]["window_hours"], 5)
        self.assertEqual(alex_w["3p-weekly"]["used_percent"], 15.0)
        self.assertEqual(alex_w["3p-weekly"]["title"], "Claude/GPT weekly")

        bob_q = by_email["bob@example.com"]["quota"]
        bob_w = {w["id"]: w for w in bob_q["windows"]}
        self.assertEqual(bob_w["weekly"]["used_percent"], 42.0)
        self.assertIsNone(bob_w["five_hour"]["used_percent"])
        self.assertEqual(bob_w["3p-weekly"]["used_percent"], 14.0)

        self.assertNotIn("quota", by_email["charlie@example.com"])

    def test_fields_absent_in_mobile_family_public(self):
        now = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
        now_ts = now.timestamp()
        cfg = config.from_dict({
            "antigravity_accounts": {
                "alex@example.com": {"plan": "google_ai_ultra"},
                "bob@example.com": {"plan": "google_ai_pro"},
            },
        })
        fake_idx = FakeAccountIndex(
            spans=[LaunchSpan(path="cli-1.log", start=now_ts - 600, end=now_ts, emails={"alex@example.com"})],
            current="alex@example.com",
        )
        with mock.patch("kanjo.antigravity_accounts.get_account_index", return_value=fake_idx):
            quota_fetch.record_antigravity_account_quota({
                "weekly_resets_at": "2026-11-24T12:00:00Z",
                "weekly_window_hours": 168,
                "weekly_used_percent": 15.0,
                "five_hour_resets_at": "2026-11-17T15:00:00Z",
                "five_hour_window_hours": 5,
                "five_hour_used_percent": 20.0,
            }, now=now_ts)

        s = Session(
            id="ag-priv",
            agent="antigravity",
            file="/tmp/priv.db",
            cwd="/repo",
            messages=[
                Message(ts=now_ts - 300, model="gemini-2.5-pro", input=500, output=200, account="alex@example.com"),
            ],
        )
        scan_res = export.ScanResult(sessions=[s], failed_files=[], stats={})

        with mock.patch("kanjo.antigravity_accounts.get_account_index", return_value=fake_idx):
            full = export.build_export(config=cfg, scan_result=scan_res, now=now)
            mob = export.mobile_document(full)
            fam = export.build_family_report(config=cfg, scan_result=scan_res, now=now)
            pub = export.build_public_summary(config=cfg, scan_result=scan_res, now=now)

        self.assertIn("antigravity_accounts", full)
        self.assertIn("by_day", full["antigravity_accounts"])
        self.assertIn("plan", full["antigravity_accounts"]["accounts"][0])
        self.assertIn("quota", full["antigravity_accounts"]["accounts"][0])
        self.assertEqual(full["subscriptions"]["antigravity"]["accounts_priced"], 2)

        self.assertNotIn("antigravity_accounts", mob)
        self.assertNotIn("antigravity_accounts", fam)
        self.assertEqual(fam["plans"]["antigravity"], "Google AI Ultra + Google AI Pro")
        self.assertNotIn("@", json.dumps(fam))
        self.assertNotIn("antigravity_accounts", pub)
        self.assertNotIn("subscriptions", pub)
        self.assertNotIn("@", json.dumps(pub))


if __name__ == "__main__":
    unittest.main()
