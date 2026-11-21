import os
import unittest
from unittest import mock

from kanjo.sources import base


class LocalTimezoneTests(unittest.TestCase):
    def test_explicit_unix_tz_overrides_system_zone(self):
        for tz, expected in (("UTC", "UTC"), ("", "UTC"), ("GMT", "GMT")):
            with self.subTest(tz=tz), mock.patch.dict(os.environ, {"TZ": tz}), \
                 mock.patch.object(base.winsupport, "is_windows", return_value=False), \
                 mock.patch.object(base.os.path, "realpath", return_value="/usr/share/zoneinfo/Asia/Shanghai"):
                self.assertEqual(base.local_timezone_name(), expected)
