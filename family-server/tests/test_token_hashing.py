"""Unit tests for token generation and SHA-256 hashing."""

import hashlib
import os
import tempfile
import unittest

from family_server import db


class TestTokenHashing(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_tokens.db")
        db.init_db(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_hash_token_deterministic(self):
        token = "test-token-secret-123456"
        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.assertEqual(db.hash_token(token), expected)
        self.assertEqual(len(expected), 64)

    def test_add_member_stores_only_hash(self):
        with db.get_connection(self.db_path) as conn:
            token, member_id = db.add_member(conn, "SyntheticUser")
            self.assertTrue(len(token) >= 32)

            cur = conn.cursor()
            cur.execute("SELECT id, name, token_sha256 FROM members WHERE id = ?", (member_id,))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["name"], "SyntheticUser")

            # Check that raw token is NOT in the database
            self.assertNotEqual(row["token_sha256"], token)
            # Check that stored token is sha256 hex digest
            self.assertEqual(row["token_sha256"], db.hash_token(token))

    def test_get_member_by_token(self):
        with db.get_connection(self.db_path) as conn:
            token, member_id = db.add_member(conn, "UserLookup")
            found = db.get_member_by_token(conn, token)
            self.assertIsNotNone(found)
            self.assertEqual(found["id"], member_id)
            self.assertEqual(found["name"], "UserLookup")

            # Nonexistent token
            not_found = db.get_member_by_token(conn, "nonexistent-token")
            self.assertIsNone(not_found)


if __name__ == "__main__":
    unittest.main()
