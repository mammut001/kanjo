"""Tests for Antigravity login management, switcher, and backend safety."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from kanjo.agy_login import (
    KeychainBackend,
    SecurityKeychainBackend,
    forget,
    get_slot_owner,
    list_accounts_login,
    set_backend,
    switch,
    sync,
)
from kanjo.antigravity_accounts import AntigravityAccountIndex, LaunchSpan


class FakeKeychainBackend(KeychainBackend):
    def __init__(self, slot=None, slot_mdat=None, saved=None):
        self.slot = slot
        self.slot_mdat = slot_mdat
        self.saved = dict(saved or {})
        self.write_slot_calls = []
        self.write_saved_calls = []

    def read_slot(self):
        return self.slot

    def write_slot(self, secret: bytes):
        self.write_slot_calls.append(secret)
        self.slot = secret
        self.slot_mdat = 999999.0

    def slot_modified_at(self):
        return self.slot_mdat

    def read_saved(self, email: str):
        return self.saved.get(email.lower())

    def write_saved(self, email: str, secret: bytes):
        self.write_saved_calls.append((email.lower(), secret))
        self.saved[email.lower()] = secret

    def delete_saved(self, email: str):
        self.saved.pop(email.lower(), None)

    def list_saved(self):
        return sorted(self.saved.keys())


class FakeAccountIndex:
    def __init__(self, spans=None, current=None):
        self.spans = spans or []
        self._current = current

    def get_current_account(self):
        return self._current


class AgyLoginTest(unittest.TestCase):
    def tearDown(self):
        set_backend(None)

    def test_owner_detection_by_mdat_vs_launch_start(self):
        # Spans:
        # span 1: start 100, authenticated alice
        # mdat: 150
        # span 2: start 200, unauthenticated (no email)
        # span 3: start 300, authenticated bob
        # span 4: start 400, authenticated charlie
        s1 = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=100.5)
        s2 = LaunchSpan(path="cli-2.log", start=200.0, end=210.0, emails=set(), auth_ts=200.5)
        s3 = LaunchSpan(path="cli-3.log", start=300.0, end=310.0, emails={"bob@example.com"}, auth_ts=300.5)
        s4 = LaunchSpan(path="cli-4.log", start=400.0, end=410.0, emails={"charlie@example.com"}, auth_ts=400.5)

        idx = FakeAccountIndex(spans=[s1, s2, s3, s4])

        # Backend with mdat at 150 -> earliest authenticated after 150 is s3 (bob)
        backend = FakeKeychainBackend(slot_mdat=150.0)
        self.assertEqual(get_slot_owner(backend, idx), "bob@example.com")

        # Backend with mdat at 350 -> earliest authenticated is s4 (charlie)
        backend = FakeKeychainBackend(slot_mdat=350.0)
        self.assertEqual(get_slot_owner(backend, idx), "charlie@example.com")

        # Backend with mdat at 500 -> no spans after 500 -> None (unknown)
        backend = FakeKeychainBackend(slot_mdat=500.0)
        self.assertIsNone(get_slot_owner(backend, idx))

        # Backend with mdat None -> None
        backend = FakeKeychainBackend(slot_mdat=None)
        self.assertIsNone(get_slot_owner(backend, idx))

        # Ambiguous span with multiple emails -> returns None (never guess)
        s_amb = LaunchSpan(path="cli-amb.log", start=250.0, end=260.0, emails={"x@a.com", "y@b.com"}, auth_ts=250.5)
        idx_amb = FakeAccountIndex(spans=[s1, s_amb, s3])
        backend = FakeKeychainBackend(slot_mdat=150.0)
        self.assertIsNone(get_slot_owner(backend, idx_amb))

    def test_sync_writes_only_when_changed(self):
        s1 = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=100.5)
        idx = FakeAccountIndex(spans=[s1])

        # 1. Slot owner is alice, slot has new bytes b"token_v2", saved has b"token_v1"
        backend = FakeKeychainBackend(slot=b"token_v2", slot_mdat=50.0, saved={"alice@example.com": b"token_v1"})
        res = sync(backend, idx)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["synced"])
        self.assertEqual(res["account"], "alice@example.com")
        self.assertEqual(backend.read_saved("alice@example.com"), b"token_v2")
        self.assertEqual(len(backend.write_saved_calls), 1)

        # 2. Sync again when bytes are identical -> does not write
        res2 = sync(backend, idx)
        self.assertEqual(res2["status"], "ok")
        self.assertFalse(res2["synced"])
        self.assertEqual(len(backend.write_saved_calls), 1)

        # 3. Owner unknown -> does not write
        backend_unknown = FakeKeychainBackend(slot=b"token_new", slot_mdat=200.0)
        res3 = sync(backend_unknown, idx)
        self.assertEqual(res3["status"], "ok")
        self.assertFalse(res3["synced"])
        self.assertEqual(len(backend_unknown.write_saved_calls), 0)

    def test_switch_happy_path(self):
        # Alice is current in slot with refreshed token
        s1 = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=100.5)
        idx = FakeAccountIndex(spans=[s1])
        backend = FakeKeychainBackend(
            slot=b"alice_new_token",
            slot_mdat=50.0,
            saved={"alice@example.com": b"alice_old_token", "bob@example.com": b"bob_saved_token"},
        )

        # Switch to Bob
        code, res = switch("bob@example.com", backend, idx)
        self.assertEqual(code, 0)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["account"], "bob@example.com")
        self.assertIn("running agy sessions keep their old account", res["note"])

        # Check Alice's token was synced first
        self.assertEqual(backend.read_saved("alice@example.com"), b"alice_new_token")
        # Check Slot now has Bob's token
        self.assertEqual(backend.read_slot(), b"bob_saved_token")

    def test_switch_refuses_to_clobber_unsaved_login(self):
        # Slot owner is unknown, slot has b"unsaved_secret", no saved copy matches it
        s1 = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=100.5)
        idx = FakeAccountIndex(spans=[s1])
        backend = FakeKeychainBackend(
            slot=b"unsaved_secret",
            slot_mdat=200.0,  # after s1, so owner unknown
            saved={"bob@example.com": b"bob_secret"},
        )

        code, res = switch("bob@example.com", backend, idx)
        self.assertEqual(code, 1)
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error"], "unsaved_login")
        self.assertIn("current login is not saved yet; run agy once and refresh Kanjo", res["message"])
        # Slot must remain untouched
        self.assertEqual(backend.read_slot(), b"unsaved_secret")

    def test_switch_allows_when_unknown_owner_matches_a_saved_copy(self):
        # Slot owner unknown, but slot bytes match an existing saved copy (e.g. earlier switch)
        s1 = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=100.5)
        idx = FakeAccountIndex(spans=[s1])
        backend = FakeKeychainBackend(
            slot=b"alice_secret",
            slot_mdat=200.0,  # after s1, owner unknown
            saved={"alice@example.com": b"alice_secret", "bob@example.com": b"bob_secret"},
        )

        code, res = switch("bob@example.com", backend, idx)
        self.assertEqual(code, 0)
        self.assertEqual(backend.read_slot(), b"bob_secret")

    def test_switch_missing_saved_copy(self):
        s1 = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=100.5)
        idx = FakeAccountIndex(spans=[s1])
        backend = FakeKeychainBackend(
            slot=b"alice_secret",
            slot_mdat=50.0,
            saved={"alice@example.com": b"alice_secret"},
        )

        code, res = switch("carol@example.com", backend, idx)
        self.assertEqual(code, 1)
        self.assertEqual(res["error"], "no_saved_login")
        self.assertIn("no saved login for carol@example.com", res["message"])

    def test_read_back_mismatch_restores_previous(self):
        s1 = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=100.5)
        idx = FakeAccountIndex(spans=[s1])

        class FlakyBackend(FakeKeychainBackend):
            def write_slot(self, secret: bytes):
                # Flaky: writes corrupted bytes
                self.slot = b"corrupted"

        backend = FlakyBackend(
            slot=b"alice_secret",
            slot_mdat=50.0,
            saved={"alice@example.com": b"alice_secret", "bob@example.com": b"bob_secret"},
        )

        code, res = switch("bob@example.com", backend, idx)
        self.assertEqual(code, 1)
        self.assertEqual(res["error"], "verification_failed")
        self.assertIn("read-back mismatch after writing slot; restored previous login", res["message"])

    def test_list_and_forget(self):
        s1 = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=100.5)
        idx = FakeAccountIndex(spans=[s1], current="alice@example.com")
        backend = FakeKeychainBackend(
            saved={"alice@example.com": b"t1", "bob@example.com": b"t2"}
        )

        code, res = list_accounts_login(backend, idx)
        self.assertEqual(code, 0)
        self.assertEqual(res["current"], "alice@example.com")
        accounts = res["accounts"]
        self.assertEqual(len(accounts), 2)
        alice_row = next(a for a in accounts if a["email"] == "alice@example.com")
        bob_row = next(a for a in accounts if a["email"] == "bob@example.com")
        self.assertTrue(alice_row["saved_login"])
        self.assertTrue(alice_row["current"])
        self.assertTrue(bob_row["saved_login"])
        self.assertFalse(bob_row["current"])

        # Forget Bob
        code2, res2 = forget("bob@example.com", backend)
        self.assertEqual(code2, 0)
        self.assertEqual(res2["action"], "forgotten")
        self.assertNotIn("bob@example.com", backend.list_saved())

    def test_secret_safety_in_subprocess_argv_and_output(self):
        """Assert secrets NEVER appear in argv of subprocess calls and never in error text."""
        secret_bytes = b"SUPER_SECRET_TOKEN_DO_NOT_LEAK_12345"
        captured_calls = []

        def fake_run(args, **kwargs):
            captured_calls.append((list(args), kwargs))
            # If find-generic-password with -w, return secret
            if "find-generic-password" in args and "-w" in args:
                return subprocess.CompletedProcess(args, 0, stdout=secret_bytes + b"\n", stderr=b"")
            # If -i, return error or success
            if "-i" in args:
                return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
            if "dump-keychain" in args:
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        backend = SecurityKeychainBackend(security_bin="/fake/bin/security")

        with patch("subprocess.run", side_effect=fake_run):
            backend.write_slot(secret_bytes)

            # Inspect all captured argv calls: NONE of them may contain the secret
            for argv, kwargs in captured_calls:
                for arg in argv:
                    self.assertNotIn(
                        secret_bytes.decode(),
                        str(arg),
                        f"Secret leaked into argv: {argv}",
                    )
                # Confirm -i command carried the secret on stdin
                if "-i" in argv:
                    stdin_input = kwargs.get("input", b"")
                    self.assertIn(secret_bytes, stdin_input)

        # Test failure exception doesn't leak secret
        def fail_run(args, **kwargs):
            return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"SecKeychainItemCreate failed")

        with patch("subprocess.run", side_effect=fail_run):
            try:
                backend.write_slot(secret_bytes)
                self.fail("should have raised RuntimeError")
            except RuntimeError as exc:
                self.assertNotIn(secret_bytes.decode(), str(exc))

    def test_cli_command_agy_account_dispatch(self):
        from kanjo.cli import main

        backend = FakeKeychainBackend(
            slot=b"alice_secret",
            slot_mdat=50.0,
            saved={"alice@example.com": b"alice_secret", "bob@example.com": b"bob_secret"},
        )
        set_backend(backend)

        s1 = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=100.5)
        with patch("kanjo.antigravity_accounts.get_account_index", return_value=FakeAccountIndex(spans=[s1], current="alice@example.com")):
            # Test list --json
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                ret = main(["agy-account", "list", "--json"])
            self.assertEqual(ret, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["status"], "ok")
            self.assertEqual(len(data["accounts"]), 2)

            # Test switch --json
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                ret = main(["agy-account", "switch", "bob@example.com", "--json"])
            self.assertEqual(ret, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["account"], "bob@example.com")
            self.assertEqual(backend.read_slot(), b"bob_secret")

    def test_same_second_race(self):
        # 1. Span start in mdat second with old email, but auth_ts < mdat (loaded before write):
        # Later span has auth_ts >= mdat + 1.0 with new email -> owner = new email.
        backend = FakeKeychainBackend(slot_mdat=100.0)
        s1 = LaunchSpan(path="cli-1.log", start=100.2, end=110.0, emails={"alice@example.com"}, auth_ts=99.8)
        s2 = LaunchSpan(path="cli-2.log", start=102.0, end=112.0, emails={"bob@example.com"}, auth_ts=102.5)
        idx = FakeAccountIndex(spans=[s1, s2])
        self.assertEqual(get_slot_owner(backend, idx), "bob@example.com")

        # 2. Span auth inside mdat second with same email as qualifying span -> owner = new email
        s1_same = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"bob@example.com"}, auth_ts=100.5)
        idx_same = FakeAccountIndex(spans=[s1_same, s2])
        self.assertEqual(get_slot_owner(backend, idx_same), "bob@example.com")

        # 3. Span auth inside mdat second with old email (different from qualifying span):
        # Per rule 2: "Spans with auth_ts inside [mdat, mdat+1) are ambiguous: if any such
        # span exists with a DIFFERENT email than the first qualifying span, return None. Never guess."
        s1_amb = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=100.5)
        idx_amb = FakeAccountIndex(spans=[s1_amb, s2])
        self.assertIsNone(get_slot_owner(backend, idx_amb))

    def test_only_ambiguous_spans(self):
        # Only spans with auth_ts inside [mdat, mdat + 1.0) and no span >= mdat + 1.0 -> None
        backend = FakeKeychainBackend(slot_mdat=100.0)
        s1 = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=100.5)
        idx = FakeAccountIndex(spans=[s1])
        self.assertIsNone(get_slot_owner(backend, idx))

    def test_sync_refuses_when_slot_equals_another_account(self):
        # Slot owner is alice, slot bytes match bob's saved copy -> sync refuses
        s1 = LaunchSpan(path="cli-1.log", start=100.0, end=110.0, emails={"alice@example.com"}, auth_ts=102.0)
        idx = FakeAccountIndex(spans=[s1])
        backend = FakeKeychainBackend(
            slot=b"bob_secret",
            slot_mdat=100.0,
            saved={"alice@example.com": b"alice_old", "bob@example.com": b"bob_secret"},
        )
        res = sync(backend, idx)
        self.assertEqual(res["status"], "ok")
        self.assertFalse(res["synced"])
        self.assertEqual(res["reason"], "slot matches another account")
        # Alice's saved copy must NOT be overwritten with Bob's secret
        self.assertEqual(backend.read_saved("alice@example.com"), b"alice_old")

    def test_non_keyring_auth_spans_ignored(self):
        # Spans whose email came from another auth path (auth_ts is None) are ignored for slot ownership
        backend = FakeKeychainBackend(slot_mdat=100.0)
        s_oauth = LaunchSpan(path="cli-1.log", start=102.0, end=110.0, emails={"alice@example.com"}, auth_ts=None)
        idx = FakeAccountIndex(spans=[s_oauth])
        self.assertIsNone(get_slot_owner(backend, idx))

    def test_switch_no_op_when_slot_already_matches_target(self):
        backend = FakeKeychainBackend(
            slot=b"bob_secret",
            slot_mdat=100.0,
            saved={"bob@example.com": b"bob_secret"},
        )
        code, res = switch("bob@example.com", backend, FakeAccountIndex())
        self.assertEqual(code, 0)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(backend.write_slot_calls), 0)

    def test_parse_log_file_keyring_auth_ts(self):
        from kanjo.antigravity_accounts import parse_log_file
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Has keyringAuth line -> auth_ts is sub-second timestamp of that line
            log1 = os.path.join(tmpdir, "cli-20261112_120000.log")
            with open(log1, "w") as f:
                f.write("I1112 12:00:01.123456 1 auth.go:100] keyringAuth: loaded token\n")
                f.write("I1112 12:00:02.654321 1 server_oauth.go:221] applyAuthResult: email=alice@example.com\n")
            span1 = parse_log_file(log1)
            self.assertIsNotNone(span1.auth_ts)
            self.assertEqual(span1.emails, {"alice@example.com"})

            # 2. Has keyringAuth without glog ts -> falls back to applyAuthResult ts
            log2 = os.path.join(tmpdir, "cli-20261112_130000.log")
            with open(log2, "w") as f:
                f.write("keyringAuth: loaded token\n")
                f.write("I1112 13:00:05.500000 1 server_oauth.go:221] applyAuthResult: email=bob@example.com\n")
            span2 = parse_log_file(log2)
            self.assertIsNotNone(span2.auth_ts)
            self.assertEqual(span2.emails, {"bob@example.com"})

            # 3. No keyringAuth line (another auth path, e.g. web oauth) -> auth_ts is None
            log3 = os.path.join(tmpdir, "cli-20261112_140000.log")
            with open(log3, "w") as f:
                f.write("I1112 14:00:05.500000 1 server_oauth.go:221] applyAuthResult: email=charlie@example.com\n")
            span3 = parse_log_file(log3)
            self.assertIsNone(span3.auth_ts)
            self.assertEqual(span3.emails, {"charlie@example.com"})


if __name__ == "__main__":
    unittest.main()
