"""Tests for kanjo.net (TLS trust on macOS) and its use by the family/quota HTTP calls."""

import io
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

from kanjo import cli, net, quota_fetch

PEM = b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n"
FRAMEWORK_EXE = "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
CERT_FAILED = "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate"


def _completed(stdout=PEM, returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=b"")


class _NetTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-net-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.cache_file = os.path.join(self.cache_dir, net._ROOTS_CACHE_NAME)
        for p in (mock.patch.dict(os.environ, {"KANJO_CACHE_DIR": self.cache_dir}),
                  mock.patch.object(net, "_context", None)):
            p.start()
            self.addCleanup(p.stop)

    def _age_cache(self, seconds):
        when = time.time() - seconds
        os.utime(self.cache_file, (when, when))

    def _write_cache(self, data):
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(self.cache_file, "wb") as fh:
            fh.write(data)


class SslContextDarwinTest(_NetTestBase):
    def setUp(self):
        super().setUp()
        self.ctx = mock.MagicMock(spec=ssl.SSLContext)
        for p in (mock.patch.object(net, "_on_macos", return_value=True),
                  mock.patch("ssl.create_default_context", return_value=self.ctx)):
            p.start()
            self.addCleanup(p.stop)
        self.mock_run = mock.patch("subprocess.run", return_value=_completed()).start()
        self.addCleanup(mock.patch.stopall)

    def _loaded_cafiles(self):
        return [c.kwargs.get("cafile") for c in self.ctx.load_verify_locations.call_args_list]

    def test_exports_system_roots_without_w_flag(self):
        net.ssl_context()
        self.mock_run.assert_called_once()
        argv = self.mock_run.call_args.args[0]
        self.assertEqual(argv[0], "/usr/bin/security")
        self.assertEqual(argv[1:4], ["find-certificate", "-a", "-p"])
        self.assertEqual(argv[4], "/System/Library/Keychains/SystemRootCertificates.keychain")
        self.assertNotIn("-w", argv)
        self.assertEqual(self.mock_run.call_args.kwargs.get("timeout"), 10)

    def test_writes_cache_and_loads_it(self):
        self.assertIs(net.ssl_context(), self.ctx)
        with open(self.cache_file, "rb") as fh:
            self.assertEqual(fh.read(), PEM)
        self.assertIn(self.cache_file, self._loaded_cafiles())

    def test_fresh_cache_is_reused(self):
        self._write_cache(PEM)
        net.ssl_context()
        self.mock_run.assert_not_called()
        self.assertIn(self.cache_file, self._loaded_cafiles())

    def test_stale_cache_is_refreshed(self):
        self._write_cache(b"old")
        self._age_cache(8 * 24 * 3600)
        self.mock_run.return_value = _completed(stdout=PEM + b"NEW")
        net.ssl_context()
        self.mock_run.assert_called_once()
        with open(self.cache_file, "rb") as fh:
            self.assertEqual(fh.read(), PEM + b"NEW")

    def test_stale_cache_used_when_refresh_fails(self):
        self._write_cache(PEM)
        self._age_cache(8 * 24 * 3600)
        self.mock_run.side_effect = subprocess.TimeoutExpired(cmd="security", timeout=10)
        self.assertIs(net.ssl_context(), self.ctx)
        self.assertIn(self.cache_file, self._loaded_cafiles())

    def test_nonzero_security_exit_writes_nothing(self):
        self.mock_run.return_value = _completed(stdout=b"", returncode=44)
        net.ssl_context()
        self.assertFalse(os.path.exists(self.cache_file))

    def test_local_bundle_and_certifi_loaded_when_present(self):
        fake_certifi = mock.MagicMock()
        fake_certifi.where.return_value = "/fake/certifi.pem"
        real_isfile = os.path.isfile
        with mock.patch.object(net.os.path, "isfile",
                               side_effect=lambda p: p == net._LOCAL_CA_BUNDLE or real_isfile(p)), \
             mock.patch.dict(sys.modules, {"certifi": fake_certifi}):
            net.ssl_context()
        cafiles = self._loaded_cafiles()
        self.assertIn(net._LOCAL_CA_BUNDLE, cafiles)
        self.assertIn("/fake/certifi.pem", cafiles)

    def test_context_built_once_per_process(self):
        net.ssl_context()
        net.ssl_context()
        self.assertEqual(self.mock_run.call_count, 1)


class SslContextFailureTest(_NetTestBase):
    def test_security_failure_still_returns_verifying_context(self):
        with mock.patch.object(net, "_on_macos", return_value=True), \
             mock.patch("subprocess.run", side_effect=OSError("no security")):
            ctx = net.ssl_context()
        self.assertIsInstance(ctx, ssl.SSLContext)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_non_darwin_returns_default_without_subprocess(self):
        with mock.patch.object(net, "_on_macos", return_value=False), \
             mock.patch("subprocess.run") as mock_run:
            ctx = net.ssl_context()
        mock_run.assert_not_called()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_linux_platform_skips_subprocess(self):
        with mock.patch.object(sys, "platform", "linux"), mock.patch("subprocess.run") as mock_run:
            net.ssl_context()
        mock_run.assert_not_called()


class CertHintTest(unittest.TestCase):
    def _cert_error(self):
        return urllib.error.URLError(ssl.SSLCertVerificationError(1, CERT_FAILED))

    def test_python_org_mac_gets_hint(self):
        with mock.patch.object(net, "_on_macos", return_value=True), \
             mock.patch.object(net.sys, "executable", FRAMEWORK_EXE):
            hint = net.cert_hint(self._cert_error())
        self.assertIn("Install Certificates.command", hint)
        self.assertIn("/Applications", hint)

    def test_non_python_org_mac_gets_no_hint(self):
        with mock.patch.object(net, "_on_macos", return_value=True), \
             mock.patch.object(net.sys, "executable", "/opt/homebrew/bin/python3"), \
             mock.patch.object(net.sys, "prefix", "/opt/homebrew"):
            self.assertEqual(net.cert_hint(self._cert_error()), "")

    def test_other_platform_gets_no_hint(self):
        with mock.patch.object(net, "_on_macos", return_value=False), \
             mock.patch.object(net.sys, "executable", FRAMEWORK_EXE):
            self.assertEqual(net.cert_hint(self._cert_error()), "")

    def test_non_cert_error_gets_no_hint(self):
        with mock.patch.object(net, "_on_macos", return_value=True), \
             mock.patch.object(net.sys, "executable", FRAMEWORK_EXE):
            self.assertEqual(net.cert_hint(urllib.error.URLError(OSError("Connection refused"))), "")

    def test_bare_ssl_error_detected(self):
        self.assertTrue(net.is_cert_error(ssl.SSLError("CERTIFICATE_VERIFY_FAILED")))
        self.assertFalse(net.is_cert_error(ValueError("nope")))


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b'{"received_at": 1}'


class FamilyReportTlsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-net-family-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sentinel = object()
        for p in (mock.patch.dict(os.environ, {
                      "KANJO_FAMILY_TOKEN": "test-token",
                      "KANJO_CACHE_DIR": os.path.join(self.tmp, "cache"),
                      "KANJO_DATA_DIR": os.path.join(self.tmp, "data")}),
                  mock.patch("kanjo.report_family.ssl_context", return_value=self.sentinel),
                  mock.patch("kanjo.report_family.build_family_report",
                             return_value={"kind": "kanjo-family-report"})):
            p.start()
            self.addCleanup(p.stop)

    def _run(self, urlopen_side_effect):
        out = io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=urlopen_side_effect) as mock_open, \
             mock.patch("sys.stdout", out):
            code = cli.main(["report-family", "--url", "https://usage.example.test", "--no-cache"])
        return code, json.loads(out.getvalue().strip().splitlines()[-1]), mock_open

    def test_successful_post_passes_context(self):
        code, payload, mock_open = self._run(lambda req, timeout=30, **kw: _Resp())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "sent")
        self.assertIs(mock_open.call_args.kwargs["context"], self.sentinel)

    def test_cert_error_message_includes_hint(self):
        def fail(req, timeout=30, **kw):
            raise urllib.error.URLError(ssl.SSLCertVerificationError(1, CERT_FAILED))
        with mock.patch.object(net, "_on_macos", return_value=True), \
             mock.patch.object(net.sys, "executable", FRAMEWORK_EXE):
            code, payload, _ = self._run(fail)
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertIn("CERTIFICATE_VERIFY_FAILED", payload["message"])
        self.assertIn("Install Certificates.command", payload["message"])

    def test_other_error_message_has_no_hint(self):
        def fail(req, timeout=30, **kw):
            raise urllib.error.URLError(OSError("Connection refused"))
        with mock.patch.object(net, "_on_macos", return_value=True), \
             mock.patch.object(net.sys, "executable", FRAMEWORK_EXE):
            code, payload, _ = self._run(fail)
        self.assertEqual(code, 1)
        self.assertNotIn("Install Certificates.command", payload["message"])


class QuotaFetchTlsTest(unittest.TestCase):
    """The quota fetchers pass the shared verifying context to urlopen."""

    def _capture(self, fn):
        sentinel = object()
        with mock.patch.object(quota_fetch, "ssl_context", return_value=sentinel), \
             mock.patch.object(quota_fetch, "is_network_disabled", return_value=False), \
             mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("stop")) as mock_open, \
             mock.patch.object(quota_fetch, "_load_codex_auth", return_value=("tok", None)), \
             mock.patch.object(quota_fetch, "_load_grok_auth", return_value="tok"), \
             mock.patch.object(quota_fetch, "_load_claude_credentials", return_value="tok"):
            fn(time.time())
        self.assertTrue(mock_open.called)
        for c in mock_open.call_args_list:
            self.assertIs(c.kwargs.get("context"), sentinel)

    def test_codex_passes_context(self):
        self._capture(quota_fetch.fetch_codex_quota)

    def test_grok_passes_context(self):
        self._capture(quota_fetch.fetch_grok_quota)

    def test_claude_passes_context(self):
        self._capture(quota_fetch.fetch_claude_quota)


if __name__ == "__main__":
    unittest.main()
