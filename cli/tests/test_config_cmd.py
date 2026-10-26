"""Subscription overrides, effective origins and atomic configuration edits."""

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from kanjo import cli, config, config_cmd, quota
from kanjo.subscriptions import subscriptions

from tests.support import FIXTURE_DIRS, check_subscriptions


class ConfigCommandTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kanjo-config-")
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.config_dir = os.path.join(self.root, "config")
        os.mkdir(self.config_dir)
        self.toml = os.path.join(self.config_dir, "attribution.toml")
        self.overrides = os.path.join(self.config_dir, "overrides.json")
        self.claude = os.path.join(self.root, "claude.json")
        env = {
            "KANJO_CONFIG_DIR": self.config_dir,
            "KANJO_CACHE_DIR": os.path.join(self.root, "cache"),
            "KANJO_DATA_DIR": os.path.join(self.root, "data"),
            "KANJO_TOKEI_DIR": self.root,
            "KANJO_CLAUDE_CONFIG": self.claude,
            "KANJO_CLAUDE_DIR": FIXTURE_DIRS["claude"][0],
            "KANJO_CODEX_DIR": FIXTURE_DIRS["codex"][0],
            "KANJO_ANTIGRAVITY_DIR": FIXTURE_DIRS["antigravity"][0],
        }
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        self.write_json(os.path.join(self.root, quota.CODEX_FILE), {"plan": "plus", "fetched_at": time.time()})
        self.write_json(self.claude, {"oauthAccount": {
            "billingType": "stripe_subscription", "organizationRateLimitTier": "default_claude_max_5x",
            "subscriptionCreatedAt": "2026-09-25T10:00:00Z", "hasExtraUsageEnabled": True,
        }})

    def write_json(self, path, data):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def write_toml(self, text):
        with open(self.toml, "w", encoding="utf-8") as handle:
            handle.write(text)

    def read_overrides(self):
        with open(self.overrides, encoding="utf-8") as handle:
            return json.load(handle)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def assert_line(self, argv, expected):
        self.assertEqual(self.run_cli("config", *argv), (0, expected + "\n", ""))

    def test_set_get_unset_round_trip_all_fields(self):
        for field, value, effective, fallback, origin in (
                ("anchor_day", "8", "8", "unset", "rolling 30 days"),
                ("plan", "pro", '"pro"', '"plus"', "detected"),
                ("monthly_price_usd", "0", "0.0", "20.0", "detected")):
            key = "subscriptions.codex." + field
            self.assert_line(("set", key, value), "%s = %s (overrides)" % (key, effective))
            self.assert_line(("get", key), "%s = %s (overrides)" % (key, effective))
            self.assertIn(field, self.read_overrides()["subscriptions"]["codex"])
            self.assert_line(("unset", key), "%s = %s (%s)" % (key, fallback, origin))
            self.assertNotIn("codex", self.read_overrides()["subscriptions"])

    def test_precedence_overrides_toml_detected_default(self):
        key = "subscriptions.claude.anchor_day"
        self.assert_line(("get", key), key + " = 25 (detected)")
        self.write_toml('[subscriptions.claude]\nanchor_day = 12\n')
        self.assert_line(("get", key), key + " = 12 (toml)")
        self.assert_line(("set", key, "8"), key + " = 8 (overrides)")
        self.assertEqual(config.load().subscriptions["claude"], {"anchor_day": 8})
        self.assert_line(("unset", key), key + " = 12 (toml)")
        os.unlink(self.toml)
        self.assert_line(("get", key), key + " = 25 (detected)")
        os.unlink(self.claude)
        self.assert_line(("get", key), key + " = unset (rolling 30 days)")

    def test_anchor_only_keeps_detected_plan_price_and_extra(self):
        self.run_cli("config", "set", "subscriptions.claude.anchor_day", "8")
        found = subscriptions(config.load().subscriptions)
        sub = found["claude"]
        self.assertEqual((sub["plan"], sub["plan_label"], sub["monthly_price_usd"]),
                         ("max_5x", "Claude Max 5x", 100.0))
        self.assertTrue(sub["extra_usage_enabled"])
        self.assertEqual((sub["anchor_day"], sub["source"], sub["cycle_source"]), (8, "manual", "manual"))
        check_subscriptions(self, found)

    def test_unset_anchor_returns_to_rolling_window(self):
        key = "subscriptions.codex.anchor_day"
        self.assert_line(("get", key), key + " = unset (rolling 30 days)")
        self.assert_line(("set", key, "8"), key + " = 8 (overrides)")
        self.assert_line(("unset", key), key + " = unset (rolling 30 days)")
        code, out, err = self.run_cli("export", "--no-cache")
        self.assertEqual(code, 0, err)
        found = json.loads(out)["subscriptions"]
        self.assertIsNone(found["codex"]["anchor_day"])
        self.assertEqual(found["codex"]["cycle_source"], "rolling_30d")
        self.assertEqual(found["codex"]["source"], "detected")
        check_subscriptions(self, found)
        code, out, err = self.run_cli("doctor", "--no-cache")
        self.assertEqual(code, 0, err)
        self.assertIn("codex: ChatGPT Plus, $20.00, anchor day: unknown (rolling 30 days)", out)

    def test_precedence_merges_each_field_across_files(self):
        self.write_toml('[subscriptions.codex]\nplan = "team"\nmonthly_price_usd = 25\nanchor_day = 12\n')
        self.write_json(self.overrides, {"subscriptions": {"codex": {"anchor_day": 8}}})
        sub = subscriptions(config.load().subscriptions)["codex"]
        self.assertEqual((sub["plan"], sub["monthly_price_usd"], sub["anchor_day"]), ("team", 25.0, 8))
        self.assert_line(("get", "subscriptions.codex.plan"), 'subscriptions.codex.plan = "team" (toml)')
        self.assert_line(("get", "subscriptions.codex.monthly_price_usd"),
                         "subscriptions.codex.monthly_price_usd = 25.0 (toml)")
        self.assertEqual(self.run_cli("config", "set", "subscriptions.codex.plan", "pro")[0], 0)
        self.assertEqual(self.run_cli("config", "set", "subscriptions.codex.monthly_price_usd", "150")[0], 0)
        sub = subscriptions(config.load().subscriptions)["codex"]
        self.assertEqual((sub["plan"], sub["plan_label"], sub["monthly_price_usd"], sub["anchor_day"]),
                         ("pro", "ChatGPT Pro", 150.0, 8))
        self.assert_line(("unset", "subscriptions.codex.plan"), 'subscriptions.codex.plan = "team" (toml)')
        self.assert_line(("unset", "subscriptions.codex.monthly_price_usd"),
                         "subscriptions.codex.monthly_price_usd = 25.0 (toml)")

    def test_preserves_other_keys_and_never_edits_toml(self):
        text = '# keep this comment\n[subscriptions.codex]\nplan = "team"\nmonthly_price_usd = 25\n'
        self.write_toml(text)
        other = {"future": {"theme": "dark"}, "subscriptions": {
            "claude": {"anchor_day": 4}, "codex": {"future_field": "keep"}}}
        self.write_json(self.overrides, other)
        self.assertEqual(self.run_cli("config", "set", "subscriptions.codex.anchor_day", "8")[0], 0)
        data = self.read_overrides()
        self.assertEqual(data["future"], other["future"])
        self.assertEqual(data["subscriptions"]["claude"], other["subscriptions"]["claude"])
        self.assertEqual(data["subscriptions"]["codex"], {"anchor_day": 8, "future_field": "keep"})
        self.assertEqual(self.run_cli("config", "unset", "subscriptions.codex.anchor_day")[0], 0)
        self.assertEqual(self.read_overrides(), other)
        with open(self.toml, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), text)

    def test_plan_fills_label_price_and_preserves_detected_anchor(self):
        self.assertEqual(self.run_cli("config", "set", "subscriptions.claude.plan", "pro")[0], 0)
        self.assert_line(("get", "subscriptions.claude.monthly_price_usd"),
                         "subscriptions.claude.monthly_price_usd = 20.0 (overrides)")
        sub = subscriptions(config.load().subscriptions)["claude"]
        self.assertEqual((sub["plan_label"], sub["monthly_price_usd"], sub["anchor_day"], sub["cycle_source"]),
                         ("Claude Pro", 20.0, 25, "subscription_date"))
        self.assertTrue(sub["extra_usage_enabled"])

    def test_validation_errors_do_not_write(self):
        for key, value in (
                ("subscriptions.codex.anchor_day", "0"), ("subscriptions.codex.anchor_day", "29"),
                ("subscriptions.codex.anchor_day", "1.5"), ("subscriptions.codex.anchor_day", "true"),
                ("subscriptions.codex.monthly_price_usd", "-1"), ("subscriptions.codex.monthly_price_usd", "nan"),
                ("subscriptions.codex.monthly_price_usd", "inf"), ("subscriptions.codex.monthly_price_usd", "free"),
                ("subscriptions.codex.plan", ""), ("subscriptions.codex.plan", "unknown"),
                ("subscriptions.other.anchor_day", "8"), ("subscriptions.codex.other", "8"), ("bad", "8")):
            code, out, err = self.run_cli("config", "set", key, value)
            self.assertEqual((code, out), (2, ""), (key, value, err))
            self.assertEqual(len(err.splitlines()), 1)
            self.assertFalse(os.path.exists(self.overrides))
        for args in (("get", "bad"), ("unset", "bad"), ("set", "subscriptions.codex.plan"),
                     ("get", "subscriptions.codex.plan", "extra"), ("path", "extra")):
            self.assertEqual(self.run_cli("config", *args)[0], 2)

    def test_boundary_values_and_custom_plan_with_price(self):
        for day in ("1", "28"):
            self.assertEqual(self.run_cli("config", "set", "subscriptions.codex.anchor_day", day)[0], 0)
        self.assertEqual(self.run_cli("config", "set", "subscriptions.codex.monthly_price_usd", "12.5")[0], 0)
        self.assert_line(("set", "subscriptions.codex.plan", "custom"),
                         'subscriptions.codex.plan = "custom" (overrides)')

    def test_config_all_new_agents_supported(self):
        new_agents = {
            "grok": ("supergrok", 30.0),
            "copilot": ("pro", 10.0),
            "minimax": ("starter", 10.0),
            "qwen": ("coding_plan", 50.0),
            "commandcode": ("goat", 10.0),
            "opencode": ("go", 10.0),
        }
        for agent, (plan, price) in new_agents.items():
            key = "subscriptions.%s.plan" % agent
            self.assertEqual(self.run_cli("config", "set", key, plan)[0], 0)
            self.assert_line(("get", "subscriptions.%s.monthly_price_usd" % agent),
                             "subscriptions.%s.monthly_price_usd = %s (overrides)" % (agent, price))
            day_key = "subscriptions.%s.anchor_day" % agent
            self.assertEqual(self.run_cli("config", "set", day_key, "15")[0], 0)
            self.assert_line(("get", day_key), "%s = 15 (overrides)" % day_key)
            self.assertEqual(self.run_cli("config", "unset", key)[0], 0)
            self.assertEqual(self.run_cli("config", "unset", day_key)[0], 0)

    def test_unpriced_plans_require_price(self):
        # Setting an unpriced plan directly without monthly_price_usd fails
        self.assertEqual(self.run_cli("config", "set", "subscriptions.commandcode.plan", "provider")[0], 2)
        # But setting price first works
        self.assertEqual(self.run_cli("config", "set", "subscriptions.commandcode.monthly_price_usd", "15")[0], 0)
        self.assertEqual(self.run_cli("config", "set", "subscriptions.commandcode.plan", "provider")[0], 0)
        self.assert_line(("get", "subscriptions.commandcode.plan"),
                         'subscriptions.commandcode.plan = "provider" (overrides)')
        self.assert_line(("get", "subscriptions.commandcode.monthly_price_usd"),
                         'subscriptions.commandcode.monthly_price_usd = 15.0 (overrides)')
        # Clean up
        self.run_cli("config", "unset", "subscriptions.commandcode.plan")
        self.run_cli("config", "unset", "subscriptions.commandcode.monthly_price_usd")

    def test_paths_env_and_explicit_config_directory(self):
        self.assertEqual(self.run_cli("config", "path"), (0, self.toml + "\n" + self.overrides + "\n", ""))
        other = os.path.join(self.root, "other.toml")
        with open(other, "w", encoding="utf-8") as handle:
            handle.write('[subscriptions.codex]\nanchor_day = 4\n')
        override = os.path.join(self.root, "overrides.json")
        key = "subscriptions.codex.anchor_day"
        self.assert_line(("set", key, "8", "--config", other), key + " = 8 (overrides)")
        self.assertEqual(config.load(other).subscriptions["codex"]["anchor_day"], 8)
        self.assertFalse(os.path.exists(self.overrides))
        self.assertEqual(self.run_cli("config", "path", "--config", other),
                         (0, other + "\n" + override + "\n", ""))

    def test_atomic_replace_and_cleanup_on_failure(self):
        key = "subscriptions.codex.anchor_day"
        with mock.patch.object(config_cmd.os, "replace", wraps=os.replace) as replace:
            self.assertEqual(self.run_cli("config", "set", key, "8")[0], 0)
        src, dst = replace.call_args[0]
        self.assertEqual(os.path.dirname(src), self.config_dir)
        self.assertEqual(dst, self.overrides)
        self.assertEqual(os.listdir(self.config_dir), ["overrides.json"])
        with mock.patch.object(config_cmd.os, "replace", side_effect=OSError("rename failed")):
            code, _, err = self.run_cli("config", "set", key, "9")
        self.assertEqual(code, 2)
        self.assertIn("rename failed", err)
        self.assertEqual(self.read_overrides()["subscriptions"]["codex"]["anchor_day"], 8)
        self.assertEqual(os.listdir(self.config_dir), ["overrides.json"])

    def test_bad_overrides_are_not_overwritten(self):
        for text in ('{not json', '[]', '{"subscriptions": []}', '{"subscriptions": {"codex": 8}}'):
            with open(self.overrides, "w", encoding="utf-8") as handle:
                handle.write(text)
            for action in ("get", "set", "unset"):
                args = ["config", action, "subscriptions.codex.anchor_day"] + (["8"] if action == "set" else [])
                code, _, err = self.run_cli(*args)
                self.assertEqual(code, 2)
                self.assertEqual(len(err.splitlines()), 1)
                with open(self.overrides, encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), text)

    def test_export_and_doctor_reflect_override(self):
        self.assertEqual(self.run_cli("config", "set", "subscriptions.codex.anchor_day", "8")[0], 0)
        code, out, err = self.run_cli("export", "--no-cache")
        self.assertEqual(code, 0, err)
        found = json.loads(out)["subscriptions"]
        sub = found["codex"]
        self.assertEqual((sub["plan"], sub["anchor_day"], sub["cycle_source"], sub["source"]),
                         ("plus", 8, "manual", "manual"))
        check_subscriptions(self, found)
        code, out, err = self.run_cli("doctor", "--no-cache")
        self.assertEqual(code, 0, err)
        self.assertIn("anchor day 8 (overrides.json)", out)
        self.assertIn("anchor day 25 (detected)", out)

    def test_config_plans_json(self):
        from kanjo.subscriptions import KNOWN_PLANS
        code, out, err = self.run_cli("config", "plans", "--json")
        self.assertEqual((code, err), (0, ""))
        data = json.loads(out)
        self.assertEqual(list(data.keys()), list(KNOWN_PLANS.keys()))
        for agent, expected_plans in KNOWN_PLANS.items():
            self.assertIn(agent, data)
            actual_plans = data[agent]
            self.assertEqual(len(actual_plans), len(expected_plans))
            for actual, (expected_key, (expected_label, expected_price)) in zip(actual_plans, expected_plans.items()):
                self.assertEqual(actual["key"], expected_key)
                self.assertEqual(actual["label"], expected_label)
                self.assertEqual(actual["monthly_price_usd"], expected_price)

    def test_config_plans_text(self):
        code, out, err = self.run_cli("config", "plans")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("claude:", out)
        self.assertIn("Claude Pro ($20.00)", out)
        self.assertIn("ChatGPT Plus ($20.00)", out)
        self.assertIn("X Premium+ (unknown)", out)

    def test_config_plans_rejects_arguments(self):
        code, _, err = self.run_cli("config", "plans", "extra")
        self.assertEqual(code, 2)
        self.assertIn("takes no key or value", err)
        code, _, err = self.run_cli("config", "plans", "k", "v")
        self.assertEqual(code, 2)
        self.assertIn("takes no key or value", err)

    def test_config_json_rejected_for_non_plans(self):
        for subcmd in ("get", "set", "unset", "path"):
            args = ["config", subcmd]
            if subcmd in ("get", "unset"):
                args.append("subscriptions.codex.plan")
            elif subcmd == "set":
                args.extend(["subscriptions.codex.plan", "plus"])
            args.append("--json")
            code, _, err = self.run_cli(*args)
            self.assertEqual(code, 2)
            self.assertIn("does not accept --json", err)


if __name__ == "__main__":
    unittest.main()
