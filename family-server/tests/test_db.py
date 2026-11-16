"""Unit tests for SQLite database operations and retention pruning."""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest

from family_server import db


class TestDatabaseAndPrune(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_family.db")
        db.init_db(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_member_uniqueness_and_revocation(self):
        with db.get_connection(self.db_path) as conn:
            token, m_id = db.add_member(conn, "Member1")
            self.assertEqual(m_id, 1)

            # Duplicate name
            with self.assertRaises(ValueError):
                db.add_member(conn, "Member1")

            # Empty name
            with self.assertRaises(ValueError):
                db.add_member(conn, "   ")

            # Revoke member
            self.assertTrue(db.revoke_member(conn, "Member1"))
            # Revoke again returns False (already revoked)
            self.assertFalse(db.revoke_member(conn, "Member1"))

            # Revoke nonexistent member
            with self.assertRaises(ValueError):
                db.revoke_member(conn, "Ghost")

            # Member lookup reflects revocation
            m = db.get_member_by_token(conn, token)
            self.assertIsNotNone(m)
            self.assertIsNotNone(m["revoked_at"])

    def test_prune_retention_policy(self):
        """Retention policy:
        - Latest report per member is kept.
        - Last report per member per day is kept within 90 days.
        - Intermediate reports on the same day are deleted.
        - Reports older than 90 days are deleted unless they are the latest report.
        """
        now = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)

        with db.get_connection(self.db_path) as conn:
            _, m1 = db.add_member(conn, "MemberOne")
            _, m2 = db.add_member(conn, "MemberTwo")

            # Member 1 reports:
            # 95 days ago: 2 reports (older than 90 days, should both be deleted since Member 1 has newer reports)
            d95 = now - timedelta(days=95)
            db.insert_report(conn, m1, d95.isoformat(), '{"day": "d95_1"}', received_at=(d95 + timedelta(hours=1)).isoformat())
            db.insert_report(conn, m1, d95.isoformat(), '{"day": "d95_2"}', received_at=(d95 + timedelta(hours=5)).isoformat())

            # 30 days ago: 3 reports on the same day (first 2 intermediate deleted, last 1 kept)
            d30 = now - timedelta(days=30)
            id_d30_1 = db.insert_report(conn, m1, d30.isoformat(), '{"day": "d30_1"}', received_at=(d30 + timedelta(hours=1)).isoformat())
            id_d30_2 = db.insert_report(conn, m1, d30.isoformat(), '{"day": "d30_2"}', received_at=(d30 + timedelta(hours=4)).isoformat())
            id_d30_3 = db.insert_report(conn, m1, d30.isoformat(), '{"day": "d30_3"}', received_at=(d30 + timedelta(hours=8)).isoformat())

            # Today: 2 reports (first intermediate deleted, second is latest and kept)
            id_today_1 = db.insert_report(conn, m1, now.isoformat(), '{"day": "today_1"}', received_at=(now - timedelta(hours=3)).isoformat())
            id_today_2 = db.insert_report(conn, m1, now.isoformat(), '{"day": "today_2"}', received_at=now.isoformat())

            # Member 2 reports:
            # Only 1 report, 120 days ago (older than 90 days, but is Member 2's latest report -> must be KEPT!)
            d120 = now - timedelta(days=120)
            id_m2_only = db.insert_report(conn, m2, d120.isoformat(), '{"m2": "oldest"}', received_at=d120.isoformat())

            # Total reports before prune: 2 (d95) + 3 (d30) + 2 (today) + 1 (m2) = 8
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM reports")
            self.assertEqual(cur.fetchone()[0], 8)

            # Execute prune
            deleted = db.prune_reports(conn, now=now)

            # Deleted:
            # Member 1: 2 from d95, id_d30_1, id_d30_2, id_today_1 = 5 reports deleted
            # Member 2: 0 deleted
            self.assertEqual(deleted, 5)

            # Verify kept reports
            cur.execute("SELECT id FROM reports ORDER BY id ASC")
            remaining_ids = {row[0] for row in cur.fetchall()}
            expected_ids = {id_d30_3, id_today_2, id_m2_only}
            self.assertEqual(remaining_ids, expected_ids)

    def test_maybe_prune_hourly_throttle(self):
        now = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
        with db.get_connection(self.db_path) as conn:
            _, m1 = db.add_member(conn, "UserThrottle")
            db.insert_report(conn, m1, now.isoformat(), '{"v": 1}', received_at=now.isoformat())

            # First prune runs
            res1 = db.maybe_prune_hourly(conn, now=now)
            self.assertIsNotNone(res1)

            # 10 minutes later: should throttle (returns None)
            res2 = db.maybe_prune_hourly(conn, now=now + timedelta(minutes=10))
            self.assertIsNone(res2)

            # 61 minutes later: should run
            res3 = db.maybe_prune_hourly(conn, now=now + timedelta(minutes=61))
            self.assertIsNotNone(res3)

    def test_settings_crud(self):
        with db.get_connection(self.db_path) as conn:
            self.assertIsNone(db.get_setting(conn, "cycle_anchor_day"))
            self.assertEqual(db.get_setting(conn, "cycle_anchor_day", "default_val"), "default_val")

            # Set setting
            db.set_setting(conn, "cycle_anchor_day", "9")
            db.set_setting(conn, "timezone", "America/Toronto")
            db.set_setting(conn, "tracking_start", "2026-11-09")

            self.assertEqual(db.get_setting(conn, "cycle_anchor_day"), "9")
            self.assertEqual(db.get_setting(conn, "timezone"), "America/Toronto")
            self.assertEqual(db.get_setting(conn, "tracking_start"), "2026-11-09")

            all_s = db.get_all_settings(conn)
            self.assertEqual(all_s["cycle_anchor_day"], "9")
            self.assertEqual(all_s["timezone"], "America/Toronto")
            self.assertEqual(all_s["tracking_start"], "2026-11-09")

            # Update setting
            db.set_setting(conn, "cycle_anchor_day", "15")
            self.assertEqual(db.get_setting(conn, "cycle_anchor_day"), "15")

            # Delete setting with None
            db.set_setting(conn, "tracking_start", None)
            self.assertIsNone(db.get_setting(conn, "tracking_start"))
            self.assertNotIn("tracking_start", db.get_all_settings(conn))

    def test_migration_on_old_schema_db(self):
        import sqlite3

        old_db = os.path.join(self.tmp_dir.name, "old_schema.db")
        with sqlite3.connect(old_db) as conn:
            conn.executescript(
                """
                CREATE TABLE members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    token_sha256 TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    member_id INTEGER NOT NULL REFERENCES members(id),
                    received_at TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                INSERT INTO members (name, token_sha256, created_at) VALUES ('OldUser', 'hash123', '2026-10-01T00:00:00Z');
                INSERT INTO reports (member_id, received_at, generated_at, payload_json)
                    VALUES (1, '2026-10-02T00:00:00Z', '2026-10-02T00:00:00Z', '{"summary":{}}');
                """
            )

        # Idempotent migration on startup
        db.init_db(old_db)
        db.init_db(old_db)

        with db.get_connection(old_db) as conn:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(reports)").fetchall()}
            self.assertIn("device_id", cols)
            self.assertIn("device_name", cols)
            idxs = {row["name"] for row in conn.execute("PRAGMA index_list(reports)").fetchall()}
            self.assertIn("idx_reports_member_device_received", idxs)
            row = conn.execute("SELECT device_id, device_name FROM reports WHERE id = 1").fetchone()
            self.assertEqual(row["device_id"], "")
            self.assertIsNone(row["device_name"])

    def test_prune_retention_per_device(self):
        now = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
        dev_a = "aaaa1111bbbb2222"
        dev_b = "cccc3333dddd4444"

        with db.get_connection(self.db_path) as conn:
            _, m1 = db.add_member(conn, "MultiDeviceUser")

            # Device A: 120 days old (latest for dev_a -> MUST be kept!)
            d120 = now - timedelta(days=120)
            id_a_old = db.insert_report(
                conn, m1, d120.isoformat(), '{"dev":"a"}',
                received_at=d120.isoformat(), device_id=dev_a, device_name="OldMac",
            )

            # Device B: 2 reports today -> first deleted, second kept
            id_b_t1 = db.insert_report(
                conn, m1, now.isoformat(), '{"dev":"b1"}',
                received_at=(now - timedelta(hours=2)).isoformat(), device_id=dev_b, device_name="LinuxBox",
            )
            id_b_t2 = db.insert_report(
                conn, m1, now.isoformat(), '{"dev":"b2"}',
                received_at=now.isoformat(), device_id=dev_b, device_name="LinuxBox",
            )

            deleted = db.prune_reports(conn, now=now)
            self.assertEqual(deleted, 1)

            rows = conn.execute("SELECT id FROM reports ORDER BY id ASC").fetchall()
            self.assertEqual({r["id"] for r in rows}, {id_a_old, id_b_t2})
            self.assertNotIn(id_b_t1, {r["id"] for r in rows})

    def test_get_member_latest_reports_by_device_and_remove(self):
        with db.get_connection(self.db_path) as conn:
            _, m1 = db.add_member(conn, "Alice")
            db.insert_report(
                conn, m1, "2026-11-01T10:00:00Z", '{"v":1}',
                received_at="2026-11-01T10:00:00Z", device_id="1111222233334444", device_name="Mac",
            )
            db.insert_report(
                conn, m1, "2026-11-02T10:00:00Z", '{"v":2}',
                received_at="2026-11-02T10:00:00Z", device_id="1111222233334444", device_name="Mac",
            )
            db.insert_report(
                conn, m1, "2026-11-03T10:00:00Z", '{"v":3}',
                received_at="2026-11-03T10:00:00Z", device_id="aaaa5555bbbb6666", device_name="Linux",
            )

            latest = db.get_member_latest_reports_by_device(conn, m1)
            self.assertEqual(len(latest), 2)
            self.assertEqual(latest[0]["device_id"], "aaaa5555bbbb6666")
            self.assertEqual(latest[1]["device_id"], "1111222233334444")
            self.assertIn('"v":2', latest[1]["payload_json"])

            devices = db.list_member_devices(conn, "Alice")
            self.assertEqual(len(devices), 2)
            counts = {d["device_id"]: d["report_count"] for d in devices}
            self.assertEqual(counts["1111222233334444"], 2)
            self.assertEqual(counts["aaaa5555bbbb6666"], 1)

            removed = db.remove_member_device(conn, "Alice", "1111222233334444")
            self.assertEqual(removed, 2)
            self.assertEqual(len(db.get_member_latest_reports_by_device(conn, m1)), 1)


if __name__ == "__main__":
    unittest.main()
