import gzip
import io
import json
import os
import shutil
import stat
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

from kanjo import quota, quota_claude_cache, quota_fetch, subscriptions


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
        self.assertEqual(res["source"], "live")
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
        self.assertEqual(res["source"], "live")
        self.assertEqual(res["plan"], "plus")
        self.assertEqual(res["five_hour_used_percent"], 12.0)
        self.assertEqual(res["weekly_used_percent"], 45.5)
        self.assertEqual(res["five_hour_window_hours"], 5)
        self.assertEqual(res["weekly_window_hours"], 168)

    def test_parse_claude_usage(self):
        now = 1730000000.0
        data = {
            "five_hour": {
                "utilization": 13,
                "resets_at": "2024-10-27T10:00:00Z",
            },
            "seven_day": {
                "utilization": 57,
                "resets_at": "2024-10-31T10:00:00Z",
            },
        }
        res = quota_fetch.parse_claude_usage(data, now=now)
        self.assertIsNotNone(res)
        self.assertEqual(res["source"], "live")
        self.assertEqual(res["five_hour_used_percent"], 13.0)
        self.assertEqual(res["weekly_used_percent"], 57.0)
        self.assertEqual(res["five_hour_window_hours"], 5)
        self.assertEqual(res["weekly_window_hours"], 168)

    def test_parse_grok_usage_unified_billing_omitted_zero(self):
        now = 1730000000.0
        # Protobuf JSON omits creditUsagePercent when 0.0
        data = {
            "config": {
                "isUnifiedBillingUser": True,
                "currentPeriod": {
                    "start": "2024-10-24T10:00:00Z",
                    "end": "2024-10-31T10:00:00Z",
                },
            },
        }
        res = quota_fetch.parse_grok_usage(data, now=now)
        self.assertIsNotNone(res)
        self.assertEqual(res["source"], "live")
        self.assertEqual(res["plan"], "SuperGrok")
        self.assertEqual(res["weekly_used_percent"], 0.0)
        self.assertEqual(res["weekly_window_hours"], 168)
        self.assertIsNone(res["five_hour_resets_at"])

    def test_malformed_and_empty_responses_return_none(self):
        now = 1730000000.0
        self.assertIsNone(quota_fetch.parse_antigravity_summary({}, now=now))
        self.assertIsNone(quota_fetch.parse_antigravity_summary({"groups": []}, now=now))
        self.assertIsNone(quota_fetch.parse_codex_usage({}, now=now))
        self.assertIsNone(quota_fetch.parse_claude_usage({}, now=now))
        self.assertIsNone(quota_fetch.parse_grok_usage({}, now=now))

    def test_debug_logging_format(self):
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            with mock.patch.dict(os.environ, {"KANJO_QUOTA_DEBUG": "1"}):
                quota_fetch._debug_log("claude", "no_credentials")
                quota_fetch._debug_log("grok", "http_status 401")
                quota_fetch._debug_log("codex", "timeout")
                quota_fetch._debug_log("antigravity", "parse_error")
        output = stderr.getvalue()
        self.assertIn("quota_debug: claude -> no_credentials\n", output)
        self.assertIn("quota_debug: grok -> http_status 401\n", output)
        self.assertIn("quota_debug: codex -> timeout\n", output)
        self.assertIn("quota_debug: antigravity -> parse_error\n", output)
        # Ensure no secrets or tokens
        self.assertNotIn("token", output.lower())

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
                    "source": "live",
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
                    "source": "live",
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
                    "source": "live",
                },
                "codex": {
                    "plan": "plus",
                    "weekly_resets_at": "2024-10-31T10:00:00Z",
                    "source": "live",
                },
            }
        }
        quota_fetch.save_quota_cache(fake_cache)

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
                    "source": "live",
                }
            }
        }
        quota_fetch.save_quota_cache(fake_cache)

        # 1. Fetched quota has source "live"
        qw = quota.quota_windows(manual={}, directory="/nonexistent/tokei", now=now, no_network=True)
        self.assertIn("claude", qw)
        self.assertEqual(qw["claude"]["weekly_used_percent"], 30.0)
        self.assertEqual(qw["claude"]["source"], "live")

        # 2. Manual override beats fetched quota and has source "manual"
        manual = {
            "claude": {
                "weekly_reset": "tue 05:00",
                "weekly_window_hours": 168,
            }
        }
        qw_manual = quota.quota_windows(manual=manual, directory="/nonexistent/tokei", now=now, no_network=True)
        self.assertEqual(qw_manual["claude"]["source"], "manual")

    def test_claude_desktop_cache_fresh_payloads(self):
        now = 1730000000.0  # 2024-10-27T03:33:20Z
        cache_dir = os.path.join(self.tmp, "claude_cache")
        os.makedirs(cache_dir, exist_ok=True)

        payload = {
            "five_hour": {
                "utilization": 15.0,
                "resets_at": "2024-10-27T08:00:00Z",
            },
            "seven_day": {
                "utilization": 45.0,
                "resets_at": "2024-10-31T10:00:00Z",
            },
        }

        # 1. Embedded HTTP headers + raw JSON
        f_raw = os.path.join(cache_dir, "0001_0")
        raw_content = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n" + json.dumps(payload).encode("utf-8") + b"\x00\x01\x02"
        )
        with open(f_raw, "wb") as fh:
            fh.write(raw_content)
        os.utime(f_raw, (now, now))

        res_raw = quota_claude_cache.scan_claude_desktop_cache(now=now, cache_dir=cache_dir)
        self.assertIsNotNone(res_raw)
        self.assertEqual(res_raw["weekly_used_percent"], 45.0)
        self.assertEqual(res_raw["weekly_resets_at"], "2024-10-31T10:00:00Z")
        self.assertEqual(res_raw["weekly_window_hours"], 168)
        self.assertEqual(res_raw["five_hour_used_percent"], 15.0)
        self.assertEqual(res_raw["five_hour_resets_at"], "2024-10-27T08:00:00Z")
        self.assertEqual(res_raw["five_hour_window_hours"], 5)
        self.assertEqual(res_raw["source"], "live")

        # 2. Embedded HTTP headers + gzipped JSON
        os.remove(f_raw)
        f_gz = os.path.join(cache_dir, "0002_0")
        gz_body = gzip.compress(json.dumps(payload).encode("utf-8"))
        gz_content = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Encoding: gzip\r\n"
            b"\r\n" + gz_body + b"\xff\xfe\x00"
        )
        with open(f_gz, "wb") as fh:
            fh.write(gz_content)
        os.utime(f_gz, (now, now))

        res_gz = quota_claude_cache.scan_claude_desktop_cache(now=now, cache_dir=cache_dir)
        self.assertIsNotNone(res_gz)
        self.assertEqual(res_gz["weekly_used_percent"], 45.0)
        self.assertEqual(res_gz["five_hour_used_percent"], 15.0)
        self.assertEqual(res_gz["weekly_resets_at"], "2024-10-31T10:00:00Z")
        self.assertEqual(res_gz["five_hour_resets_at"], "2024-10-27T08:00:00Z")
        self.assertEqual(res_gz["source"], "live")

        # 3. Trailing Chromium cache metadata footer after compressed payload
        os.remove(f_gz)
        f_footer = os.path.join(cache_dir, "0003_0")
        chromium_footer = b"\xf5\x13\x24\x9a\x01\x00\x00\x00\x00\x00\x00\x00\x2f\x00\x00\x00\xd8\x41\x0d\xbd"
        footer_content = (
            b"HTTP/1.1 200 OK\r\n"
            b"/api/organizations/org-123/usage\r\n"
            b"\r\n" + gz_body + chromium_footer
        )
        with open(f_footer, "wb") as fh:
            fh.write(footer_content)
        os.utime(f_footer, (now, now))

        res_footer = quota_claude_cache.scan_claude_desktop_cache(now=now, cache_dir=cache_dir)
        self.assertIsNotNone(res_footer)
        self.assertEqual(res_footer["weekly_used_percent"], 45.0)
        self.assertEqual(res_footer["five_hour_used_percent"], 15.0)

        # 4. Zstandard stream with trailing Chromium footer bytes (if zstd CLI available)
        zstd_bin = shutil.which("zstd")
        if not zstd_bin:
            for cand in ("/opt/homebrew/bin/zstd", "/usr/local/bin/zstd", "/usr/bin/zstd"):
                if os.path.isfile(cand) and os.access(cand, os.X_OK):
                    zstd_bin = cand
                    break
        if zstd_bin:
            os.remove(f_footer)
            f_zstd = os.path.join(cache_dir, "0004_0")
            import subprocess
            zstd_body = subprocess.run([zstd_bin, "-c", "-q"], input=json.dumps(payload).encode("utf-8"), capture_output=True).stdout
            zstd_content = b"HTTP/1.1 200 OK\r\n/usage\r\n\r\n" + zstd_body + chromium_footer
            with open(f_zstd, "wb") as fh:
                fh.write(zstd_content)
            os.utime(f_zstd, (now, now))

            res_zstd = quota_claude_cache.scan_claude_desktop_cache(now=now, cache_dir=cache_dir)
            self.assertIsNotNone(res_zstd)
            self.assertEqual(res_zstd["weekly_used_percent"], 45.0)
            self.assertEqual(res_zstd["five_hour_used_percent"], 15.0)

    def test_claude_desktop_cache_expired_ignored(self):
        now = 1730000000.0  # 2024-10-27T03:33:20Z
        cache_dir = os.path.join(self.tmp, "claude_cache_exp")
        os.makedirs(cache_dir, exist_ok=True)

        expired_payload = {
            "five_hour": {
                "utilization": 20.0,
                "resets_at": "2024-10-26T08:00:00Z",  # in the past
            },
            "seven_day": {
                "utilization": 80.0,
                "resets_at": "2024-10-26T10:00:00Z",  # in the past
            },
        }
        f_exp = os.path.join(cache_dir, "expired_0")
        with open(f_exp, "wb") as fh:
            fh.write(json.dumps(expired_payload).encode("utf-8"))
        os.utime(f_exp, (now, now))

        res = quota_claude_cache.scan_claude_desktop_cache(now=now, cache_dir=cache_dir)
        self.assertIsNone(res)

    def test_claude_desktop_cache_garbage_files_ignored(self):
        now = 1730000000.0
        cache_dir = os.path.join(self.tmp, "claude_cache_garbage")
        os.makedirs(cache_dir, exist_ok=True)

        # Unrelated binary files, corrupt gzip, empty files
        with open(os.path.join(cache_dir, "empty_0"), "wb") as fh:
            pass
        with open(os.path.join(cache_dir, "corrupt_gz_0"), "wb") as fh:
            fh.write(b"\x1f\x8b\x08corrupt_bytes_here")
        with open(os.path.join(cache_dir, "random_0"), "wb") as fh:
            fh.write(b"NOT_JSON_OR_USAGE" * 50)

        res = quota_claude_cache.scan_claude_desktop_cache(now=now, cache_dir=cache_dir)
        self.assertIsNone(res)

    def test_fetch_claude_quota_falls_back_to_desktop_cache(self):
        now = 1730000000.0
        cache_dir = os.path.join(self.tmp, "claude_cache_fallback")
        os.makedirs(cache_dir, exist_ok=True)

        payload = {
            "five_hour": {
                "utilization": 12.0,
                "resets_at": "2024-10-27T08:00:00Z",
            },
            "seven_day": {
                "utilization": 60.0,
                "resets_at": "2024-10-31T10:00:00Z",
            },
        }
        f_cache = os.path.join(cache_dir, "entry_0")
        with open(f_cache, "wb") as fh:
            fh.write(b"HTTP/1.1 200 OK\r\n\r\n" + json.dumps(payload).encode("utf-8"))
        os.utime(f_cache, (now, now))

        with mock.patch.dict(os.environ, {"KANJO_CLAUDE_CACHE_DIR": cache_dir}):
            # Live API credentials fail / return None (e.g. empty keychain token)
            with mock.patch.object(quota_fetch, "_load_claude_credentials", return_value=None):
                res = quota_fetch.fetch_claude_quota(now=now)

        self.assertIsNotNone(res)
        self.assertEqual(res["weekly_used_percent"], 60.0)
        self.assertEqual(res["five_hour_used_percent"], 12.0)
        self.assertEqual(res["weekly_resets_at"], "2024-10-31T10:00:00Z")
        self.assertEqual(res["five_hour_resets_at"], "2024-10-27T08:00:00Z")
        self.assertEqual(res["source"], "live")


if __name__ == "__main__":
    unittest.main()
