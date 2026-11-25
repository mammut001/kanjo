"""Antigravity desktop app vs agy: source labels, app login record (rule 3),
and cache safety (docs/antigravity-app-accounts.md)."""

import json
import os
import shutil
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock

from kanjo import antigravity_accounts as aa
from kanjo import export
from kanjo.cache import SessionCache, _dump_session, _load_session
from kanjo.config import Config
from kanjo.ledger import Ledger
from kanjo.sources import antigravity
from kanjo.sources.base import AGENT_LABELS, Message, Session, session_label
from tests.support import ALICE, GITHUB, standard_fs, validate_contract
from tests.test_perf import NO_TOKEI, _pb_bytes, _pb_varint_field

T0 = 1794909600  # 2026-11-17T10:00:00Z
APP_ID = "aaaaaaaa-0000-4000-8000-000000000001"
CLI_ID = "bbbbbbbb-0000-4000-8000-000000000002"
SUB_ID = "cccccccc-0000-4000-8000-000000000003"


def _gen_record(ts, root=None, inp=100, out=50):
    usage = _pb_varint_field(2, inp) + _pb_varint_field(3, out)
    rec = (_pb_bytes(4, usage) + _pb_bytes(9, _pb_bytes(4, _pb_varint_field(1, ts)))
           + _pb_bytes(19, b"gemini-3-pro"))
    if root:
        rec += _pb_bytes(20, _pb_bytes(1, b"root_cascade_id") + _pb_bytes(2, root.encode()))
    return _pb_bytes(1, rec)


def write_db(directory, sid, stamps, root=None, workspace=GITHUB + "/FocusApp"):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, sid + ".db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE trajectory_metadata_blob (data BLOB)")
    conn.execute("CREATE TABLE steps (idx INTEGER, step_type INTEGER, metadata BLOB, step_payload BLOB)")
    conn.execute("CREATE TABLE gen_metadata (idx INTEGER, data BLOB)")
    ws = _pb_bytes(1, _pb_bytes(1, ("file://" + workspace).encode()))
    conn.execute("INSERT INTO trajectory_metadata_blob VALUES (?)", (ws,))
    for i, ts in enumerate(stamps):
        conn.execute("INSERT INTO gen_metadata VALUES (?, ?)", (i, _gen_record(ts, root)))
    conn.commit()
    conn.close()
    return path


class _CliIndex:
    """Stands in for the agy log index: rules a/b would always name this email."""

    spans = []

    def attribute(self, conversation_id, ts):
        return "cli@example.com"

    def get_current_account(self):
        return "cli@example.com"


class _Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-agy-app-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        os.makedirs(self.data)
        os.makedirs(self.cache_dir)
        self.storage = os.path.join(self.tmp, "app_storage.json")
        env = mock.patch.dict(os.environ, {
            "KANJO_DATA_DIR": self.data,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_ANTIGRAVITY_APP_STORAGE": self.storage,
            "KANJO_NO_NETWORK": "1",
        })
        env.start()
        self.addCleanup(env.stop)
        aa.reset_account_index()
        self.addCleanup(aa.reset_account_index)
        idx = mock.patch("kanjo.antigravity_accounts.get_account_index", return_value=_CliIndex())
        idx.start()
        self.addCleanup(idx.stop)
        self.app_dir = os.path.join(self.tmp, "gemini", "antigravity", "conversations")
        self.ide_dir = os.path.join(self.tmp, "gemini", "antigravity-ide", "conversations")
        self.cli_dir = os.path.join(self.tmp, "gemini", "antigravity-cli", "conversations")
        self.records = os.path.join(self.data, aa.APP_LOGINS_FILE)

    def set_login(self, email):
        with open(self.storage, "w", encoding="utf-8") as h:
            json.dump({"other": 1, aa.APP_LOGIN_KEY: email}, h)

    def write_records(self, rows):
        with open(self.records, "w", encoding="utf-8") as h:
            for ts, email in rows:
                h.write(json.dumps({"ts": ts, "email": email}) + "\n")

    def read_records(self):
        with open(self.records, encoding="utf-8") as h:
            return [json.loads(line) for line in h if line.strip()]


class SourceTest(_Env):
    def test_source_from_directory(self):
        self.assertEqual(antigravity.source_for_path(os.path.join(self.app_dir, "x.db")), "app")
        self.assertEqual(antigravity.source_for_path(os.path.join(self.ide_dir, "x.db")), "app")
        self.assertEqual(antigravity.source_for_path(os.path.join(self.cli_dir, "x.db")), "agy")
        self.assertEqual(antigravity.source_for_path("/u/.gemini/gemini-cli/conversations/x.db"), "agy")
        self.assertEqual(antigravity.source_for_path(r"C:\Users\a\.gemini\antigravity\conversations\x.db"), "app")
        # a test root without a conversations directory says nothing; sessions default to agy
        self.assertIsNone(antigravity.source_for_path("/tmp/fixtures/antigravity/x.db"))
        self.assertEqual(antigravity.session_source(Session(id="x", agent="antigravity", file="/f/x.db")), "agy")

    def test_labels(self):
        self.assertEqual(AGENT_LABELS["antigravity"], "Antigravity")
        self.assertEqual(session_label("antigravity", "app"), "Antigravity App")
        self.assertEqual(session_label("antigravity", "agy"), "agy")
        self.assertEqual(session_label("antigravity", None), "agy")
        self.assertEqual(session_label("claude", None), "Claude Code")

    def test_parse_sets_source_and_dump_roundtrip(self):
        app = antigravity.parse_file(write_db(self.app_dir, APP_ID, [T0]))
        cli = antigravity.parse_file(write_db(self.cli_dir, CLI_ID, [T0]))
        self.assertEqual((app.source, cli.source), ("app", "agy"))
        self.assertEqual(_load_session(_dump_session(app)).source, "app")
        # other agents dump exactly as before (no source key)
        self.assertNotIn("source", _dump_session(Session(id="c", agent="claude", file="/c")))

    def test_export_labels_and_subagent_follows_parent(self):
        write_db(self.app_dir, APP_ID, [T0])
        write_db(self.cli_dir, CLI_ID, [T0 + 60])
        # the sub-agent's database sits in the CLI directory, its parent is an app conversation
        write_db(self.cli_dir, SUB_ID, [T0 + 30], root=APP_ID)
        fs = standard_fs()
        self.addCleanup(fs.cleanup)
        dirs = {"antigravity": [self.app_dir, self.cli_dir]}
        result = export.scan(dirs, ledger=Ledger(self.data))
        by_id = {s.id: s for s in result.sessions}
        self.assertEqual(by_id[SUB_ID].subagent_of, APP_ID)
        self.assertEqual(by_id[SUB_ID].source, "app")
        self.assertEqual(by_id[CLI_ID].source, "agy")
        # the ledger stores the followed source
        entry = Ledger(self.data).entries["antigravity\0%s\0%s" % (SUB_ID, APP_ID)]
        self.assertEqual(entry["session"]["source"], "app")

        doc = export.build_export(scan_result=result, fs_root=fs.root, home=ALICE, tokei_dir=NO_TOKEI)
        validate_contract(self, doc)
        details = {d["id"]: d for p in doc["projects"] for d in p["sessions_detail"]}
        self.assertEqual(details[APP_ID]["label"], "Antigravity App")
        self.assertEqual(details[CLI_ID]["label"], "agy")
        self.assertEqual(details[APP_ID]["agent"], "antigravity")
        self.assertEqual(details[APP_ID]["subagents"], 1)
        for p in doc["projects"]:
            for a in p["by_agent"]:
                if a["agent"] == "antigravity":
                    self.assertEqual(a["label"], "Antigravity")

    def test_ledger_keeps_source_after_database_is_deleted(self):
        app_db = write_db(self.app_dir, APP_ID, [T0])
        dirs = {"antigravity": [self.app_dir, self.cli_dir]}
        export.scan(dirs, ledger=Ledger(self.data))
        os.unlink(app_db)
        result = export.scan(dirs, ledger=Ledger(self.data))
        orphan = [s for s in result.sessions if s.id == APP_ID]
        self.assertEqual(len(orphan), 1)
        self.assertEqual(orphan[0].source, "app")

    def test_ledger_rows_without_source(self):
        # a row written before sources existed: its recorded path still decides,
        # and a path that says nothing means agy
        old_app = Session(id="old-app", agent="antigravity", file=os.path.join(self.app_dir, "old-app.db"))
        old_other = Session(id="old-x", agent="antigravity", file="/gone/old-x.db")
        for s in (old_app, old_other):
            s.messages = [Message(ts=T0, model="gemini-3-pro", input=1, output=1, account="cli@example.com")]
            d = _dump_session(s)
            self.assertNotIn("source", d)
            loaded = _load_session(d)
            aa.apply_accounts(loaded, keep_known=True)
            s.source, s.messages = loaded.source, loaded.messages
        self.assertEqual(old_app.source, "app")
        self.assertEqual(old_other.source, "agy")
        # an app message never keeps an account guessed from the CLI logs
        self.assertIsNone(old_app.messages[0].account)
        self.assertEqual(old_other.messages[0].account, "cli@example.com")


class AccountRulesTest(_Env):
    def test_rules_a_b_only_for_agy(self):
        self.write_records([(T0 - 600, "app@example.com"), (T0 + 600, "app@example.com")])
        app = antigravity.parse_file(write_db(self.app_dir, APP_ID, [T0, T0 + 10 * 86400]))
        cli = antigravity.parse_file(write_db(self.cli_dir, CLI_ID, [T0]))
        self.assertEqual([m.account for m in app.messages], ["app@example.com", None])
        self.assertEqual([m.account for m in cli.messages], ["cli@example.com"])
        self.assertEqual(aa.attribute_message(APP_ID, T0, "app"), "app@example.com")
        self.assertEqual(aa.attribute_message(APP_ID, T0, "agy"), "cli@example.com")

    def test_app_without_records_is_unknown(self):
        app = antigravity.parse_file(write_db(self.app_dir, APP_ID, [T0]))
        self.assertEqual([m.account for m in app.messages], [None])

    def test_attribution_cases(self):
        recs = [(1000.0, "a@x.com"), (5000.0, "a@x.com"), (9000.0, "b@x.com")]
        cases = [
            (500.0, None),          # before the first record
            (1000.0, "a@x.com"),    # exactly on a record
            (3000.0, "a@x.com"),    # same email before and after
            (7000.0, None),         # switched between the two records
            (9000.0, "b@x.com"),
            (9000.0 + 7200, "b@x.com"),   # within two hours after the last record
            (9000.0 + 7201, None),        # later than that
        ]
        for ts, want in cases:
            with self.subTest(ts=ts):
                self.assertEqual(aa.attribute_app(ts, recs), want)
        self.assertIsNone(aa.attribute_app(3000.0, []))

    def test_attribution_reads_record_file(self):
        self.assertIsNone(aa.attribute_app(T0))
        self.write_records([(T0 - 10, "A@Example.com"), (T0 + 10, "a@example.com"), ("bad", "x@y.com")])
        with open(self.records, "a", encoding="utf-8") as h:
            h.write("not json\n{\"ts\": 1}\n")
        self.assertEqual(aa.app_login_records(), [(T0 - 10.0, "a@example.com"), (T0 + 10.0, "a@example.com")])
        self.assertEqual(aa.attribute_app(T0), "a@example.com")


class LoginRecordTest(_Env):
    def test_append_dedupe_and_hourly(self):
        self.set_login("  Alice@Example.COM ")
        self.assertTrue(aa.record_app_login(now=T0))
        self.assertFalse(aa.record_app_login(now=T0 + 600))         # same email, < 1 h
        self.assertFalse(aa.record_app_login(now=T0 + 3599))
        self.assertTrue(aa.record_app_login(now=T0 + 3600))          # an hour has passed
        self.set_login("bob@example.com")
        self.assertTrue(aa.record_app_login(now=T0 + 3700))          # account changed
        self.set_login("alice@example.com")
        self.assertTrue(aa.record_app_login(now=T0 + 3701))
        self.assertEqual(self.read_records(), [
            {"ts": T0, "email": "alice@example.com"},
            {"ts": T0 + 3600, "email": "alice@example.com"},
            {"ts": T0 + 3700, "email": "bob@example.com"},
            {"ts": T0 + 3701, "email": "alice@example.com"},
        ])
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(self.records).st_mode), 0o600)

    def test_existing_file_is_tightened_to_0600(self):
        if os.name != "posix":
            self.skipTest("POSIX permissions")
        self.write_records([(T0, "bob@example.com")])
        os.chmod(self.records, 0o644)
        self.set_login("alice@example.com")
        self.assertTrue(aa.record_app_login(now=T0 + 1))
        self.assertEqual(stat.S_IMODE(os.stat(self.records).st_mode), 0o600)

    def test_bad_app_storage_writes_nothing(self):
        bad = [
            None,                                   # missing file
            b"{not json",
            b"[1, 2]",
            json.dumps({"other": "a@b.com"}).encode(),
            json.dumps({aa.APP_LOGIN_KEY: "not an email"}).encode(),
            json.dumps({aa.APP_LOGIN_KEY: 42}).encode(),
            json.dumps({aa.APP_LOGIN_KEY: ""}).encode(),
            b"\xff\xfe",
        ]
        for content in bad:
            with self.subTest(content=content):
                if os.path.exists(self.storage):
                    os.unlink(self.storage)
                if content is not None:
                    with open(self.storage, "wb") as h:
                        h.write(content)
                self.assertFalse(aa.record_app_login(now=T0))
                self.assertFalse(os.path.exists(self.records))

    def test_storage_is_a_directory(self):
        os.makedirs(self.storage)
        self.assertIsNone(aa.read_app_login())
        self.assertFalse(aa.record_app_login(now=T0))

    def test_nested_key_and_quoted_value(self):
        with open(self.storage, "w", encoding="utf-8") as h:
            json.dump({"agy": {"onboarding": {"lastLoginUsername": '"Nested@Example.com"'}}}, h)
        self.assertEqual(aa.read_app_login(), "nested@example.com")

    def test_real_file_never_read_under_test_data_dir(self):
        with mock.patch.dict(os.environ, {"KANJO_DATA_DIR": self.data}):
            os.environ.pop("KANJO_ANTIGRAVITY_APP_STORAGE", None)
            self.assertIsNone(aa.app_storage_path())
            with mock.patch("builtins.open", side_effect=AssertionError("opened")):
                self.assertIsNone(aa.read_app_login())

    def test_default_paths(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("KANJO_DATA_DIR", "KANJO_ANTIGRAVITY_APP_STORAGE")}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("sys.platform", "darwin"), mock.patch("kanjo.winsupport.is_windows", return_value=False):
                self.assertTrue(aa.app_storage_path().endswith(
                    os.path.join("Library", "Application Support", "Antigravity", "app_storage.json")))
            with mock.patch("sys.platform", "linux"), mock.patch("kanjo.winsupport.is_windows", return_value=False):
                self.assertTrue(aa.app_storage_path().endswith(
                    os.path.join(".config", "Antigravity", "app_storage.json")))

    def test_scan_records_the_login(self):
        self.set_login("alice@example.com")
        export.scan({"antigravity": [self.app_dir]}, ledger=Ledger(self.data))
        self.assertEqual([r["email"] for r in self.read_records()], ["alice@example.com"])
        # a scan of other agents only does not touch the record
        os.unlink(self.records)
        export.scan({"claude": []}, ledger=Ledger(self.data))
        self.assertFalse(os.path.exists(self.records))


class CacheAndPrivacyTest(_Env):
    def test_cached_sessions_follow_record_changes(self):
        db = write_db(self.app_dir, APP_ID, [T0])
        cache = SessionCache(self.cache_dir)
        s = cache.get("antigravity", db, None, antigravity.parse_file)
        self.assertEqual([m.account for m in s.messages], [None])
        cache.save()
        self.write_records([(T0 - 60, "a@example.com"), (T0 + 60, "a@example.com")])
        cache2 = SessionCache(self.cache_dir)
        s2 = cache2.get("antigravity", db, None, antigravity.parse_file)
        self.assertEqual([m.account for m in s2.messages], ["a@example.com"])
        # same process, same cache object: a changed record file is re-read
        with open(self.records, "a", encoding="utf-8") as h:
            h.write(json.dumps({"ts": T0 + 30, "email": "b@example.com"}) + "\n")
        s3 = cache2.get("antigravity", db, None, antigravity.parse_file)
        self.assertEqual([m.account for m in s3.messages], [None])

    def test_fingerprint_changes_with_record_file(self):
        dirs = {"antigravity": [self.app_dir]}
        cfg = Config()
        fp1 = export.source_fingerprint(dirs, cfg)
        self.assertEqual(export.source_fingerprint(dirs, cfg), fp1)
        self.set_login("alice@example.com")
        fp2 = export.source_fingerprint(dirs, cfg)   # records the login, then fingerprints it
        self.assertNotEqual(fp2, fp1)
        self.assertEqual(len(self.read_records()), 1)
        self.assertEqual(export.source_fingerprint(dirs, cfg), fp2)

    def test_slim_exports_stay_email_free(self):
        write_db(self.app_dir, APP_ID, [T0])
        self.write_records([(T0 - 60, "app@example.com"), (T0 + 60, "app@example.com")])
        fs = standard_fs()
        self.addCleanup(fs.cleanup)
        result = export.scan({"antigravity": [self.app_dir]}, ledger=Ledger(self.data))
        self.assertEqual([m.account for s in result.sessions for m in s.messages], ["app@example.com"])
        doc = export.build_export(scan_result=result, fs_root=fs.root, home=ALICE, tokei_dir=NO_TOKEI)
        self.assertIn("app@example.com", json.dumps(doc.get("antigravity_accounts")))
        self.assertNotIn("@", json.dumps(export.mobile_document(doc)))
        pub = export.build_public_summary(scan_result=result, fs_root=fs.root, home=ALICE)
        self.assertNotIn("@", json.dumps(pub))
        fam = export.build_family_report(scan_result=result, fs_root=fs.root, home=ALICE)
        self.assertNotIn("@", json.dumps(fam, ensure_ascii=False))
        # the account filter applies to app messages too
        filt = export.build_family_report(config=Config(family_accounts=["other@example.com"]),
                                          scan_result=result, fs_root=fs.root, home=ALICE)
        self.assertEqual(filt["summary"]["all_time"]["tokens"]["total"], 0)
        keep = export.build_family_report(config=Config(family_accounts=["app@example.com"]),
                                          scan_result=result, fs_root=fs.root, home=ALICE)
        self.assertEqual(keep["summary"]["all_time"]["tokens"]["total"], 150)


if __name__ == "__main__":
    unittest.main()
