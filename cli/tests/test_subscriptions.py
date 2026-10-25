"""subscriptions: Claude config, Codex cache, manual plans, billing cycles."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from kanjo import cli, config, quota
from kanjo.config import ConfigError
from kanjo.export import build_export, check_invariants
from kanjo.subscriptions import subscriptions

from tests.support import ALICE, FIXTURE_DIRS, check_subscriptions, standard_fs, validate_contract

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
DAY = 86400

KNOWN = [
    ("claude", "max_20x", "Claude Max 20x", 200.0),
    ("claude", "max_5x", "Claude Max 5x", 100.0),
    ("claude", "pro", "Claude Pro", 20.0),
    ("codex", "free", "ChatGPT Free", 0.0),
    ("codex", "go", "ChatGPT Go", 8.0),
    ("codex", "plus", "ChatGPT Plus", 20.0),
    ("codex", "pro", "ChatGPT Pro", 200.0),
    ("codex", "team", "ChatGPT Team", 30.0),
    ("codex", "business", "ChatGPT Business", 30.0),
    ("antigravity", "google_ai_pro", "Google AI Pro", 19.99),
    ("antigravity", "google_ai_ultra", "Google AI Ultra", 249.99),
]


class SubscriptionTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kanjo-subs-")
        self.claude_path = os.path.join(self.dir, "claude.json")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def collect(self, manual=None, now=None, tz="UTC"):
        return subscriptions(manual, directory=self.dir, claude_config=self.claude_path,
                             now=NOW if now is None else now, timezone_name=tz)

    def write_claude(self, tier="default_claude_max_5x", created="2026-09-25T18:33:26.854830123Z",
                     billing="stripe_subscription", extra=False, user_tier=None,
                     drop_created=False, drop_oauth=False, drop_extra=False):
        account = {
            "billingType": billing,
            "organizationRateLimitTier": tier,
            "userRateLimitTier": user_tier,
        }
        if not drop_created:
            account["subscriptionCreatedAt"] = created
        if not drop_extra:
            account["hasExtraUsageEnabled"] = extra
        payload = {} if drop_oauth else {"oauthAccount": account}
        with open(self.claude_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def write_codex(self, plan="plus", fetched=None, plan_type=None, include_plan=True):
        data = {"fetched_at": NOW.timestamp() if fetched is None else fetched, "limits": {}}
        if include_plan:
            data["plan"] = plan
        if plan_type is not None:
            data["limits"]["plan_type"] = plan_type
        with open(os.path.join(self.dir, quota.CODEX_FILE), "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def test_claude_known_tiers(self):
        for tier, plan, label, price in (
                ("default_claude_max_5x", "max_5x", "Claude Max 5x", 100.0),
                ("default_claude_max_20x", "max_20x", "Claude Max 20x", 200.0),
                ("default_claude_pro", "pro", "Claude Pro", 20.0),
                ("default_claude_max_20x_pro", "max_20x", "Claude Max 20x", 200.0)):
            self.write_claude(tier=tier, extra=True)
            sub = self.collect()["claude"]
            self.assertEqual(sub["plan"], plan)
            self.assertEqual(sub["plan_label"], label)
            self.assertEqual(sub["monthly_price_usd"], price)
            self.assertTrue(sub["extra_usage_enabled"])
            self.assertEqual(sub["source"], "detected")
            self.assertEqual(sub["anchor_day"], 25)
            self.assertEqual(sub["cycle_source"], "subscription_date")
            # 9 fractional digits still parse; Sep 25 has not come around again on Oct 24
            self.assertEqual(sub["cycle_start"], "2026-09-25T00:00:00Z")
            self.assertEqual(sub["cycle_end"], "2026-10-25T00:00:00Z")
            check_subscriptions(self, self.collect())

    def test_user_tier_overrides_organization_tier(self):
        self.write_claude(tier="default_claude_max_5x", user_tier="default_claude_max_20x")
        sub = self.collect()["claude"]
        self.assertEqual(sub["plan"], "max_20x")
        self.assertEqual(sub["monthly_price_usd"], 200.0)
        # null user tier keeps the organization tier, including a real-file-shaped null
        self.write_claude(tier="default_claude_max_5x", user_tier=None)
        self.assertEqual(self.collect()["claude"]["plan"], "max_5x")

    def test_unknown_tier_keeps_raw_plan_and_null_price(self):
        self.write_claude(tier="default_claude_enterprise")
        sub = self.collect()["claude"]
        self.assertEqual(sub["plan"], "default_claude_enterprise")
        self.assertEqual(sub["plan_label"], "Claude (default_claude_enterprise)")
        self.assertIsNone(sub["monthly_price_usd"])
        check_subscriptions(self, {"claude": sub})

    def test_missing_subscription_date_uses_rolling_30d(self):
        self.write_claude(drop_created=True, drop_extra=True)
        sub = self.collect()["claude"]
        self.assertIsNone(sub["anchor_day"])
        self.assertEqual(sub["cycle_source"], "rolling_30d")
        self.assertFalse(sub["extra_usage_enabled"])
        self.assertEqual(sub["cycle_start"], "2026-09-24T12:00:00Z")
        self.assertEqual(sub["cycle_end"], "2026-10-24T12:00:00Z")
        check_subscriptions(self, {"claude": sub})
        # day-of-month is the timestamp's own calendar, not the UTC day
        self.write_claude(created="2026-08-31T23:30:00-04:00")
        sub = self.collect()["claude"]
        self.assertEqual(sub["anchor_day"], 31)
        self.assertEqual(sub["cycle_source"], "subscription_date")

    def test_invalid_subscription_date_uses_rolling_30d(self):
        for created in (None, "", "not a date", "2026-02-30T00:00:00Z", 123):
            with self.subTest(created=created):
                self.write_claude(created=created)
                sub = self.collect()["claude"]
                self.assertIsNone(sub["anchor_day"])
                self.assertEqual(sub["cycle_source"], "rolling_30d")
                self.assertEqual(sub["cycle_start"], "2026-09-24T12:00:00Z")
                self.assertEqual(sub["cycle_end"], "2026-10-24T12:00:00Z")
                check_subscriptions(self, {"claude": sub})

    def test_rolling_window_preserves_time_across_dst_and_month_boundaries(self):
        self.write_claude(drop_created=True)
        for now, start, end in (
                (datetime(2026, 11, 15, 12, 34, 56, tzinfo=ZoneInfo("America/Montreal")),
                 "2026-10-16T17:34:56Z", "2026-11-15T17:34:56Z"),
                (datetime(2024, 3, 1, 9, 15, 42, tzinfo=timezone.utc),
                 "2024-01-31T09:15:42Z", "2024-03-01T09:15:42Z"),
                (datetime(2026, 1, 10, 23, 59, 59),
                 "2025-12-11T23:59:59Z", "2026-01-10T23:59:59Z")):
            for tz in ("UTC", "Asia/Shanghai", "America/Montreal"):
                with self.subTest(now=now, tz=tz):
                    self.write_codex(fetched=now.timestamp())
                    for sub in self.collect(now=now, tz=tz).values():
                        self.assertIsNone(sub["anchor_day"])
                        self.assertEqual(sub["cycle_source"], "rolling_30d")
                        self.assertEqual(sub["cycle_start"], start)
                        self.assertEqual(sub["cycle_end"], end)
                        check_subscriptions(self, {"agent": sub})

    def test_claude_absent_without_a_subscription(self):
        self.assertEqual(self.collect(), {})
        with open(self.claude_path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(self.collect(), {})
        self.write_claude(drop_oauth=True)
        self.assertEqual(self.collect(), {})
        for billing in ("prepaid", "TeamSubscription", None):
            self.write_claude(billing=billing)
            self.assertEqual(self.collect(), {}, billing)
        self.write_claude(tier=None)
        self.assertNotIn("claude", self.collect())

    def test_codex_plus_unknown_and_stale(self):
        self.write_codex(plan="plus")
        sub = self.collect()["codex"]
        self.assertEqual((sub["plan"], sub["plan_label"], sub["monthly_price_usd"]),
                         ("plus", "ChatGPT Plus", 20.0))
        self.assertIsNone(sub["anchor_day"])
        self.assertEqual(sub["cycle_source"], "rolling_30d")
        self.assertFalse(sub["extra_usage_enabled"])
        self.assertEqual(sub["source"], "detected")
        self.assertEqual(sub["cycle_start"], "2026-09-24T12:00:00Z")
        # top-level plan wins over limits.plan_type; plan_type is the fallback
        self.write_codex(plan="plus", plan_type="team")
        self.assertEqual(self.collect()["codex"]["plan"], "plus")
        self.write_codex(include_plan=False, plan_type="team")
        sub = self.collect()["codex"]
        self.assertEqual((sub["plan"], sub["plan_label"], sub["monthly_price_usd"]),
                         ("team", "ChatGPT Team", 30.0))
        self.write_codex(plan="enterprise")
        sub = self.collect()["codex"]
        self.assertEqual(sub["plan"], "enterprise")
        self.assertEqual(sub["plan_label"], "ChatGPT (enterprise)")
        self.assertIsNone(sub["monthly_price_usd"])
        self.write_codex(plan="plus", fetched=NOW.timestamp() - 15 * DAY)
        self.assertNotIn("codex", self.collect())
        self.write_codex(plan="plus", fetched=NOW.timestamp() - 13 * DAY)
        self.assertEqual(self.collect()["codex"]["plan"], "plus")

    def test_codex_stale_mtime_when_fetched_at_missing(self):
        self.write_codex(plan="go")
        path = os.path.join(self.dir, quota.CODEX_FILE)
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        del data["fetched_at"]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        old = NOW.timestamp() - 15 * DAY
        os.utime(path, (old, old))
        self.assertNotIn("codex", self.collect())
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))
        self.assertEqual(self.collect()["codex"]["plan_label"], "ChatGPT Go")

    def test_known_plans_fill_in_price_and_label(self):
        for agent, plan, label, price in KNOWN:
            found = self.collect(config.from_dict({"subscriptions": {agent: {"plan": plan}}}).subscriptions)
            self.assertEqual(set(found), {agent})
            sub = found[agent]
            self.assertEqual((sub["plan"], sub["plan_label"], sub["monthly_price_usd"], sub["source"]),
                             (plan, label, price, "manual"))
            self.assertEqual(sub["cycle_source"], "rolling_30d")
            self.assertIsNone(sub["anchor_day"])
            self.assertFalse(sub["extra_usage_enabled"])
            check_subscriptions(self, found)

    def test_manual_overrides_detection(self):
        self.write_claude(extra=True)
        self.write_codex(plan="plus")
        manual = config.from_dict({"subscriptions": {"claude": {
            "plan": "max_20x", "monthly_price_usd": 150, "anchor_day": 8,
        }}}).subscriptions
        found = self.collect(manual)
        self.assertEqual(set(found), {"claude", "codex"})
        claude = found["claude"]
        self.assertEqual(claude["plan"], "max_20x")
        self.assertEqual(claude["plan_label"], "Claude Max 20x")
        self.assertEqual(claude["monthly_price_usd"], 150.0)
        self.assertEqual(claude["anchor_day"], 8)
        self.assertEqual(claude["cycle_source"], "manual")
        self.assertEqual(claude["source"], "manual")
        self.assertTrue(claude["extra_usage_enabled"])
        self.assertEqual(claude["cycle_start"], "2026-10-08T00:00:00Z")
        self.assertEqual(claude["cycle_end"], "2026-11-08T00:00:00Z")
        self.assertEqual(found["codex"]["source"], "detected")
        self.assertEqual(found["codex"]["plan"], "plus")

    def test_antigravity_is_manual_only(self):
        self.write_claude()
        self.write_codex()
        self.assertNotIn("antigravity", self.collect())
        manual = config.from_dict({"subscriptions": {"antigravity": {"plan": "google_ai_pro"}}}).subscriptions
        sub = self.collect(manual)["antigravity"]
        self.assertEqual(sub["plan"], "google_ai_pro")
        self.assertEqual(sub["plan_label"], "Google AI Pro")
        self.assertEqual(sub["monthly_price_usd"], 19.99)
        self.assertEqual(sub["source"], "manual")
        self.assertEqual(sub["cycle_source"], "rolling_30d")
        self.assertIsNone(sub["anchor_day"])

    def test_manual_toml_and_json(self):
        text = (
            'dominant_threshold = 0.7\n'
            '[subscriptions.claude]\n'
            'plan = "max_20x"          # known key, price overridden\n'
            'monthly_price_usd = 180\n'
            'anchor_day = 25\n'
            'extra_usage_enabled = true\n'
            '[subscriptions.antigravity]\n'
            'plan = "google_ai_ultra"\n'
            '[subscriptions.codex]\n'
            'plan = "friends"\n'
            'monthly_price_usd = 12.5\n'
            'exclude = ["/Users/alice/scratch"]\n'
        )
        cfg = config.from_dict(config._parse_text(text, "attribution.toml"))
        again = config.from_dict(config.parse_toml_subset(text))
        self.assertEqual(again.subscriptions, cfg.subscriptions)
        self.assertEqual(cfg.dominant_threshold, 0.7)
        self.assertEqual(cfg.exclude, ["/Users/alice/scratch"])
        self.assertEqual(cfg.subscriptions["claude"]["monthly_price_usd"], 180.0)
        self.assertEqual(cfg.subscriptions["claude"]["anchor_day"], 25)
        self.assertTrue(cfg.subscriptions["claude"]["extra_usage_enabled"])
        self.assertNotIn("monthly_price_usd", cfg.subscriptions["antigravity"])
        self.assertNotIn("anchor_day", cfg.subscriptions["antigravity"])
        found = self.collect(cfg.subscriptions)
        self.assertEqual(found["claude"]["cycle_source"], "manual")
        self.assertTrue(found["claude"]["extra_usage_enabled"])
        self.assertEqual(found["antigravity"]["monthly_price_usd"], 249.99)
        self.assertEqual(found["antigravity"]["plan_label"], "Google AI Ultra")
        self.assertEqual(found["codex"]["plan_label"], "ChatGPT (friends)")
        self.assertEqual(found["codex"]["monthly_price_usd"], 12.5)
        self.assertEqual(found["codex"]["cycle_source"], "rolling_30d")
        raw = json.dumps({"subscriptions": {"claude": {"plan": "pro", "anchor_day": 4}}})
        cfg = config.from_dict(config._parse_text(raw, "attribution.json"))
        self.assertEqual(cfg.subscriptions["claude"]["anchor_day"], 4)
        self.assertEqual(self.collect(cfg.subscriptions)["claude"]["plan_label"], "Claude Pro")

    def test_config_validation_exits_2(self):
        path = os.path.join(self.dir, "bad.toml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('[subscriptions.claude]\nplan = "nope"\n')
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = cli.main(["export", "--config", path])
        self.assertEqual(code, 2)
        self.assertIn("monthly_price_usd", err.getvalue())
        bad = (
            {"claude": {"plan": "pro", "anchor_day": 29}},
            {"claude": {"plan": "pro", "anchor_day": 0}},
            {"claude": {"plan": "pro", "anchor_day": True}},
            {"claude": {"plan": "pro", "monthly_price_usd": -1}},
            {"claude": {"plan": "pro", "monthly_price_usd": True}},
            {"claude": {"plan": "plus"}},
            {"claude": "max_5x"},
            ["claude"],
        )
        for spec in bad:
            with self.assertRaises(ConfigError):
                config.from_dict({"subscriptions": spec})
        # 28 is the top of the manual range; an unknown plan is fine once priced
        cfg = config.from_dict({"subscriptions": {"claude": {
            "plan": "plus", "monthly_price_usd": 15, "anchor_day": 28,
        }}})
        sub = self.collect(cfg.subscriptions)["claude"]
        self.assertEqual(sub["plan_label"], "Claude (plus)")
        self.assertEqual(sub["monthly_price_usd"], 15.0)
        self.assertEqual(sub["anchor_day"], 28)

    def test_manual_fields_preserve_detection(self):
        self.write_claude(extra=True)
        for spec in ({"anchor_day": 8}, {"monthly_price_usd": 75}, {"plan": "pro"}):
            manual = config.from_dict({"subscriptions": {"claude": spec}}).subscriptions
            sub = self.collect(manual)["claude"]
            self.assertEqual(sub["source"], "manual")
            self.assertTrue(sub["extra_usage_enabled"])
            self.assertEqual(sub["plan"], spec.get("plan", "max_5x"))
            self.assertEqual(sub["anchor_day"], spec.get("anchor_day", 25))
            self.assertEqual(sub["cycle_source"], "manual" if "anchor_day" in spec else "subscription_date")
            expected_price = 20.0 if "plan" in spec else spec.get("monthly_price_usd", 100.0)
            self.assertEqual(sub["monthly_price_usd"], expected_price)
            check_subscriptions(self, {"claude": sub})

    def test_manual_plan_or_price_preserves_rolling_window(self):
        self.write_claude(drop_created=True)
        self.write_codex()
        for agent, plan in (("claude", "pro"), ("codex", "team")):
            for spec in ({"plan": plan}, {"monthly_price_usd": 75}):
                with self.subTest(agent=agent, spec=spec):
                    manual = config.from_dict({"subscriptions": {agent: spec}}).subscriptions
                    sub = self.collect(manual)[agent]
                    self.assertEqual(sub["source"], "manual")
                    self.assertEqual(sub["cycle_source"], "rolling_30d")
                    self.assertIsNone(sub["anchor_day"])
                    self.assertEqual(sub["cycle_start"], "2026-09-24T12:00:00Z")
                    self.assertEqual(sub["cycle_end"], "2026-10-24T12:00:00Z")
                    check_subscriptions(self, {agent: sub})

    def test_cycle_crosses_month_boundary(self):
        manual = config.from_dict({"subscriptions": {"claude": {"plan": "pro", "anchor_day": 15}}}).subscriptions
        before = self.collect(manual, now=datetime(2026, 5, 14, 23, 59, 59, tzinfo=timezone.utc))["claude"]
        self.assertEqual(before["cycle_start"], "2026-04-15T00:00:00Z")
        self.assertEqual(before["cycle_end"], "2026-05-15T00:00:00Z")
        on_day = self.collect(manual, now=datetime(2026, 5, 15, 0, 0, tzinfo=timezone.utc))["claude"]
        self.assertEqual(on_day["cycle_start"], "2026-05-15T00:00:00Z")
        self.assertEqual(on_day["cycle_end"], "2026-06-15T00:00:00Z")
        # January is still on the previous December's anchor
        year = self.collect(manual, now=datetime(2026, 1, 10, tzinfo=timezone.utc))["claude"]
        self.assertEqual(year["cycle_start"], "2025-12-15T00:00:00Z")
        self.assertEqual(year["cycle_end"], "2026-01-15T00:00:00Z")

    def test_anchor_31_clamps_in_a_short_month(self):
        self.write_claude(created="2026-01-31T10:00:00Z")
        feb = self.collect(now=datetime(2026, 2, 28, 15, tzinfo=timezone.utc))["claude"]
        self.assertEqual(feb["anchor_day"], 31)
        self.assertEqual(feb["cycle_start"], "2026-02-28T00:00:00Z")
        self.assertEqual(feb["cycle_end"], "2026-03-31T00:00:00Z")
        early = self.collect(now=datetime(2026, 2, 27, 23, tzinfo=timezone.utc))["claude"]
        self.assertEqual(early["cycle_start"], "2026-01-31T00:00:00Z")
        self.assertEqual(early["cycle_end"], "2026-02-28T00:00:00Z")
        leap = self.collect(now=datetime(2024, 2, 29, 12, tzinfo=timezone.utc))["claude"]
        self.assertEqual(leap["cycle_start"], "2024-02-29T00:00:00Z")
        self.assertEqual(leap["cycle_end"], "2024-03-31T00:00:00Z")

    def test_cycle_uses_report_timezone(self):
        manual = config.from_dict({"subscriptions": {"claude": {"plan": "pro", "anchor_day": 10}}}).subscriptions
        # 2026-04-09 17:00 UTC is 2026-04-10 01:00 in Shanghai, so the 10th has started
        now = datetime(2026, 4, 9, 17, tzinfo=timezone.utc)
        shanghai = self.collect(manual, now=now, tz="Asia/Shanghai")["claude"]
        self.assertEqual(shanghai["cycle_start"], "2026-04-09T16:00:00Z")
        self.assertEqual(shanghai["cycle_end"], "2026-05-09T16:00:00Z")
        utc = self.collect(manual, now=now, tz="UTC")["claude"]
        self.assertEqual(utc["cycle_start"], "2026-03-10T00:00:00Z")
        # Montreal is UTC-4 in October and UTC-5 in November, so the two midnights differ
        manual = config.from_dict({"subscriptions": {"claude": {"plan": "pro", "anchor_day": 25}}}).subscriptions
        now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
        montreal = self.collect(manual, now=now, tz="America/Montreal")["claude"]
        self.assertEqual(montreal["cycle_start"], "2026-10-25T04:00:00Z")
        self.assertEqual(montreal["cycle_end"], "2026-11-25T05:00:00Z")

    def test_contract_rejects_a_bad_cycle(self):
        bad = {
            "plan": "plus", "plan_label": "ChatGPT Plus", "monthly_price_usd": 20.0,
            "cycle_start": "2026-05-01T00:00:00Z", "cycle_end": "2026-04-01T00:00:00Z",
            "anchor_day": 1, "cycle_source": "manual",
            "extra_usage_enabled": False, "source": "detected",
        }
        with self.assertRaises(AssertionError):
            check_subscriptions(self, {"codex": bad})
        bad["cycle_source"] = "weekly"
        bad["cycle_end"] = "2026-06-01T00:00:00Z"
        with self.assertRaises(AssertionError):
            check_subscriptions(self, {"codex": bad})

    def test_contract_requires_null_anchor_only_for_rolling_and_exactly_30_days(self):
        self.write_codex()
        sub = self.collect()["codex"]
        check_subscriptions(self, {"codex": sub})
        for changes in ({"anchor_day": 1}, {"cycle_source": "manual"},
                        {"cycle_source": "subscription_date"}, {"cycle_source": "calendar_month"},
                        {"cycle_start": "2026-09-25T12:00:00Z"},
                        {"cycle_end": "2026-10-24T12:00:01Z"}):
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                check_subscriptions(self, {"codex": dict(sub, **changes)})

    def _doctor(self, env, *argv):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def _doctor_env(self, cache):
        return {
            "KANJO_CLAUDE_DIR": FIXTURE_DIRS["claude"][0],
            "KANJO_ANTIGRAVITY_DIR": FIXTURE_DIRS["antigravity"][0],
            "KANJO_CODEX_DIR": FIXTURE_DIRS["codex"][0],
            "KANJO_CACHE_DIR": cache,
            "KANJO_CONFIG_DIR": self.dir,
            "KANJO_TOKEI_DIR": self.dir,
            "KANJO_CLAUDE_CONFIG": self.claude_path,
        }

    def test_doctor_lists_subscriptions(self):
        self.write_claude(created="2026-09-25T18:33:26.854830Z", extra=False)
        self.write_codex(plan="plus")
        path = os.path.join(self.dir, "attribution.toml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('[subscriptions.antigravity]\nplan = "google_ai_pro"\n')
        cache = tempfile.mkdtemp()
        try:
            code, text = self._doctor(self._doctor_env(cache), "doctor", "--no-cache", "--config", path)
        finally:
            shutil.rmtree(cache)
        self.assertEqual(code, 0)
        self.assertIn("Claude Max 5x", text)
        self.assertIn("$100.00", text)
        self.assertIn("anchor day 25", text)
        self.assertIn("source detected", text)
        self.assertIn("ChatGPT Plus", text)
        self.assertIn("$20.00", text)
        self.assertEqual(text.count("anchor day: unknown (rolling 30 days)"), 2)
        self.assertIn("Google AI Pro", text)
        self.assertIn("$19.99", text)
        self.assertIn("source manual", text)

    def test_doctor_says_none_when_nothing_is_found(self):
        cache = tempfile.mkdtemp()
        env = self._doctor_env(cache)
        env["KANJO_CLAUDE_CONFIG"] = os.path.join(self.dir, "missing.json")
        env["KANJO_TOKEI_DIR"] = os.path.join(self.dir, "no-tokei")
        try:
            code, text = self._doctor(env, "doctor", "--no-cache")
        finally:
            shutil.rmtree(cache)
        self.assertEqual(code, 0)
        self.assertIn("subscriptions:\n  none", text)

    def test_export_includes_subscriptions_and_matches_contract(self):
        fs = standard_fs()
        try:
            now = datetime(2026, 4, 9, 17, tzinfo=timezone.utc)
            self.write_claude(created="2026-01-10T08:00:00Z")
            self.write_codex(plan="plus", fetched=now.timestamp())
            env = {"KANJO_CLAUDE_CONFIG": self.claude_path, "KANJO_TOKEI_DIR": self.dir, "TZ": "Asia/Shanghai"}
            with mock.patch.dict(os.environ, env):
                doc = build_export(dirs=FIXTURE_DIRS, fs_root=fs.root, home=ALICE, now=now, tokei_dir=self.dir)
            self.assertEqual(doc["timezone"], "Asia/Shanghai")
            keys = list(doc)
            self.assertEqual(keys.index("subscriptions"), keys.index("quota_windows") + 1)
            validate_contract(self, doc)
            self.assertEqual(check_invariants(doc), [])
            claude = doc["subscriptions"]["claude"]
            self.assertEqual(claude["plan"], "max_5x")
            self.assertEqual(claude["source"], "detected")
            self.assertEqual(claude["cycle_start"], "2026-04-09T16:00:00Z")
            self.assertEqual(claude["cycle_end"], "2026-05-09T16:00:00Z")
            codex = doc["subscriptions"]["codex"]
            self.assertEqual(codex["plan"], "plus")
            self.assertEqual(codex["cycle_start"], "2026-03-10T17:00:00Z")
            self.assertEqual(codex["cycle_end"], "2026-04-09T17:00:00Z")
            self.assertNotIn("antigravity", doc["subscriptions"])
        finally:
            fs.cleanup()


if __name__ == "__main__":
    unittest.main()
