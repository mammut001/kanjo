"""Regression: Localizable.strings + TUI i18n stay consistent with source usage."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "check_l10n.py"


class L10nCorrectnessTest(unittest.TestCase):
    def test_check_l10n_script(self):
        self.assertTrue(CHECKER.is_file(), f"missing {CHECKER}")
        # Import the checker so failures show as assertions, not just exit codes.
        sys.path.insert(0, str(CHECKER.parent))
        import check_l10n  # type: ignore

        result = check_l10n.run_checks(ROOT)
        if result.errors:
            self.fail("\n".join(result.errors))
        # Unused keys are reported for humans; do not fail the suite.
        report = check_l10n.format_report(result)
        print(report)

    def test_check_l10n_cli_exit_zero(self):
        proc = subprocess.run(
            [sys.executable, str(CHECKER), "--root", str(ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            self.fail(proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
