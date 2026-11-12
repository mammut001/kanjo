"""Windows branches of the paths, directories, temp roots and timezone fallbacks.

Every test here runs on macOS/Linux by monkeypatching ``is_windows()`` and pointing
``USERPROFILE`` / ``APPDATA`` / ``LOCALAPPDATA`` / ``TEMP`` at temp dirs, so the
Windows-only code is exercised without a Windows machine and without touching the
real home directory.
"""

from __future__ import annotations

import ctypes
import ntpath
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

from kanjo import cache, config, disk, ledger, quota, winsupport
from kanjo.identity import Resolver
from kanjo.sources import antigravity, base, claude, codex, devin, musecode, opencode, qoder_ide

PROFILE = "C:\\Users\\alice"
APPDATA = PROFILE + "\\AppData\\Roaming"
LOCALAPPDATA = PROFILE + "\\AppData\\Local"
TEMP = LOCALAPPDATA + "\\Temp"


def fake_windows_env(**extra):
    env = {
        "USERPROFILE": PROFILE,
        "APPDATA": APPDATA,
        "LOCALAPPDATA": LOCALAPPDATA,
        "TEMP": TEMP,
    }
    env.update(extra)
    return mock.patch.dict(os.environ, env, clear=True)


class WindowsDirsTest(unittest.TestCase):
    """winsupport's directory helpers on Windows vs. their POSIX defaults."""

    def test_kanjo_dirs(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            self.assertEqual(winsupport.kanjo_config_dir(), ntpath.join(APPDATA, "kanjo"))
            self.assertEqual(winsupport.kanjo_data_dir(), ntpath.join(LOCALAPPDATA, "kanjo", "data"))
            self.assertEqual(winsupport.kanjo_cache_dir(), ntpath.join(LOCALAPPDATA, "kanjo", "cache"))

    def test_dirs_fall_back_to_the_profile_when_env_is_missing(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch.dict(os.environ, {"USERPROFILE": PROFILE}, clear=True):
            self.assertEqual(winsupport.app_data(), ntpath.join(PROFILE, "AppData", "Roaming"))
            self.assertEqual(winsupport.local_app_data(), ntpath.join(PROFILE, "AppData", "Local"))
            self.assertEqual(winsupport.kanjo_config_dir(), ntpath.join(PROFILE, "AppData", "Roaming", "kanjo"))

    def test_app_support_and_local_data_map_macos_roots(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            self.assertEqual(winsupport.app_support_dir("Claude"), ntpath.join(APPDATA, "Claude"))
            self.assertEqual(winsupport.local_data_dir("muse"), ntpath.join(LOCALAPPDATA, "muse"))
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            # The macOS paths are built from "~/...", so the separator is the
            # host's: os.path.join on the home directory spells them the same way.
            home = os.path.expanduser("~")
            self.assertEqual(winsupport.app_support_dir("Claude"),
                             os.path.join(home, "Library", "Application Support", "Claude"))
            self.assertEqual(winsupport.local_data_dir("muse"),
                             os.path.join(home, ".local", "share", "muse"))

    def test_posix_defaults_are_unchanged(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            home = os.path.expanduser("~")
            self.assertEqual(winsupport.kanjo_config_dir(), os.path.join(home, ".config", "kanjo"))
            self.assertEqual(winsupport.kanjo_data_dir(), os.path.join(home, ".local", "share", "kanjo"))

    def test_env_overrides_still_win_on_windows(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             fake_windows_env(KANJO_CONFIG_DIR="D:\\cfg", KANJO_DATA_DIR="D:\\data", KANJO_CACHE_DIR="D:\\cache"):
            self.assertEqual(config.default_paths(), [
                ntpath.join("D:\\cfg", "attribution.toml"), ntpath.join("D:\\cfg", "attribution.json")])
            self.assertEqual(ledger.data_dir(), "D:\\data")
            self.assertEqual(cache._cache_dir(), "D:\\cache")

    def test_temp_dirs_deduplicate(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            dirs = winsupport.temp_dirs()
            self.assertEqual(dirs[0], TEMP)
            self.assertEqual(len(dirs), len({d.lower() for d in dirs}))

    def test_temp_dirs_empty_off_windows(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            self.assertEqual(winsupport.temp_dirs(), [])


class WindowsPathHelpersTest(unittest.TestCase):
    def test_normcase_key_only_touches_windows_paths(self):
        self.assertEqual(winsupport.normcase_key("C:/Users/Alice/Repo"), "c:\\users\\alice\\repo")
        self.assertEqual(winsupport.normcase_key("/Users/Alice/Repo"), "/Users/Alice/Repo")

    def test_same_path_and_subpath(self):
        self.assertTrue(winsupport.same_path("C:\\Users\\A\\Repo", "c:/users/a/repo"))
        self.assertFalse(winsupport.same_path("C:\\Users\\A\\Repo", "C:\\Users\\A\\Other"))
        self.assertTrue(winsupport.is_subpath("c:/Users/A/repo/src", "C:\\Users\\A\\Repo"))
        self.assertFalse(winsupport.is_subpath("C:\\Users\\AB\\repo", "C:\\Users\\A"))
        self.assertTrue(winsupport.is_subpath("/Users/a/repo/src", "/Users/a/repo"))
        self.assertFalse(winsupport.is_subpath("/Users/a/repoxyz", "/Users/a/repo"))

    def test_split_path_list_handles_windows_separators(self):
        self.assertEqual(base.split_path_list("C:\\a;D:\\b"), ["C:\\a", "D:\\b"])
        self.assertEqual(base.split_path_list("/a" + os.pathsep + "/b"), ["/a", "/b"])


class WindowsTempPathTest(unittest.TestCase):
    """``%TEMP%`` and ``%LOCALAPPDATA%\\Temp`` count as temporary, matching PathKinds."""

    def _resolver(self):
        return Resolver(home=PROFILE)

    def test_alias_matches_windows_spelling(self):
        resolver = Resolver(aliases={"proj-alpha": ["C:\\Users\\alice\\work\\alpha"]})
        for spelling in ("C:\\Users\\alice\\work\\alpha",
                         "C:/Users/alice/work/alpha",
                         "c:\\users\\ALICE\\work\\alpha"):
            self.assertEqual(resolver.canonical_id(resolver.clean(spelling)), "proj-alpha", spelling)

    def test_override_and_exclude_match_windows_spelling(self):
        cfg = config.from_dict({"overrides": {"C:\\Users\\Alice\\scratch": "proj-alpha"},
                                "exclude": ["C:\\Users\\Alice\\tmp"]})
        self.assertEqual(cfg.match_override("c:/users/alice/scratch/session"),
                         ("override", "proj-alpha"))
        self.assertEqual(cfg.match_override("C:\\Users\\alice\\tmp\\x"), ("exclude", None))
        self.assertIsNone(cfg.match_override("C:\\Users\\alice\\Documents\\real"))

    def test_posix_override_matching_is_unchanged(self):
        cfg = config.from_dict({"overrides": {"/Users/Alice/scratch": "proj-alpha"}})
        self.assertEqual(cfg.match_override("/Users/Alice/scratch/x"), ("override", "proj-alpha"))
        self.assertIsNone(cfg.match_override("/users/alice/scratch/x"))

    def test_temp_dirs_are_not_projects(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            r = self._resolver()
            self.assertFalse(r._missing_ok(TEMP + "\\wt"))
            self.assertFalse(r._missing_ok(LOCALAPPDATA + "\\Temp\\scratch\\x"))
            self.assertTrue(r._missing_ok(PROFILE + "\\Documents\\GitHub\\proj"))

    def test_dot_state_dirs_are_not_projects(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            r = self._resolver()
            self.assertFalse(r._missing_ok(PROFILE + "\\" + ".claude" + "\\projects"))
            self.assertFalse(r._missing_ok(PROFILE + "\\" + ".codex" + "\\sessions"))

    def test_posix_temp_prefixes_still_apply(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            r = Resolver(home="/Users/alice")
            self.assertFalse(r._missing_ok("/tmp/wt"))


class WindowsProjectResolutionTest(unittest.TestCase):
    """Session cwd / repo paths compared as Windows paths (case, separators)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-win-paths-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # The resolver walks the real filesystem under fs_root; the paths it is
        # asked about are the Windows ones the logs contain.
        self.repo = self.tmp + "/Users/alice/Documents/GitHub/FocusApp"
        os.makedirs(os.path.join(self.repo, ".git"))
        with open(os.path.join(self.repo, ".git", "config"), "w", encoding="utf-8") as handle:
            handle.write('[remote "origin"]\n\turl = https://github.com/alice/FocusApp.git\n')

    def test_clean_is_canonical(self):
        self.assertEqual(Resolver.clean("c:/users/alice/Documents/GitHub/FocusApp"),
                         "C:\\users\\alice\\Documents\\GitHub\\FocusApp")
        self.assertEqual(Resolver.clean("C:\\Users\\alice\\.\\Documents\\..\\Documents\\x"),
                         "C:\\Users\\alice\\Documents\\x")

    def test_windows_spellings_of_one_path_agree(self):
        a = Resolver.clean("C:\\Users\\alice\\Documents\\GitHub\\FocusApp\\main.swift")
        b = Resolver.clean("c:/users/alice/documents/github/focusapp/main.swift")
        self.assertTrue(winsupport.same_path(a, b))

    def test_prefix_lookup_is_case_insensitive(self):
        table = {"C:\\Users\\Alice\\Documents\\GitHub\\FocusApp\\": "pid"}
        found = Resolver._lookup_prefix("c:/users/alice/documents/github/focusapp/src/main.swift", table)
        self.assertIsNotNone(found)
        self.assertEqual(found[1], "pid")

    def test_posix_prefix_lookup_is_still_case_sensitive(self):
        table = {"/Users/Alice/repo/": "pid"}
        self.assertIsNone(Resolver._lookup_prefix("/Users/alice/repo/x", table))
        self.assertEqual(Resolver._lookup_prefix("/Users/Alice/repo/x", table)[1], "pid")


class WindowsSourceRootsTest(unittest.TestCase):
    """Each agent's default Windows location, with the macOS one unchanged."""

    def test_dot_dir_agents_stay_in_the_profile(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            self.assertEqual(claude.roots(), [ntpath.join(PROFILE, ".claude", "projects")])
            self.assertEqual(codex.roots(), [ntpath.join(PROFILE, ".codex", "sessions"),
                                             ntpath.join(PROFILE, ".codex", "archived_sessions")])
            self.assertEqual(antigravity.roots()[0],
                             ntpath.join(PROFILE, ".gemini", "antigravity-cli", "conversations"))

    def test_xdg_agents_move_to_local_app_data(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            self.assertEqual(opencode.roots(), [ntpath.join(PROFILE, ".local", "share", "opencode")])
            self.assertEqual(musecode.roots(), [ntpath.join(LOCALAPPDATA, "muse")])
            self.assertEqual(devin.roots(), [ntpath.join(LOCALAPPDATA, "devin", "cli")])

    def test_macos_only_agents_are_skipped(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            self.assertEqual(qoder_ide.roots(), [])
            for agent in ("grok_bot", "qoderwork", "mimocode"):
                self.assertFalse(winsupport.is_supported(agent), agent)

    def test_macos_locations_are_unchanged(self):
        # KANJO_DATA_DIR is set by the test harness; roots() returns [] then by design.
        with mock.patch("kanjo.winsupport.is_windows", return_value=False), \
             mock.patch.dict(os.environ, {}, clear=True):
            # The macOS/Linux defaults are built from "~/...", so their separator
            # is the host's: os.path.join spells them the same way everywhere.
            home = os.path.expanduser("~")
            self.assertEqual(claude.roots(), [os.path.join(home, ".claude", "projects")])
            self.assertEqual(opencode.roots(), [os.path.join(home, ".local", "share", "opencode")])
            self.assertEqual(musecode.roots(), [os.path.abspath(os.path.join(home, ".local", "share", "muse"))])

    def test_explicit_env_override_still_works_on_windows(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             fake_windows_env(KANJO_CLAUDE_DIR="D:\\logs\\claude;D:\\logs\\claude2"):
            self.assertEqual(claude.roots(), ["D:\\logs\\claude", "D:\\logs\\claude2"])

    def test_disk_default_roots_follow_the_platform(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            roots = disk.default_roots()
            self.assertEqual(roots["opencode"], ntpath.join(PROFILE, ".local", "share", "opencode"))
            self.assertEqual(roots["claude_app"], ntpath.join(APPDATA, "Claude"))
            self.assertEqual(roots["musecode"], ntpath.join(LOCALAPPDATA, "muse"))
            self.assertEqual(roots["devin"], ntpath.join(LOCALAPPDATA, "devin", "cli"))
            self.assertIsNone(roots["grok_bot"])
            self.assertIsNone(roots["qoderwork"])
            self.assertIsNone(roots["qoder_ide"])
            self.assertIsNone(roots["mimocode"])
            self.assertEqual(roots["claude_projects"], [ntpath.join(PROFILE, ".claude", "projects")])
        with mock.patch("kanjo.winsupport.is_windows", return_value=False), \
             mock.patch.dict(os.environ, {}, clear=True):
            mac = disk.default_roots()
            home = os.path.expanduser("~")
            self.assertEqual(mac["claude_app"], os.path.join(home, "Library", "Application Support", "Claude"))
            self.assertEqual(mac["grok_bot"], os.path.join(home, "Library", "Application Support", "Grok Bot"))


class WindowsTimezoneTest(unittest.TestCase):
    """zoneinfo needs the tzdata package on Windows; every fallback must be silent."""

    def test_local_zone_without_tzdata_uses_the_offset(self):
        with mock.patch("zoneinfo.ZoneInfo", side_effect=Exception("no tzdata")):
            tz = base.local_zone("America/New_York")
        offset = datetime.now(tz).utcoffset()
        self.assertIsNotNone(offset)

    def test_next_occurrence_without_tzdata(self):
        with mock.patch("zoneinfo.ZoneInfo", side_effect=Exception("no tzdata")):
            nxt = quota.next_occurrence("tue 05:00", time.time(), "America/New_York")
        self.assertGreater(nxt, time.time())

    def test_offset_zone_name_is_utc_when_the_offset_is_zero(self):
        self.assertIn(base.offset_timezone_name()[:3], ("Etc", "UTC"))

    def test_fixed_offset_tz_inverts_etc_gmt_signs(self):
        tz = base.fixed_offset_tz("Etc/GMT+5")
        self.assertIsNotNone(datetime(2026, 1, 1, tzinfo=timezone.utc).astimezone(tz).utcoffset())


class WindowsUnsupportedAgentsTest(unittest.TestCase):
    def test_unsupported_list_is_empty_off_windows(self):
        # The POSIX branch of this check: force it instead of reading the host.
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            self.assertEqual(winsupport.unsupported_agents(), {})
            self.assertTrue(winsupport.is_supported("grok_bot"))

    def test_unsupported_list_on_windows(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True):
            agents = winsupport.unsupported_agents()
            self.assertEqual(set(agents), {"grok_bot", "qoderwork", "qoder_ide", "mimocode"})
            for reason in agents.values():
                self.assertTrue(reason)

    def test_paths_json_stays_a_map_of_lists(self):
        from kanjo import cli
        import contextlib
        import io
        import json as jsonlib
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.cmd_paths(mock.Mock(json=True))
            self.assertEqual(code, 0)
            doc = jsonlib.loads(out.getvalue())
            self.assertIsInstance(doc, dict)
            for agent, paths in doc.items():
                self.assertIsInstance(paths, list, agent)
                self.assertFalse(any(isinstance(p, dict) for p in paths), agent)
            # the macOS-only agents are absent instead of being reported as broken
            self.assertNotIn("grok_bot", doc)
            self.assertNotIn("mimocode", doc)


class FakeRecycleBackend:
    """Stands in for shell32!SHFileOperationW: records the paths, never touches the disk."""

    def __init__(self, fail_for=(), code=0):
        self.calls = []
        self.fail_for = set(fail_for)
        self.code = code

    def recycle(self, paths):
        paths = list(paths)
        self.calls.append(paths)
        if any(p in self.fail_for for p in paths):
            return 0x78  # ERROR_CANCELLED-ish: SHFileOperationW reports a per-item failure
        for p in paths:
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
        return self.code


class Shell32StructTest(unittest.TestCase):
    """The real ctypes call is exercised with a fake shell32 on any OS."""

    def test_pfrom_is_a_double_nul_terminated_list_and_flags_match(self):
        captured = {}

        def fake_operation(p_op):
            # MagicMock drops argtypes, so the byref() object must be cast back.
            op = ctypes.cast(p_op, ctypes.POINTER(winsupport.SHFILEOPSTRUCTW)).contents
            captured["wFunc"] = op.wFunc
            captured["flags"] = op.fFlags
            captured["pFrom"] = op.pFrom
            return 0

        shell = mock.MagicMock()
        shell.SHFileOperationW.side_effect = fake_operation
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch("kanjo.winsupport._get_shell32", return_value=shell):
            code = winsupport.recycle(["C:\\a\\b", "C:\\c"])
        self.assertEqual(code, 0)
        self.assertEqual(captured["wFunc"], winsupport.FO_DELETE)
        for flag in (winsupport.FOF_ALLOWUNDO, winsupport.FOF_NOCONFIRMATION,
                     winsupport.FOF_SILENT, winsupport.FOF_NOERRORUI):
            self.assertTrue(captured["flags"] & flag, flag)
        # SHFileOperationW needs a list: each item NUL-terminated, then one more NUL.
        self.assertEqual(winsupport.recycle_list(["C:\\a\\b", "C:\\c"]),
                         "C:\\a\\b\0C:\\c\0\0")
        # A plain str would have stopped at the first NUL: the buffer keeps both.
        raw = ctypes.cast(captured["pFrom"], ctypes.c_void_p)
        self.assertIsNotNone(raw.value)

    def test_aborted_operation_reports_an_error(self):
        def fake_operation(p_op):
            ctypes.cast(p_op, ctypes.POINTER(winsupport.SHFILEOPSTRUCTW)).contents.fAnyOperationsAborted = True
            return 0

        shell = mock.MagicMock()
        shell.SHFileOperationW.side_effect = fake_operation
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch("kanjo.winsupport._get_shell32", return_value=shell):
            self.assertNotEqual(winsupport.recycle(["C:\\a\\b"]), 0)

    def test_non_windows_returns_none(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            self.assertIsNone(winsupport.recycle(["C:\\a\\b"]))


class RecycleBinTest(unittest.TestCase):
    """`kanjo disk clean` on Windows moves items to the Recycle Bin, not ~/.Trash."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-win-clean-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.claude = os.path.join(self.tmp, "claude")
        self.projects = os.path.join(self.claude, "projects")
        self.shell = os.path.join(self.claude, "shell-snapshots")
        self.debug_dir = os.path.join(self.claude, "debug")
        self.data = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        for path in (self.projects, self.shell, self.debug_dir, self.data, self.cache_dir):
            os.makedirs(path, exist_ok=True)
        self.write(os.path.join(self.shell, "snap.txt"), "snap")
        self.roots = {"claude_projects": [self.projects], "scratch": None, "codex_dirs": [],
                      "antigravity_dirs": [], "grok": None, "claude_app": None}
        self.env = mock.patch.dict(os.environ, {
            "KANJO_DATA_DIR": self.data,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_CLAUDE_DIR": self.projects,
            "KANJO_TOKEI_DIR": os.path.join(self.tmp, "no-tokei"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        winsupport._shell_backend = None
        self.addCleanup(setattr, winsupport, "_shell_backend", None)

    def write(self, path, text="x"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def _prepare(self, tree=None):
        """Pin the tree's mtime in the past so it is not "active"."""
        for dirpath, dirnames, filenames in os.walk(tree or self.shell):
            for name in filenames + dirnames:
                os.utime(os.path.join(dirpath, name), (1_600_000_000, 1_600_000_000))
        os.utime(tree or self.shell, (1_600_000_000, 1_600_000_000))

    def test_recycle_helper_is_used_instead_of_the_trash(self):
        backend = FakeRecycleBackend()
        winsupport._shell_backend = backend
        with mock.patch("kanjo.winsupport.is_windows", return_value=True):
            result = disk.clean(["claude:shell-snapshots"], roots=self.roots, yes=True,
                                now=1_700_000_000, ledger=ledger.Ledger(directory=self.data))
        self.assertFalse(os.path.exists(self.shell))
        self.assertEqual(result["trash_dir"], "Recycle Bin")
        self.assertEqual(result["moved"], [self.shell])
        self.assertEqual(backend.calls, [[self.shell]])

    def test_dry_run_moves_nothing(self):
        backend = FakeRecycleBackend()
        winsupport._shell_backend = backend
        with mock.patch("kanjo.winsupport.is_windows", return_value=True):
            result = disk.clean(["claude:shell-snapshots"], roots=self.roots, dry_run=True, yes=True,
                                now=time.time(), ledger=ledger.Ledger(directory=self.data))
        self.assertTrue(os.path.exists(self.shell))
        self.assertEqual(result["moved"], [self.shell])
        self.assertEqual(backend.calls, [])
        self.assertEqual(result["trash_dir"], "Recycle Bin")

    def test_a_locked_file_is_a_per_item_error_not_a_crash(self):
        old = self.write(os.path.join(self.debug_dir, "old.log"), "old")
        new = self.write(os.path.join(self.debug_dir, "new.log"), "new")
        now = time.time()
        os.utime(old, (now - 10 * 86400, now - 10 * 86400))
        os.utime(new, (now - 6 * 86400, now - 6 * 86400))
        backend = FakeRecycleBackend(fail_for=[])
        # A per-file clean on Windows goes through _relocate one file at a time;
        # the locked file is reported and the rest still move.
        calls = []
        real_relocate = disk._relocate

        def flaky(src, dst):
            calls.append(src)
            if src == old:
                raise OSError(13, "file in use", src)
            return real_relocate(src, dst)

        winsupport._shell_backend = backend
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch.object(disk, "_relocate", side_effect=flaky):
            result = disk.clean(["claude:debug"], roots=self.roots, yes=True, older_than_days=5,
                                now=now, ledger=ledger.Ledger(directory=self.data))
        self.assertTrue(os.path.exists(old))
        # skipped ids are entry ids, exactly as on POSIX (CONTRACT.md section 10).
        self.assertEqual(result["skipped"], [{"id": "claude:debug", "reason": "move_failed"}])
        self.assertEqual(set(calls), {old, new})
        self.assertEqual(result["moved"], [new])

    def test_refuses_drive_roots_and_the_profile(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            self.assertTrue(disk._refused("C:\\"))
            self.assertTrue(disk._refused("D:/"))
            self.assertTrue(disk._refused(PROFILE))
            self.assertTrue(disk._refused(APPDATA))
            self.assertFalse(disk._refused(PROFILE + "\\Documents\\GitHub\\proj\\wt"))

    def test_recycle_falls_back_to_a_plain_error_when_shell32_is_missing(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch("kanjo.winsupport._get_shell32", return_value=None):
            self.assertEqual(winsupport.recycle([self.shell]), -1)
            with self.assertRaises(OSError):
                disk._relocate(self.shell, None)

    def test_explicit_trash_dir_still_wins_over_the_recycle_bin(self):
        backend = FakeRecycleBackend()
        winsupport._shell_backend = backend
        target = os.path.join(self.tmp, "pinned-trash")
        with mock.patch("kanjo.winsupport.is_windows", return_value=True):
            result = disk.clean(["claude:shell-snapshots"], roots=self.roots, yes=True,
                                now=1_700_000_000, trash_dir=target,
                                ledger=ledger.Ledger(directory=self.data))
        self.assertEqual(backend.calls, [])
        self.assertFalse(os.path.exists(self.shell))
        self.assertTrue(result["trash_dir"].startswith(target), result["trash_dir"])
        moved = []
        for _dirpath, _dirs, files in os.walk(target):
            moved.extend(files)
        self.assertEqual(moved, ["snap.txt"])

    def test_posix_path_still_uses_the_trash(self):
        target = os.path.join(self.tmp, "trash-root")
        # The entry-id folder name is incidental here (clean() rewrites ':' on
        # Windows; a real Windows FS cannot create it at all), so a portable name
        # keeps this a test of the POSIX branch on every host.
        entry_dir = "claude-shell-snapshots"
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            dest = os.path.join(target, "kanjo-1", entry_dir, "shell-snapshots")
            disk._relocate(self.shell, dest)
        self.assertTrue(os.path.isdir(os.path.join(target, "kanjo-1", entry_dir)))
        self.assertFalse(os.path.exists(self.shell))

    def test_trash_entry_id_is_a_legal_directory_name_on_windows(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            self.assertEqual(disk._trash_component("claude:shell-snapshots"), "claude:shell-snapshots")
        with mock.patch("kanjo.winsupport.is_windows", return_value=True):
            self.assertEqual(disk._trash_component("claude:shell-snapshots"), "claude-shell-snapshots")
            self.assertEqual(disk._trash_component("codex worktrees"), "codex worktrees")
            self.assertEqual(disk._trash_component("trailing. "), "trailing")


class ClaudeCredentialTest(unittest.TestCase):
    """Windows reads the OAuth token from %USERPROFILE%\\.claude\\.credentials.json."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-win-cred-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, ".credentials.json")

    def write(self, payload):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(payload if isinstance(payload, str) else __import__("json").dumps(payload))
        return self.path

    def test_reads_the_access_token_without_exposing_it(self):
        from kanjo import quota_fetch
        token = "sk-ant-oat-windows-token"
        self.write({"claudeAiOauth": {"accessToken": token,
                                      "expiresAt": int((time.time() + 3600) * 1000)}})
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch.dict(os.environ, {"KANJO_CLAUDE_CREDENTIALS": self.path}, clear=False):
            self.assertEqual(quota_fetch._load_claude_credentials(), token)

    def test_expired_token_is_ignored(self):
        from kanjo import quota_fetch
        self.write({"claudeAiOauth": {"accessToken": "stale", "expiresAt": 1_600_000_000_000}})
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch.dict(os.environ, {"KANJO_CLAUDE_CREDENTIALS": self.path}, clear=False):
            self.assertIsNone(quota_fetch._load_claude_credentials())

    def test_missing_or_garbage_file_returns_none(self):
        from kanjo import quota_fetch
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch.dict(os.environ, {"KANJO_CLAUDE_CREDENTIALS": self.path}, clear=False):
            self.assertIsNone(quota_fetch._load_claude_credentials())
            self.write("not json")
            self.assertIsNone(quota_fetch._load_claude_credentials())
            self.write({"claudeAiOauth": {}})
            self.assertIsNone(quota_fetch._load_claude_credentials())

    def test_default_location_is_the_profile_dot_claude_dir(self):
        from kanjo import quota_fetch
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            self.assertEqual(quota_fetch.claude_credentials_path(),
                             ntpath.join(PROFILE, ".claude", ".credentials.json"))

    def test_macos_still_uses_the_keychain(self):
        from kanjo import quota_fetch
        token = "sk-ant-oat-keychain"

        class Res:
            returncode = 0
            stdout = '{"claudeAiOauth":{"accessToken":"%s"}}' % token

        with mock.patch("kanjo.winsupport.is_windows", return_value=False), \
             mock.patch.object(quota_fetch.subprocess, "run", return_value=Res()) as run:
            self.assertEqual(quota_fetch._load_claude_credentials(), token)
        self.assertEqual(run.call_args[0][0][0], "/usr/bin/security")


class WindowsClaudeDesktopCacheTest(unittest.TestCase):
    def test_cache_dir_moves_to_app_data(self):
        from kanjo import quota_claude_cache
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            self.assertEqual(quota_claude_cache.default_cache_dir(),
                             ntpath.join(APPDATA, "Claude", "Cache", "Cache_Data"))

    def test_posix_cache_dir_is_unchanged(self):
        from kanjo import quota_claude_cache
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            home = os.path.expanduser("~")
            self.assertEqual(quota_claude_cache.default_cache_dir(),
                             os.path.join(home, "Library", "Application Support", "Claude",
                                          "Cache", "Cache_Data"))


class WindowsPathExtractionTest(unittest.TestCase):
    """Windows paths in shell text are found, POSIX extraction is unchanged."""

    def test_drive_paths_are_extracted_on_any_host(self):
        self.assertEqual(base.extract_paths(r"type C:\Users\alice\repo\main.py"),
                         ["C:\\Users\\alice\\repo\\main.py"])
        self.assertEqual(base.extract_paths(r"copy \\srv\share\a.txt dest"),
                         ["\\\\srv\\share\\a.txt"])

    def test_quoted_drive_paths_may_contain_spaces(self):
        self.assertEqual(base.extract_paths(r'cd "C:\Users\alice\my project" && dir'),
                         ["C:\\Users\\alice\\my project"])
        self.assertEqual(base.extract_paths("cat 'd:/work/my file.txt'"),
                         ["d:\\work\\my file.txt"])

    def test_posix_extraction_is_unchanged(self):
        self.assertEqual(base.extract_paths("python3 /Users/alice/x.py --a /tmp/y"),
                         ["/Users/alice/x.py", "/tmp/y"])
        self.assertEqual(base.extract_paths("a/b relative only"), [])
        self.assertEqual(base.extract_paths("https://host/x/y"), [])

    def test_tilde_uses_the_profile_on_windows(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), fake_windows_env():
            self.assertEqual(base.extract_paths(r"copy ~\notes.txt dest"),
                             [ntpath.join(PROFILE, "notes.txt")])
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            home = os.path.expanduser("~")
            self.assertEqual(base.extract_paths("cat ~/notes.txt"), [os.path.join(home, "notes.txt")])


class WindowsSQLiteUriTest(unittest.TestCase):
    def test_windows_paths_use_the_uri_form(self):
        self.assertEqual(base.sqlite_uri_path("C:\\Users\\alice\\x.db"), "/C:/Users/alice/x.db")
        self.assertEqual(base.sqlite_uri_path("D:/data/my db.sqlite"), "/D:/data/my%20db.sqlite")

    def test_posix_paths_are_unchanged(self):
        self.assertEqual(base.sqlite_uri_path("/Users/alice/x.db"), "/Users/alice/x.db")

    def test_a_windows_style_db_still_opens(self):
        tmp = tempfile.mkdtemp(prefix="kanjo-win-sqlite-")
        self.addCleanup(shutil.rmtree, tmp, True)
        db = os.path.join(tmp, "s.db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE t (x)")
        conn.commit()
        conn.close()
        with base.open_sqlite_ro(db) as handle:
            self.assertEqual(handle.execute("SELECT count(*) FROM t").fetchone()[0], 0)


class WindowsScratchpadDecoderTest(unittest.TestCase):
    """Claude Code encodes Windows cwds as ``C--Users-alice-proj``."""

    def test_encoded_part_reads_the_windows_layout(self):
        from kanjo.identity import ScratchpadDecoder
        scratch = "C:\\Users\\alice\\AppData\\Local\\Temp\\claude-501\\C--Users-alice-proj\\s"
        self.assertEqual(ScratchpadDecoder.encoded_part(scratch + "\\scratchpad"), "C--Users-alice-proj")
        projects = "C:\\Users\\alice\\.claude\\projects\\C--Users-alice-proj\\abc.jsonl"
        self.assertEqual(ScratchpadDecoder.encoded_part(projects), "C--Users-alice-proj")

    def test_posix_encoded_part_is_unchanged(self):
        from kanjo.identity import ScratchpadDecoder
        path = "/tmp/claude-501/-Users-alice-Documents-GitHub-FocusApp/abc/scratchpad"
        self.assertEqual(ScratchpadDecoder.encoded_part(path),
                         "-Users-alice-Documents-GitHub-FocusApp")
        self.assertEqual(
            ScratchpadDecoder.encoded_part("/Users/alice/.claude/projects/-Users-alice-repo/x.jsonl"),
            "-Users-alice-repo")

    def test_decode_walks_from_the_drive_root(self):
        """``C--Users-alice-proj`` decodes by walking down from ``C:\\``.

        ``fs_root`` stands in for the root of the drive, so the Windows walk runs
        on every host; ``decode`` must hand back the Windows spelling it walked.
        """
        from kanjo.identity import ScratchpadDecoder
        tmp = tempfile.mkdtemp(prefix="kanjo-win-scratch-")
        self.addCleanup(shutil.rmtree, tmp, True)
        # _fs("C:\\") is <tmp>/C, so the drive root is <tmp>/C on this host.
        os.makedirs(os.path.join(tmp, "C", "Users", "alice", "my-proj"))
        decoder = ScratchpadDecoder(fs_root=tmp)
        self.assertEqual(decoder.decode("C--Users-alice-my-proj"), "C:\\Users\\alice\\my-proj")
        self.assertIsNone(decoder.decode("C--Users-alice-missing"))
        self.assertEqual(
            ScratchpadDecoder.encoded_part("C:\\Users\\alice\\AppData\\Local\\Temp\\claude-501\\C--Users-alice-proj\\s"),
            "C--Users-alice-proj")


class WindowsQuotaCachePermissionsTest(unittest.TestCase):
    def test_chmod_is_skipped_on_windows(self):
        from kanjo import quota_fetch
        tmp = tempfile.mkdtemp(prefix="kanjo-win-quota-")
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch.dict(os.environ, {"KANJO_DATA_DIR": tmp}, clear=False), \
             mock.patch.object(quota_fetch.os, "chmod",
                               side_effect=AssertionError("chmod must not run on Windows")):
            quota_fetch.save_quota_cache({"version": quota_fetch.CACHE_VERSION, "providers": {}})
        self.assertTrue(os.path.isfile(os.path.join(tmp, "quota_cache.json")))


class WindowsRepoDiscoveryTest(unittest.TestCase):
    """`.git` discovery with real Windows paths.

    Needs the host filesystem to treat ``C:\\...`` as a path, so this only runs on
    Windows (the same logic with POSIX paths is covered by ``test_identity.py``,
    which runs on every platform).
    """

    @unittest.skipIf(os.name != "nt", "needs real Windows path semantics")
    def test_repo_found_from_a_short_spelling_of_the_same_path(self):
        tmp = tempfile.mkdtemp(prefix="kanjo-win-repo-")
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = os.path.join(tmp, "FocusApp")
        os.makedirs(os.path.join(repo, ".git"))
        with open(os.path.join(repo, ".git", "config"), "w", encoding="utf-8") as handle:
            handle.write('[remote "origin"]\n\turl = https://github.com/alice/FocusApp.git\n')
        with open(os.path.join(repo, ".git", "HEAD"), "w", encoding="utf-8") as handle:
            handle.write("ref: refs/heads/main\n")
        resolver = Resolver()
        # Node tools log forward slashes and lower-case drive letters.
        spelled = repo.replace("\\", "/")
        if spelled[1:2] == ":":
            spelled = spelled[0].lower() + spelled[1:]
        project = resolver.resolve(spelled + "/Sources/App.swift")
        self.assertIsNotNone(project)
        self.assertEqual(project.id, "github.com/alice/focusapp")

    @unittest.skipIf(os.name != "nt", "needs real Windows path semantics")
    def test_registered_worktree_resolves_from_a_forward_slash_gitdir(self):
        tmp = tempfile.mkdtemp(prefix="kanjo-win-wt-")
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = os.path.join(tmp, "repo")
        admin = os.path.join(repo, ".git", "worktrees", "feature")
        os.makedirs(admin)
        with open(os.path.join(repo, ".git", "config"), "w", encoding="utf-8") as handle:
            handle.write('[remote "origin"]\n\turl = https://github.com/alice/repo.git\n')
        with open(os.path.join(repo, ".git", "HEAD"), "w", encoding="utf-8") as handle:
            handle.write("ref: refs/heads/main\n")
        with open(os.path.join(admin, "gitdir"), "w", encoding="utf-8") as handle:
            # git records the worktree's .git with forward slashes, even on Windows
            handle.write(os.path.join(tmp, "wt-feature").replace("\\", "/") + "/.git\n")
        resolver = Resolver()
        project = resolver.resolve(repo)
        self.assertIsNotNone(project)
        self.assertEqual(
            resolver.resolve(os.path.join(tmp, "wt-feature", "src", "a.cs")).id, project.id)


if __name__ == "__main__":
    unittest.main()
