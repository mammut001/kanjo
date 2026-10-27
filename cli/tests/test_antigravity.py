import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from kanjo import disk
from kanjo.sources import antigravity


class AntigravitySourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-test-agy-")
        self.dir_cli = os.path.join(self.tmp, "antigravity-cli", "conversations")
        self.dir_app = os.path.join(self.tmp, "antigravity", "conversations")
        os.makedirs(self.dir_cli, exist_ok=True)
        os.makedirs(self.dir_app, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_roots_default_includes_both_directories(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            r = antigravity.roots()
            expected = [
                os.path.expanduser("~/.gemini/antigravity-cli/conversations"),
                os.path.expanduser("~/.gemini/antigravity/conversations"),
            ]
            self.assertEqual(r, expected)

    def test_roots_env_override(self):
        custom = os.path.join(self.tmp, "custom")
        with mock.patch.dict(os.environ, {"KANJO_ANTIGRAVITY_DIR": custom}):
            self.assertEqual(antigravity.roots(), [custom])

        custom_multi = custom + os.pathsep + os.path.join(self.tmp, "custom2")
        with mock.patch.dict(os.environ, {"KANJO_ANTIGRAVITY_DIR": custom_multi}):
            self.assertEqual(antigravity.roots(), [custom, os.path.join(self.tmp, "custom2")])

    def test_discover_missing_dir_yields_empty(self):
        self.assertEqual(antigravity.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_both_dirs(self):
        db1 = os.path.join(self.dir_cli, "session-1.db")
        db2 = os.path.join(self.dir_app, "session-2.db")
        with open(db1, "w") as f:
            f.write("dummy1")
        with open(db2, "w") as f:
            f.write("dummy2")

        discovered = antigravity.discover([self.dir_cli, self.dir_app])
        self.assertEqual(len(discovered), 2)
        paths = [p for p, parent in discovered]
        self.assertEqual(paths, [db1, db2])
        for _, parent in discovered:
            self.assertIsNone(parent)

    def test_discover_deduplication_prefers_newer_app(self):
        # session-dup.db in both; app version is newer
        cli_db = os.path.join(self.dir_cli, "session-dup.db")
        app_db = os.path.join(self.dir_app, "session-dup.db")
        with open(cli_db, "w") as f:
            f.write("cli")
        with open(app_db, "w") as f:
            f.write("app")

        now = time.time()
        os.utime(cli_db, (now - 100, now - 100))
        os.utime(app_db, (now, now))

        discovered = antigravity.discover([self.dir_cli, self.dir_app])
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0][0], app_db)

    def test_discover_deduplication_prefers_newer_cli(self):
        # session-dup.db in both; cli version is newer
        cli_db = os.path.join(self.dir_cli, "session-dup.db")
        app_db = os.path.join(self.dir_app, "session-dup.db")
        with open(cli_db, "w") as f:
            f.write("cli")
        with open(app_db, "w") as f:
            f.write("app")

        now = time.time()
        os.utime(cli_db, (now, now))
        os.utime(app_db, (now - 100, now - 100))

        discovered = antigravity.discover([self.dir_cli, self.dir_app])
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0][0], cli_db)

    def test_discover_with_env_override(self):
        custom = os.path.join(self.tmp, "env_custom")
        os.makedirs(custom, exist_ok=True)
        db = os.path.join(custom, "env-session.db")
        with open(db, "w") as f:
            f.write("env")

        with mock.patch.dict(os.environ, {"KANJO_ANTIGRAVITY_DIR": custom}):
            discovered = antigravity.discover()
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0][0], db)

    def test_disk_default_roots_has_both_directories(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            agy_dirs = disk.default_roots()["antigravity_dirs"]
            expected = [
                os.path.expanduser("~/.gemini/antigravity-cli/conversations"),
                os.path.expanduser("~/.gemini/antigravity/conversations"),
            ]
            self.assertEqual(agy_dirs, expected)


if __name__ == "__main__":
    unittest.main()
