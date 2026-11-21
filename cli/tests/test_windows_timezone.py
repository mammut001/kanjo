import contextlib
import io
import os
import sys
import types
import unittest
from unittest import mock
from zoneinfo import ZoneInfo
from datetime import datetime

from kanjo.sources import base


class WindowsTimezoneTests(unittest.TestCase):
    def setUp(self):
        self.windows = mock.patch.object(base.winsupport, "is_windows", return_value=True)
        self.windows.start()
        self.addCleanup(self.windows.stop)
        self.warned = mock.patch.object(base, "_fixed_offset_warned", False)
        self.warned.start()
        self.addCleanup(self.warned.stop)

    def registry(self, name):
        key = mock.MagicMock()
        registry = types.SimpleNamespace(HKEY_LOCAL_MACHINE=object(), OpenKey=mock.Mock(return_value=key),
                                         QueryValueEx=mock.Mock(return_value=(name, 1)))
        return registry

    def test_registry_maps_zone_and_preserves_dst(self):
        registry = self.registry("Eastern Standard Time")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.dict(sys.modules, {"winreg": registry}):
            name = base.local_timezone_name()
        self.assertEqual(name, "America/New_York")
        registry.OpenKey.assert_called_once_with(registry.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation")
        registry.QueryValueEx.assert_called_once_with(mock.ANY, "TimeZoneKeyName")
        self.assertNotEqual(datetime(2024, 1, 1, tzinfo=ZoneInfo(name)).utcoffset(),
                            datetime(2024, 7, 1, tzinfo=ZoneInfo(name)).utcoffset())

    def test_explicit_tz_takes_precedence(self):
        registry = self.registry("Eastern Standard Time")
        with mock.patch.dict(os.environ, {"TZ": "Europe/Paris"}, clear=True), mock.patch.dict(sys.modules, {"winreg": registry}):
            self.assertEqual(base.local_timezone_name(), "Europe/Paris")
        registry.OpenKey.assert_not_called()

    def test_missing_or_unknown_registry_warns_once(self):
        for value in ("Unknown fictional zone", None):
            registry = self.registry(value)
            if value is None:
                registry.OpenKey.side_effect = OSError("missing")
            with self.subTest(value=value), mock.patch.dict(os.environ, {}, clear=True), \
                 mock.patch.dict(sys.modules, {"winreg": registry}), \
                 mock.patch.object(base, "offset_timezone_name", return_value="Etc/GMT+5"), \
                 mock.patch.object(base, "_fixed_offset_warned", False), contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(base.local_timezone_name(), "Etc/GMT+5")
                self.assertEqual(base.local_timezone_name(), "Etc/GMT+5")
                self.assertEqual(stderr.getvalue().count("warning"), 1)

    def test_non_iana_explicit_tz_does_not_query_registry(self):
        registry = self.registry("Eastern Standard Time")
        with mock.patch.dict(os.environ, {"TZ": "EST5EDT"}, clear=True), \
             mock.patch.dict(sys.modules, {"winreg": registry}), \
             mock.patch.object(base, "offset_timezone_name", return_value="UTC"), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(base.local_timezone_name(), "UTC")
        registry.OpenKey.assert_not_called()
