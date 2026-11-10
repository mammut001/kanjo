"""Tests for validation module (syntax warnings, schema and privacy checks)."""

import importlib
import unittest
import warnings

import family_server.validation


class TestValidationSyntaxWarning(unittest.TestCase):
    def test_import_emits_no_syntax_warning(self):
        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always", SyntaxWarning)
            importlib.reload(family_server.validation)
            syntax_warnings = [
                w for w in recorded_warnings if issubclass(w.category, SyntaxWarning)
            ]
            self.assertEqual(
                syntax_warnings,
                [],
                f"Importing family_server.validation emitted SyntaxWarning: {syntax_warnings}",
            )


if __name__ == "__main__":
    unittest.main()
