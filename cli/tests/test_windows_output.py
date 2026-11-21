"""Windows redirected output and timezone fallback regression tests."""
import io
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from kanjo import cli
from kanjo.sources import base


class WindowsOutputTests(unittest.TestCase):
    def run_output(self, args):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")
        env = {key: value for key, value in os.environ.items() if key != "PYTHONIOENCODING"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch("sys.stdout", stream):
            self.assertEqual(cli.main(args), 0)
            stream.flush()
            result = raw.getvalue()
        stream.close()
        return result

    def test_usage_redirected_in_both_languages(self):
        sample = str(Path(__file__).resolve().parents[2] / "ui/fixtures/sample.json")
        for lang in ("en", "zh"):
            with self.subTest(lang=lang):
                output = self.run_output(["usage", "--once", "--no-color", "--data", sample, "--lang", lang])
                self.assertTrue(any(b >= 128 for b in output))
                output.decode("utf-8")

    def test_export_redirected_non_ascii(self):
        with mock.patch("kanjo.cli.build_export", return_value={"name": "项目"}), \
             mock.patch("kanjo.cli.check_invariants", return_value=[]):
            output = self.run_output(["export", "--no-cache"])
        self.assertEqual(json.loads(output.decode("utf-8")), {"name": "项目"})

    def test_explicit_encoding_is_respected(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with mock.patch.dict(os.environ, {"PYTHONIOENCODING": "cp1252"}), \
             mock.patch("kanjo.winsupport.is_windows", return_value=True), \
             mock.patch("sys.stdout", stream):
            with self.assertRaises(SystemExit) as exit_code:
                cli.main(["--version"])
            self.assertEqual(exit_code.exception.code, 0)
            self.assertEqual(stream.encoding, "cp1252")
        stream.close()

    def test_timezone_fallback_warns_once(self):
        err = io.StringIO()
        with mock.patch.object(base, "_fixed_offset_warned", False), \
             mock.patch("zoneinfo.ZoneInfo", side_effect=Exception("missing")), \
             mock.patch("sys.stderr", err):
            base.local_zone("America/New_York")
            base.local_zone("America/New_York")
        self.assertEqual(len(err.getvalue().splitlines()), 1)
        self.assertIn("fixed timezone offset", err.getvalue())
