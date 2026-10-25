import os
import unittest

import kanjo


class VersionTests(unittest.TestCase):
    def test_package_version_matches_version_file(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(root, "VERSION"), encoding="utf-8") as handle:
            self.assertEqual(kanjo.__version__, handle.read().strip())


if __name__ == "__main__":
    unittest.main()
