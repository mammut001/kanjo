"""`kanjo export --mobile`: the trimmed phone snapshot (CONTRACT.md section 11)."""

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from kanjo.export import build_export, mobile_document

from tests.support import ALICE, FIXTURE_DIRS, FIXTURES, standard_fs, validate_contract

NO_TOKEI = os.path.join(FIXTURES, "no-tokei")
CLI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MOBILE_TOP_LEVEL = {"schema_version", "generated_at", "generated_by", "timezone", "currency",
                    "cost_note", "quota_windows", "subscriptions", "totals", "projects", "buckets",
                    "mobile"}
MOBILE_PROJECT_KEYS = {"id", "name", "cost", "tokens", "sessions", "first_active", "last_active",
                       "by_agent", "by_model", "by_day"}
MOBILE_BUCKET_KEYS = {"cost", "tokens", "sessions", "first_active", "last_active"}
DROP_PROJECT_KEYS = {"config", "paths", "remote", "path_missing", "by_branch", "sessions_detail"}


class MobileDocumentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fs = standard_fs()
        cls.full = build_export(dirs=FIXTURE_DIRS, fs_root=cls.fs.root, home=ALICE, tokei_dir=NO_TOKEI)
        cls.mobile = mobile_document(cls.full)

    @classmethod
    def tearDownClass(cls):
        cls.fs.cleanup()

    def test_top_level_keys_are_trimmed(self):
        self.assertEqual(set(self.mobile), MOBILE_TOP_LEVEL)
        self.assertEqual(self.mobile["mobile"], {"trimmed": True, "hidden_project_names": False})
        for key in ("config", "ledger"):
            self.assertNotIn(key, self.mobile)

    def test_projects_keep_only_phone_fields(self):
        self.assertEqual(len(self.mobile["projects"]), len(self.full["projects"]))
        for mobile_project, full_project in zip(self.mobile["projects"], self.full["projects"]):
            self.assertEqual(set(mobile_project), MOBILE_PROJECT_KEYS)
            self.assertFalse(DROP_PROJECT_KEYS & set(mobile_project))
            self.assertEqual(mobile_project["id"], full_project["id"])
            self.assertEqual(mobile_project["name"], full_project["name"])
            self.assertEqual(mobile_project["cost"], full_project["cost"])
            self.assertEqual(mobile_project["tokens"], full_project["tokens"])
            self.assertEqual(mobile_project["sessions"], full_project["sessions"])
            self.assertEqual(mobile_project["first_active"], full_project["first_active"])
            self.assertEqual(mobile_project["last_active"], full_project["last_active"])
            self.assertEqual(mobile_project["by_agent"], full_project["by_agent"])
            self.assertEqual(mobile_project["by_model"], full_project["by_model"])
            self.assertEqual(mobile_project["by_day"], full_project["by_day"])

    def test_buckets_are_summaries_only(self):
        buckets = self.mobile["buckets"]
        for name in ("unattributed", "excluded"):
            self.assertEqual(set(buckets[name]), MOBILE_BUCKET_KEYS)
            for key in MOBILE_BUCKET_KEYS:
                self.assertEqual(buckets[name][key], self.full["buckets"][name][key])
        self.assertEqual(set(buckets["parse_failed"]), {"sessions"})
        self.assertEqual(buckets["parse_failed"]["sessions"], self.full["buckets"]["parse_failed"]["sessions"])

    def test_numbers_and_shared_sections_match_full_export(self):
        self.assertEqual(self.mobile["totals"], self.full["totals"])
        for key in ("schema_version", "generated_at", "generated_by", "timezone", "currency",
                    "cost_note", "quota_windows", "subscriptions"):
            self.assertEqual(self.mobile[key], self.full[key])
        text = json.dumps(self.mobile)
        for needle in ('"sessions_detail"', '"paths"', '"remote"', '"path_missing"', '"by_branch"'):
            self.assertNotIn(needle, text)

    def test_hide_project_names_keeps_order_and_is_stable(self):
        hidden = mobile_document(self.full, hide_project_names=True)
        self.assertEqual(hidden["mobile"], {"trimmed": True, "hidden_project_names": True})
        self.assertEqual([p["name"] for p in hidden["projects"]],
                         ["Project %d" % i for i in range(1, len(self.full["projects"]) + 1)])
        self.assertEqual([p["id"] for p in hidden["projects"]],
                         [hashlib.sha256(p["id"].encode("utf-8")).hexdigest()[:12]
                          for p in self.full["projects"]])
        self.assertEqual([p["cost"] for p in hidden["projects"]],
                         [p["cost"] for p in self.full["projects"]])
        self.assertEqual(len({p["id"] for p in hidden["projects"]}), len(hidden["projects"]))
        self.assertEqual(hidden, mobile_document(self.full, hide_project_names=True))

    def test_full_export_is_not_mutated(self):
        before = json.dumps(self.full, sort_keys=True)
        mobile_document(self.full, hide_project_names=True)
        self.assertEqual(json.dumps(self.full, sort_keys=True), before)
        self.assertIn("sessions_detail", self.full["projects"][0])
        self.assertIn("config", self.full)


class MobileCliTest(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix="kanjo-test-data-")
        self.cache_dir = tempfile.mkdtemp(prefix="kanjo-test-cache-")
        self.env = dict(
            os.environ,
            KANJO_DATA_DIR=self.data_dir,
            KANJO_CACHE_DIR=self.cache_dir,
            KANJO_CLAUDE_DIR=FIXTURE_DIRS["claude"][0],
            KANJO_ANTIGRAVITY_DIR=FIXTURE_DIRS["antigravity"][0],
            KANJO_CODEX_DIR=FIXTURE_DIRS["codex"][0],
            KANJO_TOKEI_DIR=NO_TOKEI,
            KANJO_NO_NETWORK="1",
        )

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)
        shutil.rmtree(self.cache_dir, ignore_errors=True)

    def run_export(self, *argv):
        proc = subprocess.run([sys.executable, "-m", "kanjo", "export"] + list(argv),
                              cwd=CLI_DIR, capture_output=True, env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return proc.stdout

    def test_gzip_decompresses_to_the_mobile_json(self):
        compressed = self.run_export("--mobile", "--gzip")
        self.assertTrue(compressed.startswith(b"\x1f\x8b"))
        plain = self.run_export("--mobile", "--compact")
        from_gzip = json.loads(gzip.decompress(compressed))
        from_plain = json.loads(plain)
        from_gzip.pop("generated_at")
        from_plain.pop("generated_at")
        self.assertEqual(from_gzip, from_plain)

    def test_full_export_still_has_every_section(self):
        full = json.loads(self.run_export())
        validate_contract(self, full)
        self.assertIn("config", full)
        self.assertIn("ledger", full)
        self.assertIn("sessions_detail", full["buckets"]["unattributed"])
        self.assertIn("files", full["buckets"]["parse_failed"])

    def test_hide_project_names_requires_mobile(self):
        proc = subprocess.run([sys.executable, "-m", "kanjo", "export", "--hide-project-names"],
                              cwd=CLI_DIR, capture_output=True, env=self.env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"--hide-project-names requires --mobile", proc.stderr)


if __name__ == "__main__":
    unittest.main()
