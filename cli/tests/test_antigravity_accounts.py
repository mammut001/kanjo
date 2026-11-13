"""Tests for Antigravity Google account attribution and `kanjo accounts`."""

import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from kanjo import antigravity_accounts, cli, export
from kanjo.antigravity_accounts import (
    AntigravityAccountIndex, LaunchSpan, get_account_index, list_accounts,
    parse_log_file, reset_account_index,
)
from kanjo.sources.base import Message, Session, local_zone


def write_log(path, content, mtime=None):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    else:
        lines = [line for line in content.splitlines() if line.startswith(("I", "W", "E", "F"))]
        if lines:
            import re
            from kanjo.sources.base import local_zone
            gm = re.match(r"^[IWEF](\d{2})(\d{2})\s+(\d{2}):(\d{2}):(\d{2})", lines[-1])
            if gm:
                fn_m = re.search(r"(\d{4})(\d{2})", os.path.basename(path))
                start_year = int(fn_m.group(1)) if fn_m else 2026
                start_month = int(fn_m.group(2)) if fn_m else 11
                l_m, l_d, l_h, l_mi, l_s = (int(gm.group(i)) for i in range(1, 6))
                l_year = start_year + 1 if (start_month == 12 and l_m == 1) else start_year
                t = datetime(l_year, l_m, l_d, l_h, l_mi, l_s, tzinfo=local_zone()).timestamp()
                os.utime(path, (t, t))


class AntigravityLogParsingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-test-log-")
        reset_account_index()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_account_index()

    def test_log_parsing_email_and_conversation_lines(self):
        # cli-YYYYMMDD_HHMMSS.log
        log_path = os.path.join(self.tmp, "cli-20261112_120000.log")
        cid_created = "9e60b0f4-c279-4f0e-a098-0ce2d7c1bc19"
        cid_active = "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"
        cid_inactive = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        random_path_uuid = "12345678-1234-1234-1234-123456789abc"

        content = f"""I1112 12:00:01.123456       1 server.go:100] Server started
I1112 12:00:02.234567       1 server_oauth.go:221] applyAuthResult: email=Alice.Doe@gmail.com, authMethod=consumer, quotaProject=
I1112 12:01:00.345678       1 server.go:1233] Created conversation {cid_created} (backend=BACKEND_TYPE_UNSPECIFIED)
I1112 12:01:05.456789       1 server.go:3366] GetConversationDetail: found conversation {cid_active} (active=true)
I1112 12:01:10.567890       1 server.go:3366] GetConversationDetail: found conversation {cid_inactive} (active=false)
I1112 12:01:15.678901       1 tool.go:50] Reading file /tmp/{random_path_uuid}/test.txt
I1112 12:05:00.789012       1 server.go:500] Shutting down
"""
        tz = local_zone()
        expected_end = datetime(2026, 11, 12, 12, 5, 0, 789012, tzinfo=tz).timestamp()
        write_log(log_path, content, mtime=expected_end)

        span = parse_log_file(log_path)
        self.assertIsNotNone(span)
        self.assertEqual(span.emails, {"alice.doe@gmail.com"})
        # Created and active=true are counted; active=false and path UUIDs are ignored
        self.assertIn(cid_created.lower(), span.conversations)
        self.assertIn(cid_active.lower(), span.conversations)
        self.assertNotIn(cid_inactive.lower(), span.conversations)
        self.assertNotIn(random_path_uuid.lower(), span.conversations)
        self.assertEqual(len(span.conversations), 2)

        # Check start time derived from filename 2026-11-12 12:00:00
        tz = local_zone()
        expected_start = datetime(2026, 11, 12, 12, 0, 0, tzinfo=tz).timestamp()
        self.assertEqual(span.start, expected_start)
        # Check end time matches last glog line
        expected_end = datetime(2026, 11, 12, 12, 5, 0, 789012, tzinfo=tz).timestamp()
        self.assertEqual(span.end, expected_end)

    def test_log_parsing_year_rollover(self):
        # Filename starts on Dec 31
        log_path = os.path.join(self.tmp, "cli-20261231_235950.log")
        content = """I1231 23:59:55.100000       1 server.go:1] Launching
I0101 00:00:05.200000       1 server.go:2] New Year started
"""
        tz = local_zone()
        expected_start = datetime(2026, 12, 31, 23, 59, 50, tzinfo=tz).timestamp()
        expected_end = datetime(2027, 1, 1, 0, 0, 5, 200000, tzinfo=tz).timestamp()
        write_log(log_path, content, mtime=expected_end)

        span = parse_log_file(log_path)
        self.assertIsNotNone(span)
        self.assertEqual(span.start, expected_start)
        self.assertEqual(span.end, expected_end)


class AntigravityAttributionRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-test-attr-")
        self.log_dir = os.path.join(self.tmp, "log")
        os.makedirs(self.log_dir, exist_ok=True)
        reset_account_index()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_account_index()

    def test_per_message_attribution_conversation_across_two_launches(self):
        # Conversation C1 continued across two launches under different accounts
        cid = "c1111111-1111-1111-1111-111111111111"

        # Launch 1: Alice, 2026-11-12 10:00:00 to 10:10:00
        l1 = os.path.join(self.log_dir, "cli-20261112_100000.log")
        write_log(l1, f"""I1112 10:00:01.000000 1 server_oauth.go:221] applyAuthResult: email=alice@gmail.com
I1112 10:00:02.000000 1 server.go:1233] Created conversation {cid}
I1112 10:10:00.000000 1 server.go:500] Exit
""")

        # Launch 2: Bob, 2026-11-12 14:00:00 to 14:10:00
        l2 = os.path.join(self.log_dir, "cli-20261112_140000.log")
        write_log(l2, f"""I1112 14:00:01.000000 1 server_oauth.go:221] applyAuthResult: email=bob@gmail.com
I1112 14:00:02.000000 1 server.go:3366] GetConversationDetail: found conversation {cid} (active=true)
I1112 14:10:00.000000 1 server.go:500] Exit
""")

        idx = AntigravityAccountIndex(dirs=[self.log_dir], cache_dir=self.tmp)

        tz = local_zone()
        ts_alice = datetime(2026, 11, 12, 10, 5, 0, tzinfo=tz).timestamp()
        ts_bob = datetime(2026, 11, 12, 14, 5, 0, tzinfo=tz).timestamp()
        ts_outside = datetime(2026, 11, 12, 12, 0, 0, tzinfo=tz).timestamp()

        self.assertEqual(idx.attribute(cid, ts_alice), "alice@gmail.com")
        self.assertEqual(idx.attribute(cid, ts_bob), "bob@gmail.com")
        self.assertIsNone(idx.attribute(cid, ts_outside))

    def test_print_mode_launch_without_conversation_id(self):
        # Launch in print mode: has email but NO conversation ID
        l = os.path.join(self.log_dir, "cli-20261112_110000.log")
        write_log(l, """I1112 11:00:01.000000 1 server_oauth.go:221] applyAuthResult: email=charlie@gmail.com
I1112 11:05:00.000000 1 server.go:500] Exit
""")

        idx = AntigravityAccountIndex(dirs=[self.log_dir], cache_dir=self.tmp)

        tz = local_zone()
        # Any conversation during this time window should attribute to charlie
        ts_inside = datetime(2026, 11, 12, 11, 2, 0, tzinfo=tz).timestamp()
        ts_edge = datetime(2026, 11, 12, 11, 5, 45, tzinfo=tz).timestamp()  # within 60s
        ts_far = datetime(2026, 11, 12, 11, 8, 0, tzinfo=tz).timestamp()

        self.assertEqual(idx.attribute("any-conversation-id", ts_inside), "charlie@gmail.com")
        self.assertEqual(idx.attribute("any-conversation-id", ts_edge), "charlie@gmail.com")
        self.assertIsNone(idx.attribute("any-conversation-id", ts_far))

    def test_overlapping_launches_different_emails_no_conversation_returns_none(self):
        # Two overlapping launches with different emails and no conversation IDs
        l1 = os.path.join(self.log_dir, "cli-20261112_150000.log")
        write_log(l1, """I1112 15:00:01.000000 1 server_oauth.go:221] applyAuthResult: email=alice@gmail.com
I1112 15:30:00.000000 1 server.go:500] Exit
""")

        l2 = os.path.join(self.log_dir, "cli-20261112_151000.log")
        write_log(l2, """I1112 15:10:01.000000 1 server_oauth.go:221] applyAuthResult: email=bob@gmail.com
I1112 15:40:00.000000 1 server.go:500] Exit
""")

        idx = AntigravityAccountIndex(dirs=[self.log_dir], cache_dir=self.tmp)

        tz = local_zone()
        # At 15:20, both are active -> cannot guess between alice and bob -> None
        ts_overlap = datetime(2026, 11, 12, 15, 20, 0, tzinfo=tz).timestamp()
        self.assertIsNone(idx.attribute("random-conv", ts_overlap))

    def test_overlapping_launches_same_email(self):
        # Two overlapping launches with the SAME email and no conversation IDs
        l1 = os.path.join(self.log_dir, "cli-20261112_160000.log")
        write_log(l1, """I1112 16:00:01.000000 1 server_oauth.go:221] applyAuthResult: email=alice@gmail.com
I1112 16:30:00.000000 1 server.go:500] Exit
""")

        l2 = os.path.join(self.log_dir, "cli-20261112_161000.log")
        write_log(l2, """I1112 16:10:01.000000 1 server_oauth.go:221] applyAuthResult: email=alice@gmail.com
I1112 16:40:00.000000 1 server.go:500] Exit
""")

        idx = AntigravityAccountIndex(dirs=[self.log_dir], cache_dir=self.tmp)

        tz = local_zone()
        ts_overlap = datetime(2026, 11, 12, 16, 20, 0, tzinfo=tz).timestamp()
        self.assertEqual(idx.attribute("random-conv", ts_overlap), "alice@gmail.com")

    def test_no_log_dir_returns_none_everywhere(self):
        idx = AntigravityAccountIndex(dirs=[os.path.join(self.tmp, "nonexistent")], cache_dir=self.tmp)
        self.assertIsNone(idx.attribute("conv-1", 1700000000.0))
        self.assertIsNone(idx.get_current_account())

    def test_persistent_cache_speed_and_invalidation(self):
        l1 = os.path.join(self.log_dir, "cli-20261112_170000.log")
        write_log(l1, """I1112 17:00:01.000000 1 server_oauth.go:221] applyAuthResult: email=cached@gmail.com
I1112 17:10:00.000000 1 server.go:500] Exit
""")

        # First run builds cache
        idx1 = AntigravityAccountIndex(dirs=[self.log_dir], cache_dir=self.tmp)
        self.assertEqual(len(idx1.spans), 1)

        cache_file = os.path.join(self.tmp, "antigravity-logs-cache-v1.json")
        self.assertTrue(os.path.exists(cache_file))

        # Second run reads from cache
        with mock.patch("kanjo.antigravity_accounts.parse_log_file") as mock_parse:
            idx2 = AntigravityAccountIndex(dirs=[self.log_dir], cache_dir=self.tmp)
            mock_parse.assert_not_called()
            self.assertEqual(len(idx2.spans), 1)
            self.assertEqual(idx2.get_current_account(), "cached@gmail.com")


class KanjoAccountsCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-test-cmd-")
        reset_account_index()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_account_index()

    def test_list_accounts_aggregation(self):
        s1 = Session(id="s1", agent="antigravity", file="/f1")
        s1.messages = [
            Message(ts=1000.0, model="gemini-pro", input=100, output=50, account="alice@gmail.com"),
            Message(ts=2000.0, model="gemini-pro", input=200, output=100, account="alice@gmail.com"),
        ]
        s2 = Session(id="s2", agent="antigravity", file="/f2")
        s2.messages = [
            Message(ts=1500.0, model="gemini-pro", input=500, output=200, account="bob@gmail.com"),
            Message(ts=3000.0, model="gemini-pro", input=50, output=20, account=None),
        ]
        # Another agent should be ignored
        s3 = Session(id="s3", agent="claude", file="/f3")
        s3.messages = [Message(ts=1000.0, model="claude-3-5-sonnet", input=1000, output=500, account="other@gmail.com")]

        rows = list_accounts([s1, s2, s3])
        # Alice (2 msgs), Bob (1 msg), Unknown (1 msg)
        self.assertEqual(len(rows), 3)

        row_alice = next(r for r in rows if r["account"] == "alice@gmail.com")
        self.assertEqual(row_alice["messages"], 2)
        self.assertEqual(row_alice["tokens"], 450)
        self.assertIsNotNone(row_alice["first_seen"])
        self.assertIsNotNone(row_alice["last_seen"])

        row_bob = next(r for r in rows if r["account"] == "bob@gmail.com")
        self.assertEqual(row_bob["messages"], 1)
        self.assertEqual(row_bob["tokens"], 700)

        row_unknown = rows[-1]
        self.assertEqual(row_unknown["account"], "unknown")
        self.assertEqual(row_unknown["messages"], 1)
        self.assertEqual(row_unknown["tokens"], 70)

    def test_kanjo_accounts_cli_table_and_json(self):
        # Mock scan to return a session with known and unknown messages
        s = Session(id="s1", agent="antigravity", file="/f1")
        s.messages = [
            Message(ts=1730000000.0, model="gemini-pro", input=100, output=100, account="alice@gmail.com"),
            Message(ts=1730000100.0, model="gemini-pro", input=50, output=50, account=None),
        ]
        scan_res = export.ScanResult(sessions=[s], failed_files=[], stats={})

        with mock.patch("kanjo.cli.scan", return_value=scan_res):
            # 1. Text table
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = cli.main(["accounts"])
            self.assertEqual(code, 0)
            text = out.getvalue()
            self.assertIn("Account", text)
            self.assertIn("Messages", text)
            self.assertIn("Total Tokens", text)
            self.assertIn("alice@gmail.com", text)
            self.assertIn("unknown", text)

            # 2. JSON
            out_json = io.StringIO()
            with mock.patch("sys.stdout", out_json):
                code = cli.main(["accounts", "--json"])
            self.assertEqual(code, 0)
            data = json.loads(out_json.getvalue())
            self.assertIsInstance(data, list)
            accounts = [d["account"] for d in data]
            self.assertIn("alice@gmail.com", accounts)
            self.assertEqual(data[-1]["account"], "unknown")
