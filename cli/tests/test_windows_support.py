"""Unit tests for Windows platform compatibility, Credential Manager, and path handling."""

from __future__ import annotations

import io
import json
import ntpath
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from kanjo import cli, disk, ledger, cache, winsupport, quota_fetch
from kanjo.identity import Resolver
from kanjo.sources import base, antigravity


class WindowsSupportUnitTest(unittest.TestCase):
    def tearDown(self):
        winsupport._powershell_runner = None
        winsupport._cred_backend = None

    def test_powershell_non_windows(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            self.assertEqual(winsupport.powershell("Get-Date"), "")

    def test_powershell_runner_injection(self):
        winsupport._powershell_runner = lambda cmd, to: f"mocked: {cmd}"
        self.assertEqual(winsupport.powershell("echo hi"), "mocked: echo hi")

    def test_cred_non_windows_noop(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            self.assertIsNone(winsupport.cred_read("Target"))
            self.assertFalse(winsupport.cred_write("Target", "secret"))
            self.assertFalse(winsupport.cred_delete("Target"))

    def test_cred_backend_injection(self):
        class MockBackend:
            def __init__(self):
                self.store = {}
            def cred_read(self, target):
                return self.store.get(target)
            def cred_write(self, target, secret):
                self.store[target] = secret
                return True
            def cred_delete(self, target):
                self.store.pop(target, None)
                return True

        backend = MockBackend()
        winsupport._cred_backend = backend

        self.assertIsNone(winsupport.cred_read("test-target"))
        self.assertTrue(winsupport.cred_write("test-target", "my-secret-123"))
        self.assertEqual(winsupport.cred_read("test-target"), "my-secret-123")
        self.assertTrue(winsupport.cred_delete("test-target"))
        self.assertIsNone(winsupport.cred_read("test-target"))

    def test_real_cred_advapi32_mock(self):
        """Verify advapi32 ctypes struct packing/unpacking with UTF-16LE."""
        with mock.patch("kanjo.winsupport.is_windows", return_value=True):
            # We can test ctypes marshalling by mocking WinDLL
            mock_advapi = mock.MagicMock()
            written_creds = []

            def mock_cred_write(p_cred, flags):
                cred = p_cred.contents
                blob = bytes(winsupport.ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize))
                written_creds.append({
                    "target": cred.TargetName,
                    "type": cred.Type,
                    "persist": cred.Persist,
                    "blob": blob,
                    "secret": blob.decode("utf-16-le"),
                })
                return 1

            mock_advapi.CredWriteW.side_effect = mock_cred_write
            mock_advapi.CredDeleteW.return_value = 1

            with mock.patch("kanjo.winsupport._get_advapi32", return_value=mock_advapi):
                self.assertTrue(winsupport.cred_write("KanjoFamilyReport", "secret-token-xyz"))
                self.assertEqual(len(written_creds), 1)
                self.assertEqual(written_creds[0]["target"], "KanjoFamilyReport")
                self.assertEqual(written_creds[0]["type"], winsupport.CRED_TYPE_GENERIC)
                self.assertEqual(written_creds[0]["persist"], winsupport.CRED_PERSIST_LOCAL_MACHINE)
                self.assertEqual(written_creds[0]["secret"], "secret-token-xyz")
                self.assertTrue(winsupport.cred_delete("KanjoFamilyReport"))


class FamilyTokenCliTest(unittest.TestCase):
    def tearDown(self):
        winsupport._powershell_runner = None
        winsupport._cred_backend = None

    def test_family_token_mac_notice(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=False):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = cli.main(["family-token", "status"])
            self.assertEqual(code, 0)
            self.assertIn("On macOS, the family token is managed in the Kanjo App Settings", out.getvalue())

    def test_family_token_status_windows(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True):
            with mock.patch("kanjo.winsupport.cred_read", return_value="some-token"):
                out = io.StringIO()
                with mock.patch("sys.stdout", out):
                    code = cli.main(["family-token", "status"])
                self.assertEqual(code, 0)
                self.assertEqual(out.getvalue().strip(), "set")

            with mock.patch("kanjo.winsupport.cred_read", return_value=None):
                out = io.StringIO()
                with mock.patch("sys.stdout", out):
                    code = cli.main(["family-token", "status"])
                self.assertEqual(code, 0)
                self.assertEqual(out.getvalue().strip(), "not set")

    def test_family_token_set_windows(self):
        written = {}
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch("kanjo.winsupport.cred_write", side_effect=lambda k, v: written.setdefault(k, v) or True):
            out = io.StringIO()
            stdin = io.StringIO("super-secret-token\n")
            with mock.patch("sys.stdout", out), mock.patch("sys.stdin", stdin):
                code = cli.main(["family-token", "set"])
            self.assertEqual(code, 0)
            self.assertIn("token set", out.getvalue())
            self.assertEqual(written.get("KanjoFamilyReport"), "super-secret-token")

    def test_family_token_clear_windows(self):
        deleted = []
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch("kanjo.winsupport.cred_delete", side_effect=lambda k: deleted.append(k) or True):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = cli.main(["family-token", "clear"])
            self.assertEqual(code, 0)
            self.assertIn("token cleared", out.getvalue())
            self.assertEqual(deleted, ["KanjoFamilyReport"])


class ReportFamilyWindowsFallbackTest(unittest.TestCase):
    def test_report_family_reads_credential_when_env_unset(self):
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("kanjo.winsupport.cred_read", return_value="token-from-credmgr"):
            captured_headers = {}

            class MockResponse:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def read(self):
                    return b'{"status":"ok","received_at":12345}'

            def mock_urlopen(req, timeout=30):
                captured_headers.update(req.headers)
                return MockResponse()

            with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen), \
                 mock.patch("kanjo.report_family.build_family_report", return_value={"kind": "kanjo-family-report"}):
                out = io.StringIO()
                with mock.patch("sys.stdout", out):
                    code = cli.main(["report-family", "--url", "http://127.0.0.1:8788", "--no-cache"])
                self.assertEqual(code, 0)
                self.assertEqual(captured_headers.get("Authorization"), "Bearer token-from-credmgr")


class AntigravityQuotaWindowsTest(unittest.TestCase):
    def test_find_antigravity_processes_windows_powershell(self):
        ps_output = (
            "1234 C:\\Users\\Alice\\AppData\\Local\\Programs\\Antigravity\\language_server_windows_x64.exe "
            "--csrf_token=csrf_12345 --extension_server_port=49152\n"
            "5678 notepad.exe\n"
        )
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch.dict(os.environ, {"ANTIGRAVITY_CSRF_TOKEN": "", "ANTIGRAVITY_LS_ADDRESS": ""}), \
             mock.patch("kanjo.winsupport.powershell", return_value=ps_output):
            procs = quota_fetch._find_antigravity_processes()
            self.assertEqual(len(procs), 1)
            self.assertEqual(procs[0]["pid"], 1234)
            self.assertEqual(procs[0]["csrf_token"], "csrf_12345")
            self.assertEqual(procs[0]["port"], 49152)

    def test_antigravity_ports_windows_netstat_fallback(self):
        # 1. PowerShell Get-NetTCPConnection succeeds
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch("kanjo.winsupport.powershell", return_value="55123\n55124\n"):
            ports = quota_fetch._antigravity_ports(1234, 49152)
            self.assertEqual(sorted(ports), [49152, 55123, 55124])

        # 2. PowerShell returns nothing, fallback to netstat -ano
        netstat_out = (
            "  TCP    127.0.0.1:55125        0.0.0.0:0              LISTENING       1234\n"
            "  TCP    0.0.0.0:80             0.0.0.0:0              LISTENING       4\n"
        )
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch("kanjo.winsupport.powershell", return_value=""), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout=netstat_out, returncode=0)):
            ports = quota_fetch._antigravity_ports(1234, 49152)
            self.assertEqual(sorted(ports), [49152, 55125])


class WindowsDataCacheDirTest(unittest.TestCase):
    def test_default_dirs_on_windows(self):
        env = {
            "LOCALAPPDATA": "C:\\Users\\Alice\\AppData\\Local",
            "USERPROFILE": "C:\\Users\\Alice",
        }
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch.dict(os.environ, env, clear=True):
            d_dir = ledger.data_dir()
            c_dir = cache._cache_dir()
            # Windows paths use '\' regardless of the OS running the test.
            local = "C:\\Users\\Alice\\AppData\\Local"
            self.assertEqual(d_dir, ntpath.join(local, "kanjo", "data"))
            self.assertEqual(c_dir, ntpath.join(local, "kanjo", "cache"))

    def test_env_override_takes_precedence(self):
        env = {
            "LOCALAPPDATA": "C:\\Users\\Alice\\AppData\\Local",
            "KANJO_DATA_DIR": "D:\\custom\\data",
            "KANJO_CACHE_DIR": "D:\\custom\\cache",
        }
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(ledger.data_dir(), "D:\\custom\\data")
            self.assertEqual(cache._cache_dir(), "D:\\custom\\cache")


class WindowsDiskGuardTest(unittest.TestCase):
    def test_disk_command_runs_on_windows(self):
        """`kanjo disk` is supported on Windows now (batch 4): it scans and reports JSON."""
        tmp = tempfile.mkdtemp(prefix="kanjo-win-disk-")
        self.addCleanup(shutil.rmtree, tmp, True)
        roots = {key: [] for key in disk.default_roots()}
        with mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch.dict(os.environ, {"KANJO_DATA_DIR": os.path.join(tmp, "data"),
                                          "KANJO_CACHE_DIR": os.path.join(tmp, "cache")}, clear=False):
            doc = disk.report(roots=roots, now=time.time(), rescan=True)
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(doc["agents"], [])


class WindowsPathHandlingTest(unittest.TestCase):
    def test_clean_path_windows_drive(self):
        p1 = Resolver.clean(r"C:\Users\alice\project")
        self.assertTrue(p1.startswith("C:") or p1.startswith("c:"))
        p2 = Resolver.clean("C:/Users/alice/project")
        self.assertTrue(p2.startswith("C:") or p2.startswith("c:"))
        p3 = Resolver.clean("file:///C:/Users/alice/project")
        self.assertTrue(p3.startswith("C:") or p3.startswith("c:"))

    def test_ensure_project_windows_path(self):
        resolver = Resolver()
        proj = resolver.ensure_project(r"C:\Users\alice\myproject")
        self.assertEqual(proj.name, "myproject")
        self.assertIsNone(proj.remote)

    def test_alias_with_windows_path(self):
        resolver = Resolver(aliases={"proj-alpha": [r"C:\Users\alice\work\alpha"]})
        canonical = resolver.canonical_id(r"C:\Users\alice\work\alpha")
        self.assertEqual(canonical, "proj-alpha")

    def test_absolutize_windows_path(self):
        res1 = base.absolutize("app.py", r"C:\Users\alice\project")
        self.assertIn(r"C:\Users\alice\project", res1)
        self.assertTrue(res1.endswith("app.py"))

        res2 = base.absolutize(r"C:\Users\alice\project\main.py", r"C:\other")
        self.assertEqual(res2, os.path.normpath(r"C:\Users\alice\project\main.py"))

    def test_uri_path_antigravity(self):
        self.assertEqual(
            antigravity._uri_path("file:///C:/Users/alice/project"),
            "C:/Users/alice/project"
        )
        self.assertEqual(
            antigravity._uri_path(r"C:\Users\alice\project"),
            r"C:\Users\alice\project"
        )


if __name__ == "__main__":
    unittest.main()
