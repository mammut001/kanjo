"""Tests for Antigravity login management, switcher, and backend safety."""

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from kanjo.agy_login import (
    KeychainBackend,
    SecurityKeychainBackend,
    _record_slot_write,
    count_running_agy,
    forget,
    get_slot_owner,
    list_accounts_login,
    set_backend,
    switch,
    sync,
)
from kanjo.antigravity_accounts import LaunchSpan


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


def _span(path, start, end, auth_events=None, refresh_events=None):
    """Build a LaunchSpan from (ts, email, via) auth events and refresh timestamps."""
    auth_events = list(auth_events or [])
    emails = {email for _ts, email, _via in auth_events}
    return LaunchSpan(
        path=path,
        start=start,
        end=end,
        emails=emails,
        auth_events=auth_events,
        refresh_events=list(refresh_events or []),
    )


class AgyLoginOwnerTest(unittest.TestCase):
    """Slot-owner detection from the log events model."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-agy-owner-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_refresh_written_slot_single_long_running_process(self):
        # A long-running process loaded keyring as X, then silently refreshed
        # (rewriting the slot) exactly at mdat -> owner X.
        backend = FakeKeychainBackend(slot=b"x_refreshed", slot_mdat=150.0,
                                      saved={"x@example.com": b"x_old"})
        s = _span("cli-1.log", 100.0, 200.0,
                  auth_events=[(100.5, "x@example.com", "keyring")],
                  refresh_events=[150.0])
        idx = FakeAccountIndex(spans=[s])
        self.assertEqual(get_slot_owner(backend, idx), "x@example.com")

        # sync saves the silently refreshed token
        res = sync(backend, idx, cache_dir=self.tmp)
        self.assertTrue(res["synced"])
        self.assertEqual(res["account"], "x@example.com")
        self.assertEqual(backend.read_saved("x@example.com"), b"x_refreshed")

    def test_several_processes_only_one_refreshed_near_mdat(self):
        # Three running processes with different accounts; only X refreshed
        # within [mdat-5, mdat+2] -> owner X, never the others.
        backend = FakeKeychainBackend(slot=b"x_refreshed", slot_mdat=150.0)
        sx = _span("cli-1.log", 100.0, 400.0,
                   auth_events=[(100.5, "x@example.com", "keyring")], refresh_events=[150.0])
        sy = _span("cli-2.log", 110.0, 400.0,
                   auth_events=[(110.5, "y@example.com", "keyring")], refresh_events=[400.0])
        sz = _span("cli-3.log", 120.0, 400.0,
                   auth_events=[(120.5, "z@example.com", "keyring")])
        idx = FakeAccountIndex(spans=[sx, sy, sz])
        self.assertEqual(get_slot_owner(backend, idx), "x@example.com")

    def test_in_session_login_sequence_last_login_wins(self):
        # One process: keyring A, then /login B, then /login C. The slot was
        # written at C's login (mdat) -> owner C.
        backend = FakeKeychainBackend(slot=b"c_token", slot_mdat=250.0)
        s = _span("cli-1.log", 100.0, 300.0,
                  auth_events=[(100.5, "a@example.com", "keyring"),
                               (200.0, "b@example.com", "login"),
                               (250.0, "c@example.com", "login")])
        idx = FakeAccountIndex(spans=[s])
        self.assertEqual(get_slot_owner(backend, idx), "c@example.com")

    def test_keyring_launch_after_mdat(self):
        # A launch that started after mdat loaded the token via keyring ->
        # its email owns the slot (keyring evidence rule).
        backend = FakeKeychainBackend(slot=b"w_token", slot_mdat=150.0)
        s = _span("cli-1.log", 160.0, 300.0,
                  auth_events=[(160.5, "w@example.com", "keyring")])
        idx = FakeAccountIndex(spans=[s])
        self.assertEqual(get_slot_owner(backend, idx), "w@example.com")

    def test_rules_disagree_returns_none(self):
        # A login near mdat says X; a keyring launch after mdat says Y -> unknown.
        backend = FakeKeychainBackend(slot=b"tok", slot_mdat=150.0)
        s_login = _span("cli-1.log", 100.0, 300.0,
                        auth_events=[(100.5, "a@example.com", "keyring"),
                                     (150.0, "x@example.com", "login")])
        s_keyring = _span("cli-2.log", 160.0, 300.0,
                          auth_events=[(160.5, "y@example.com", "keyring")])
        idx = FakeAccountIndex(spans=[s_login, s_keyring])
        self.assertIsNone(get_slot_owner(backend, idx))

    def test_candidates_disagree_returns_none(self):
        # Two logins near mdat by different accounts -> never guess.
        backend = FakeKeychainBackend(slot=b"tok", slot_mdat=150.0)
        s1 = _span("cli-1.log", 100.0, 300.0, auth_events=[(150.0, "x@example.com", "login")])
        s2 = _span("cli-2.log", 100.0, 300.0, auth_events=[(151.0, "y@example.com", "login")])
        idx = FakeAccountIndex(spans=[s1, s2])
        self.assertIsNone(get_slot_owner(backend, idx))

    def test_no_slot_writing_events_returns_none(self):
        backend = FakeKeychainBackend(slot=b"tok", slot_mdat=150.0)
        s = _span("cli-1.log", 100.0, 300.0, auth_events=[(100.5, "x@example.com", "keyring")])
        idx = FakeAccountIndex(spans=[s])
        self.assertIsNone(get_slot_owner(backend, idx))

    def test_mdat_none_returns_none(self):
        backend = FakeKeychainBackend(slot_mdat=None)
        s = _span("cli-1.log", 100.0, 300.0,
                  auth_events=[(100.5, "x@example.com", "keyring")], refresh_events=[150.0])
        self.assertIsNone(get_slot_owner(backend, FakeAccountIndex(spans=[s])))

    def test_hash_record_wins_over_events(self):
        # A Kanjo switch wrote the slot; the recorded hash identifies the owner
        # even though a live process (X) refreshed around mdat.
        with tempfile.TemporaryDirectory() as tmp:
            backend = FakeKeychainBackend(slot=b"y_saved_token", slot_mdat=100.0,
                                          saved={"x@example.com": b"x_secret_token",
                                                 "y@example.com": b"y_saved_token"})
            _record_slot_write(b"y_saved_token", "y@example.com", cache_dir=tmp)
            s = _span("cli-1.log", 50.0, 500.0,
                      auth_events=[(50.5, "x@example.com", "keyring")], refresh_events=[100.0])
            idx = FakeAccountIndex(spans=[s])
            self.assertEqual(get_slot_owner(backend, idx, cache_dir=tmp), "y@example.com")

    def test_rules_agree_returns_owner(self):
        # Login near mdat (X) and a keyring launch after mdat (also X) agree.
        backend = FakeKeychainBackend(slot=b"tok", slot_mdat=150.0)
        s_login = _span("cli-1.log", 100.0, 300.0,
                        auth_events=[(100.5, "a@example.com", "keyring"),
                                     (150.0, "x@example.com", "login")])
        s_keyring = _span("cli-2.log", 160.0, 300.0,
                          auth_events=[(160.5, "x@example.com", "keyring")])
        idx = FakeAccountIndex(spans=[s_login, s_keyring])
        self.assertEqual(get_slot_owner(backend, idx), "x@example.com")


class AgyLoginSyncSwitchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-agy-sync-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sync_writes_only_when_changed_and_owner_known(self):
        backend = FakeKeychainBackend(slot=b"x_new", slot_mdat=150.0, saved={"x@example.com": b"x_old"})
        s = _span("cli-1.log", 100.0, 200.0,
                  auth_events=[(100.5, "x@example.com", "keyring")], refresh_events=[150.0])
        idx = FakeAccountIndex(spans=[s])

        res = sync(backend, idx, cache_dir=self.tmp)
        self.assertTrue(res["synced"])
        self.assertEqual(res["account"], "x@example.com")
        self.assertEqual(backend.read_saved("x@example.com"), b"x_new")
        self.assertEqual(len(backend.write_saved_calls), 1)

        # Bytes identical -> no second write.
        res2 = sync(backend, idx, cache_dir=self.tmp)
        self.assertFalse(res2["synced"])
        self.assertEqual(len(backend.write_saved_calls), 1)

        # Owner unknown -> no write.
        backend_unknown = FakeKeychainBackend(slot=b"mystery", slot_mdat=150.0)
        res3 = sync(backend_unknown, FakeAccountIndex(spans=[]), cache_dir=self.tmp)
        self.assertFalse(res3["synced"])
        self.assertEqual(res3["reason"], "slot owner unknown")
        self.assertEqual(len(backend_unknown.write_saved_calls), 0)

    def test_sync_refuses_when_slot_equals_another_account(self):
        # Slot owner is alice (refresh), but slot bytes equal bob's saved copy.
        backend = FakeKeychainBackend(slot=b"bob_secret", slot_mdat=150.0,
                                      saved={"alice@example.com": b"alice_old",
                                             "bob@example.com": b"bob_secret"})
        s = _span("cli-1.log", 100.0, 300.0,
                  auth_events=[(100.5, "alice@example.com", "keyring")], refresh_events=[150.0])
        res = sync(backend, FakeAccountIndex(spans=[s]), cache_dir=self.tmp)
        self.assertFalse(res["synced"])
        self.assertEqual(res["reason"], "slot matches another account")
        self.assertEqual(backend.read_saved("alice@example.com"), b"alice_old")

    def test_switch_happy_path(self):
        # Alice is current (her refreshed token, mdat matches her refresh).
        backend = FakeKeychainBackend(slot=b"alice_new_token", slot_mdat=150.0,
                                      saved={"alice@example.com": b"alice_old_token",
                                             "bob@example.com": b"bob_saved_token"})
        s = _span("cli-1.log", 100.0, 300.0,
                  auth_events=[(100.5, "alice@example.com", "keyring")], refresh_events=[150.0])
        idx = FakeAccountIndex(spans=[s])

        code, res = switch("bob@example.com", backend, idx, cache_dir=self.tmp, running_agy=0)
        self.assertEqual(code, 0)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["account"], "bob@example.com")
        self.assertEqual(res["running_agy"], 0)
        self.assertIn("token refresh", res["note"])
        # Alice's refreshed token was synced first, then the slot took Bob's.
        self.assertEqual(backend.read_saved("alice@example.com"), b"alice_new_token")
        self.assertEqual(backend.read_slot(), b"bob_saved_token")

    def test_switch_refuses_to_clobber_unsaved_login(self):
        backend = FakeKeychainBackend(slot=b"unsaved_secret", slot_mdat=150.0,
                                      saved={"bob@example.com": b"bob_secret"})
        s = _span("cli-1.log", 100.0, 200.0, auth_events=[(100.5, "x@example.com", "keyring")])
        idx = FakeAccountIndex(spans=[s])

        code, res = switch("bob@example.com", backend, idx, cache_dir=self.tmp, running_agy=0)
        self.assertEqual(code, 1)
        self.assertEqual(res["error"], "unsaved_login")
        self.assertIn("current login is not saved yet", res["message"])
        self.assertEqual(backend.read_slot(), b"unsaved_secret")

    def test_switch_allows_when_unknown_owner_matches_a_saved_copy(self):
        backend = FakeKeychainBackend(slot=b"alice_secret", slot_mdat=150.0,
                                      saved={"alice@example.com": b"alice_secret",
                                             "bob@example.com": b"bob_secret"})
        s = _span("cli-1.log", 100.0, 200.0, auth_events=[(100.5, "x@example.com", "keyring")])
        idx = FakeAccountIndex(spans=[s])

        code, res = switch("bob@example.com", backend, idx, cache_dir=self.tmp, running_agy=0)
        self.assertEqual(code, 0)
        self.assertEqual(backend.read_slot(), b"bob_secret")

    def test_switch_missing_saved_copy(self):
        backend = FakeKeychainBackend(slot=b"alice_secret", slot_mdat=150.0,
                                      saved={"alice@example.com": b"alice_secret"})
        s = _span("cli-1.log", 100.0, 300.0,
                  auth_events=[(100.5, "alice@example.com", "keyring")], refresh_events=[150.0])
        idx = FakeAccountIndex(spans=[s])

        code, res = switch("carol@example.com", backend, idx, cache_dir=self.tmp, running_agy=0)
        self.assertEqual(code, 1)
        self.assertEqual(res["error"], "no_saved_login")
        self.assertIn("no saved login for carol@example.com", res["message"])

    def test_read_back_mismatch_restores_previous(self):
        s = _span("cli-1.log", 100.0, 300.0,
                  auth_events=[(100.5, "alice@example.com", "keyring")], refresh_events=[150.0])

        class FlakyBackend(FakeKeychainBackend):
            def write_slot(self, secret: bytes):
                self.slot = b"corrupted"

        backend = FlakyBackend(slot=b"alice_secret", slot_mdat=150.0,
                               saved={"alice@example.com": b"alice_secret",
                                      "bob@example.com": b"bob_secret"})

        code, res = switch("bob@example.com", backend, FakeAccountIndex(spans=[s]),
                           cache_dir=self.tmp, running_agy=0)
        self.assertEqual(code, 1)
        self.assertEqual(res["error"], "verification_failed")
        self.assertIn("read-back mismatch", res["message"])

    def test_switch_no_op_when_slot_already_matches_target(self):
        backend = FakeKeychainBackend(slot=b"bob_secret", slot_mdat=150.0,
                                      saved={"bob@example.com": b"bob_secret"})
        code, res = switch("bob@example.com", backend, FakeAccountIndex(),
                           cache_dir=self.tmp, running_agy=2)
        self.assertEqual(code, 0)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["running_agy"], 2)
        self.assertEqual(len(backend.write_slot_calls), 0)

    def test_switch_counts_running_agy_by_default(self):
        backend = FakeKeychainBackend(slot=b"bob_secret", slot_mdat=150.0,
                                      saved={"bob@example.com": b"bob_secret"})
        with patch("kanjo.agy_login.count_running_agy", return_value=3):
            code, res = switch("bob@example.com", backend, FakeAccountIndex(), cache_dir=self.tmp)
        self.assertEqual(code, 0)
        self.assertEqual(res["running_agy"], 3)

    def test_list_and_forget(self):
        s = _span("cli-1.log", 100.0, 300.0,
                  auth_events=[(100.5, "alice@example.com", "keyring")], refresh_events=[150.0])
        idx = FakeAccountIndex(spans=[s], current="alice@example.com")
        backend = FakeKeychainBackend(saved={"alice@example.com": b"t1", "bob@example.com": b"t2"})

        code, res = list_accounts_login(backend, idx)
        self.assertEqual(code, 0)
        self.assertEqual(res["current"], "alice@example.com")
        self.assertIn("running_agy", res)
        accounts = res["accounts"]
        self.assertEqual(len(accounts), 2)
        alice_row = next(a for a in accounts if a["email"] == "alice@example.com")
        bob_row = next(a for a in accounts if a["email"] == "bob@example.com")
        self.assertTrue(alice_row["saved_login"])
        self.assertTrue(alice_row["current"])
        self.assertTrue(bob_row["saved_login"])
        self.assertFalse(bob_row["current"])

        code2, res2 = forget("bob@example.com", backend, cache_dir=self.tmp)
        self.assertEqual(code2, 0)
        self.assertEqual(res2["action"], "forgotten")
        self.assertNotIn("bob@example.com", backend.list_saved())

    def test_count_running_agy_uses_pgrep(self):
        from kanjo import agy_login
        with patch("subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0, stdout="123\n456\n", stderr="")) as m:
            self.assertEqual(agy_login.count_running_agy(), 2)
            self.assertEqual(m.call_args[0][0], ["pgrep", "-x", "agy"])
        # returncode 1 -> no matches -> 0
        with patch("subprocess.run",
                   return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="")):
            self.assertEqual(agy_login.count_running_agy(), 0)
        # unexpected returncode -> None
        with patch("subprocess.run",
                   return_value=subprocess.CompletedProcess([], 2, stdout="", stderr="")):
            self.assertIsNone(agy_login.count_running_agy())
        # exception -> None
        with patch("subprocess.run", side_effect=OSError("boom")):
            self.assertIsNone(agy_login.count_running_agy())

    def test_kanjo_switch_while_process_alive_hash_record_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = FakeKeychainBackend(slot=b"x_secret_token", slot_mdat=100.0,
                                          saved={"x@example.com": b"x_secret_token",
                                                 "y@example.com": b"y_saved_token"})
            s = _span("cli-1.log", 50.0, 500.0, auth_events=[(50.5, "x@example.com", "keyring")])
            idx = FakeAccountIndex(spans=[s])

            code, res = switch("y@example.com", backend, idx, cache_dir=tmp, running_agy=1)
            self.assertEqual(code, 0)
            self.assertEqual(backend.read_slot(), b"y_saved_token")

            # get_slot_owner identifies Y via the hash record despite live process X
            owner = get_slot_owner(backend, idx, slot_bytes=backend.read_slot(), cache_dir=tmp)
            self.assertEqual(owner, "y@example.com")

            # sync does NOT write Y's bytes into X's copy
            sync(backend, idx, cache_dir=tmp)
            self.assertEqual(backend.read_saved("x@example.com"), b"x_secret_token")
            self.assertEqual(backend.read_saved("y@example.com"), b"y_saved_token")

    @unittest.skipIf(sys.platform == "win32", "POSIX file modes do not apply on Windows")
    def test_state_file_permissions_and_no_secret_content(self):
        secret_token = b"TOP_SECRET_OAUTH_TOKEN_DO_NOT_WRITE_RAW_KEYRING_VALUE_12345"
        backend = FakeKeychainBackend(slot=b"prev_token", slot_mdat=50.0,
                                      saved={"x@example.com": b"prev_token",
                                             "y@example.com": secret_token})
        code, res = switch("y@example.com", backend, FakeAccountIndex(), cache_dir=self.tmp, running_agy=0)
        self.assertEqual(code, 0)

        state_file = os.path.join(self.tmp, "agy-slot-write.json")
        self.assertTrue(os.path.exists(state_file))

        st = os.stat(state_file)
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o600)

        with open(state_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("TOP_SECRET", content)
        self.assertNotIn(secret_token.decode("utf-8"), content)

        data = json.loads(content)
        self.assertEqual(data["sha256"], hashlib.sha256(secret_token).hexdigest())
        self.assertEqual(data["email"], "y@example.com")
        self.assertIn("written_at", data)


class AgyLoginSafetyTest(unittest.TestCase):
    def tearDown(self):
        set_backend(None)

    def test_secret_safety_in_subprocess_argv_and_output(self):
        """Assert secrets NEVER appear in argv of subprocess calls and never in error text."""
        secret_bytes = b"SUPER_SECRET_TOKEN_DO_NOT_LEAK_12345"
        captured_calls = []

        def fake_run(args, **kwargs):
            captured_calls.append((list(args), kwargs))
            if "find-generic-password" in args and "-w" in args:
                return subprocess.CompletedProcess(args, 0, stdout=secret_bytes + b"\n", stderr=b"")
            if "-i" in args:
                return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
            if "dump-keychain" in args:
                return subprocess.CompletedProcess(args, 0, stdout="", stderr=b"")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr=b"")

        backend = SecurityKeychainBackend(security_bin="/fake/bin/security")

        with patch("subprocess.run", side_effect=fake_run):
            backend.write_slot(secret_bytes)
            for argv, kwargs in captured_calls:
                for arg in argv:
                    self.assertNotIn(secret_bytes.decode(), str(arg), f"Secret leaked into argv: {argv}")
                if "-i" in argv:
                    stdin_input = kwargs.get("input", b"")
                    self.assertIn(secret_bytes, stdin_input)

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

        backend = FakeKeychainBackend(slot=b"alice_secret", slot_mdat=50.0,
                                      saved={"alice@example.com": b"alice_secret",
                                             "bob@example.com": b"bob_secret"})
        set_backend(backend)

        s1 = _span("cli-1.log", 100.0, 110.0, auth_events=[(100.5, "alice@example.com", "keyring")])
        with patch("kanjo.antigravity_accounts.get_account_index",
                   return_value=FakeAccountIndex(spans=[s1], current="alice@example.com")), \
                patch("kanjo.agy_login.count_running_agy", return_value=0):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                ret = main(["agy-account", "list", "--json"])
            self.assertEqual(ret, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["status"], "ok")
            self.assertEqual(len(data["accounts"]), 2)
            self.assertEqual(data["running_agy"], 0)

            buf = io.StringIO()
            with patch("sys.stdout", buf):
                ret = main(["agy-account", "switch", "bob@example.com", "--json"])
            self.assertEqual(ret, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["account"], "bob@example.com")
            self.assertEqual(data["running_agy"], 0)
            self.assertEqual(backend.read_slot(), b"bob_secret")

    def test_parse_log_file_keyring_auth_ts(self):
        from kanjo.antigravity_accounts import parse_log_file
        with tempfile.TemporaryDirectory() as tmpdir:
            log1 = os.path.join(tmpdir, "cli-20261112_120000.log")
            with open(log1, "w") as f:
                f.write("I1112 12:00:01.123456 1 auth.go:100] keyringAuth: loaded token\n")
                f.write("I1112 12:00:02.654321 1 server_oauth.go:221] applyAuthResult: email=alice@example.com\n")
            span1 = parse_log_file(log1)
            self.assertIsNotNone(span1.auth_ts)
            self.assertEqual(span1.emails, {"alice@example.com"})
            self.assertEqual([(e[1], e[2]) for e in span1.auth_events], [("alice@example.com", "keyring")])

            log2 = os.path.join(tmpdir, "cli-20261112_130000.log")
            with open(log2, "w") as f:
                f.write("keyringAuth: loaded token\n")
                f.write("I1112 13:00:05.500000 1 server_oauth.go:221] applyAuthResult: email=bob@example.com\n")
            span2 = parse_log_file(log2)
            self.assertIsNotNone(span2.auth_ts)
            self.assertEqual(span2.emails, {"bob@example.com"})

            log3 = os.path.join(tmpdir, "cli-20261112_140000.log")
            with open(log3, "w") as f:
                f.write("I1112 14:00:05.500000 1 server_oauth.go:221] applyAuthResult: email=charlie@example.com\n")
            span3 = parse_log_file(log3)
            self.assertIsNone(span3.auth_ts)
            self.assertEqual(span3.emails, {"charlie@example.com"})
            # No keyring load -> the email is a login event, not keyring.
            self.assertEqual([(e[1], e[2]) for e in span3.auth_events], [("charlie@example.com", "login")])


if __name__ == "__main__":
    unittest.main()
