import json
import os
import shutil
import stat
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

from kanjo import quota, quota_fetch, subscriptions


class QuotaFetchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-quota-fetch-")
        self.data_dir = os.path.join(self.tmp, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.env = mock.patch.dict(os.environ, {
            "KANJO_DATA_DIR": self.data_dir,
            "KANJO_NO_NETWORK": "1",  # Never hit network in tests by default
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)

    def test_parse_antigravity_summary(self):
        now = 1730000000.0
        data = {
            "groups": [
                {
                    "displayName": "Gemini Models",
                    "buckets": [
                        {
                            "window": "weekly",
                            "remainingFraction": 0.199,
                            "resetTime": now + 50000,
                            "windowMinutes": 10080,
                        },
                        {
                            "window": "5h",
                            "remainingFraction": 0.75,
                            "resetTime": now + 3600,
                            "windowMinutes": 300,
                        },
                    ],
                },
                {
                    "displayName": "Claude and GPT Models",
                    "buckets": [
                        {
                            "bucketId": "antigravity-3p-weekly",
                            "displayName": "Claude/GPT 周",
                            "remainingFraction": 0.90,
                            "resetTime": now + 50000,
                            "windowMinutes": 10080,
                        },
                        {
                            "bucketId": "antigravity-3p-5h",
                            "displayName": "Claude/GPT 5h",
                            "remainingFraction": 0.50,
                            "resetTime": now + 1800,
                            "windowMinutes": 300,
                        },
                    ],
                },
            ]
        }
        res = quota_fetch.parse_antigravity_summary(data, now=now, plan_name="Google AI Pro")
        self.assertIsNotNone(res)
        self.assertEqual(res["plan"], "Google AI Pro")
        self.assertEqual(res["weekly_used_percent"], 80.1)
        self.assertEqual(res["five_hour_used_percent"], 25.0)
        self.assertEqual(res["weekly_window_hours"], 168)
        self.assertEqual(res["five_hour_window_hours"], 5)
        self.assertEqual(len(res["extra_windows"]), 2)
        self.assertEqual(res["extra_windows"][0]["id"], "antigravity-3p-weekly")
        self.assertEqual(res["extra_windows"][0]["title"], "Claude/GPT 周")
        self.assertEqual(res["extra_windows"][0]["used_percent"], 10.0)
        self.assertEqual(res["extra_windows"][1]["id"], "antigravity-3p-5h")
        self.assertEqual(res["extra_windows"][1]["used_percent"], 50.0)

    def test_parse_codex_usage(self):
        now = 1730000000.0
        data = {
            "plan_type": "plus",
            "rate_limit": {
                "primary_window": {
                    "used_percent": 12.0,
                    "limit_window_seconds": 18000,
                    "reset_at": now + 3600,
                },
                "secondary_window": {
                    "used_percent": 45.5,
                    "limit_window_seconds": 604800,
                    "reset_at": now + 86400,
                },
            },
        }
        res = quota_fetch.parse_codex_usage(data, now=now)
        self.assertIsNotNone(res)
        self.assertEqual(res["plan"], "plus")
        self.assertEqual(res["five_hour_used_percent"], 12.0)
        self.assertEqual(res["weekly_used_percent"], 45.5)
        self.assertEqual(res["five_hour_window_hours"], 5)
        self.assertEqual(res["weekly_window_hours"], 168)

    def test_parse_claude_usage(self):
        now = 1730000000.0
        data = {
            "five_hour": {
                "utilization": 0.13,
                "resets_at": "2024-10-27T10:00:00Z",
            },
            "seven_day": {
                "utilization": 0.57,
                "resets_at": "2024-10-31T10:00:00Z",
            },
        }
        res = quota_fetch.parse_claude_usage(data, now=now)
        self.assertIsNotNone(res)
        self.assertEqual(res["five_hour_used_percent"], 13.0)
        self.assertEqual(res["weekly_used_percent"], 57.0)
        self.assertEqual(res["five_hour_window_hours"], 5)
        self.assertEqual(res["weekly_window_hours"], 168)

    def test_parse_grok_usage(self):
        now = 1730000000.0
        data = {
            "subscriptionTier": "SuperGrok",
            "config": {
                "creditUsagePercent": 42.0,
                "currentPeriod": {
                    "end": "2024-10-31T10:00:00Z",
                },
            },
        }
        res = quota_fetch.parse_grok_usage(data, now=now)
        self.assertIsNotNone(res)
        self.assertEqual(res["plan"], "SuperGrok")
        self.assertEqual(res["weekly_used_percent"], 42.0)
        self.assertEqual(res["weekly_window_hours"], 168)
        self.assertIsNone(res["five_hour_resets_at"])

    def test_malformed_and_empty_responses_return_none(self):
        now = 1730000000.0
        self.assertIsNone(quota_fetch.parse_antigravity_summary({}, now=now))
        self.assertIsNone(quota_fetch.parse_antigravity_summary({"groups": []}, now=now))
        self.assertIsNone(quota_fetch.parse_codex_usage({}, now=now))
        self.assertIsNone(quota_fetch.parse_claude_usage({}, now=now))
        self.assertIsNone(quota_fetch.parse_grok_usage({}, now=now))

    def test_cache_ttl_and_no_network(self):
        now = 1730000000.0
        fake_data = {
            "version": 1,
            "fetched_at": now - 100,  # within 300s TTL
            "providers": {
                "antigravity": {
                    "weekly_resets_at": "2024-10-31T10:00:00Z",
                    "weekly_window_hours": 168,
                    "weekly_used_percent": 80.0,
                    "plan": "Google AI Pro",
                }
            }
        }
        quota_fetch.save_quota_cache(fake_data)

        # Reads from cache without hitting network
        result = quota_fetch.fetch_all_quotas(now=now, no_network=True)
        self.assertIn("antigravity", result)
        self.assertEqual(result["antigravity"]["weekly_used_percent"], 80.0)

        # When network is disabled and cache is stale, returns stale cache
        stale_result = quota_fetch.fetch_all_quotas(now=now + 500, no_network=True)
        self.assertIn("antigravity", stale_result)

    def test_secrets_never_in_cache_file(self):
        secret_token = "SECRET_BEARER_TOKEN_XYZZY_999"
        secret_csrf = "SECRET_ANTIGRAVITY_CSRF_TOKEN_42"

        data_to_cache = {
            "version": 1,
            "fetched_at": time.time(),
            "providers": {
                "antigravity": {
                    "weekly_resets_at": "2024-10-31T10:00:00Z",
                    "weekly_window_hours": 168,
                    "weekly_used_percent": 80.0,
                    "plan": "Google AI Pro",
                }
            }
        }
        quota_fetch.save_quota_cache(data_to_cache)
        cache_file = quota_fetch.quota_cache_path()
        self.assertTrue(os.path.exists(cache_file))

        with open(cache_file, "r", encoding="utf-8") as f:
            raw = f.read()

        self.assertNotIn(secret_token, raw)
        self.assertNotIn(secret_csrf, raw)
        self.assertNotIn("token", raw)
        self.assertNotIn("auth", raw)

        # Check file mode is 0600
        mode = stat.S_IMODE(os.stat(cache_file).st_mode)
        self.assertEqual(mode, 0o600)

    def test_subscriptions_uses_fetched_plan_without_tokei(self):
        now = datetime(2024, 10, 27, 10, 0, tzinfo=timezone.utc)
        fake_cache = {
            "version": 1,
            "fetched_at": now.timestamp(),
            "providers": {
                "antigravity": {
                    "plan": "Google AI Pro",
                    "weekly_resets_at": "2024-10-31T10:00:00Z",
                },
                "codex": {
                    "plan": "plus",
                    "weekly_resets_at": "2024-10-31T10:00:00Z",
                },
            }
        }
        quota_fetch.save_quota_cache(fake_cache)

        # Pass non-existent tokei directory; subscriptions should still detect Google AI Pro and Codex Plus!
        subs = subscriptions.subscriptions(manual={}, directory="/nonexistent/tokei/dir", now=now)
        self.assertIn("antigravity", subs)
        self.assertEqual(subs["antigravity"]["plan"], "google_ai_pro")
        self.assertEqual(subs["antigravity"]["plan_label"], "Google AI Pro")
        self.assertEqual(subs["antigravity"]["monthly_price_usd"], 19.99)
        self.assertEqual(subs["antigravity"]["source"], "detected")

        self.assertIn("codex", subs)
        self.assertEqual(subs["codex"]["plan"], "plus")
        self.assertEqual(subs["codex"]["plan_label"], "ChatGPT Plus")
        self.assertEqual(subs["codex"]["monthly_price_usd"], 20.0)

    def test_quota_source_priority(self):
        now = datetime(2024, 10, 27, 10, 0, tzinfo=timezone.utc).timestamp()
        fake_cache = {
            "version": 1,
            "fetched_at": now,
            "providers": {
                "claude": {
                    "weekly_resets_at": "2024-10-31T10:00:00Z",
                    "weekly_window_hours": 168,
                    "weekly_used_percent": 30.0,
                    "source": "tokei",
                }
            }
        }
        quota_fetch.save_quota_cache(fake_cache)

        # 1. Fetched quota is present
        qw = quota.quota_windows(manual={}, directory="/nonexistent/tokei", now=now, no_network=True)
        self.assertIn("claude", qw)
        self.assertEqual(qw["claude"]["weekly_used_percent"], 30.0)

        # 2. Manual override beats fetched quota
        manual = {
            "claude": {
                "weekly_reset": "tue 05:00",
                "weekly_window_hours": 168,
            }
        }
        qw_manual = quota.quota_windows(manual=manual, directory="/nonexistent/tokei", now=now, no_network=True)
        self.assertEqual(qw_manual["claude"]["source"], "manual")


if __name__ == "__main__":
    unittest.main()
