"""Tests for validation module (syntax warnings, schema and privacy checks)."""

import copy
import importlib
import json
import os
import unittest
import warnings

import family_server.validation
from family_server.validation import validate_report_payload


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


class TestScopeValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "report.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            cls.base_payload = json.load(f)

    def test_valid_scope(self):
        for scope in (
            {"agents": ["antigravity"], "since": "2026-11-09"},
            {"agents": ["antigravity", "claude"], "since": "2026-11-09T00:00:00Z"},
            {"agents": ["all"], "since": None},
            {"agents": []},
            {"since": "2026-11-09"},
            {},
        ):
            payload = copy.deepcopy(self.base_payload)
            payload["scope"] = scope
            err = validate_report_payload(payload)
            self.assertIsNone(err, f"Scope {scope} rejected: {err}")

    def test_invalid_scope(self):
        for bad_scope, expected_sub in (
            ("not_a_dict", "scope must be an object"),
            (123, "scope must be an object"),
            ({"agents": "not_a_list"}, "scope.agents must be a list"),
            ({"agents": [123]}, "scope.agents must contain short strings"),
            ({"agents": ["x" * 65]}, "scope.agents must contain short strings"),
            ({"since": 123}, "scope.since must be a string or null"),
            ({"since": "x" * 65}, "scope.since must be a string or null"),
        ):
            payload = copy.deepcopy(self.base_payload)
            payload["scope"] = bad_scope
            err = validate_report_payload(payload)
            self.assertIsNotNone(err)
            self.assertIn(expected_sub, err)


if __name__ == "__main__":
    unittest.main()
