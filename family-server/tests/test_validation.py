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


class TestDeviceValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "report.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            cls.base_payload = json.load(f)

    def test_valid_device_and_optional_legacy(self):
        # Legacy without device
        legacy = copy.deepcopy(self.base_payload)
        legacy.pop("device", None)
        self.assertIsNone(validate_report_payload(legacy))

        for os_name in ("macos", "linux", "windows"):
            payload = copy.deepcopy(self.base_payload)
            payload["device"] = {"id": "0123456789abcdef", "name": "Alice MacBook", "os": os_name}
            self.assertIsNone(validate_report_payload(payload))

    def test_invalid_device(self):
        bad_cases = (
            ("not_a_dict", "device must be an object"),
            ({"id": "short", "name": "Mac", "os": "macos"}, "device.id"),
            ({"id": "0123456789ABCDEF", "name": "Mac", "os": "macos"}, "device.id"),
            ({"id": "0123456789abcdef\n", "name": "Mac", "os": "macos"}, "device.id"),
            ({"id": "0123456789abcdeg", "name": "Mac", "os": "macos"}, "device.id"),
            ({"id": "0123456789abcdef", "name": "", "os": "macos"}, "device.name"),
            ({"id": "0123456789abcdef", "name": "   ", "os": "macos"}, "device.name"),
            ({"id": "0123456789abcdef", "name": "x" * 41, "os": "macos"}, "device.name"),
            ({"id": "0123456789abcdef", "name": "Mac\nBox", "os": "macos"}, "device.name"),
            ({"id": "0123456789abcdef", "name": "Mac", "os": "freebsd"}, "device.os"),
        )
        for bad_dev, expected in bad_cases:
            payload = copy.deepcopy(self.base_payload)
            payload["device"] = bad_dev
            err = validate_report_payload(payload)
            self.assertIsNotNone(err, f"Expected failure for {bad_dev}")
            self.assertIn(expected, err)


if __name__ == "__main__":
    unittest.main()

class TestUntrustedReports(unittest.TestCase):
    def test_rejects_unsafe_numbers_and_nested_shapes(self):
        with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'report.json'), encoding='utf-8') as f:
            base = json.load(f)
        for change in ('nan', 'negative', 'huge', 'sixth_day', 'month', 'provider', 'numeric_string', 'provider_tokens'):
            payload = copy.deepcopy(base)
            if change == 'nan':
                payload['summary']['all_time']['tokens']['total'] = float('nan')
            elif change == 'negative':
                payload['summary']['all_time']['cost_usd'] = -1
            elif change == 'huge':
                payload['summary']['all_time']['tokens']['total'] = 10 ** 400
            elif change == 'sixth_day':
                payload['summary']['days'][5] = {'period': 'x', 'tokens': {}, 'cost_usd': 'bad'}
            elif change == 'month':
                payload['summary']['months'][0] = {'period': 'x', 'tokens': {}, 'cost_usd': 'bad'}
            elif change == 'provider':
                payload['summary']['all_time']['by_provider'] = 5
            elif change == 'numeric_string':
                payload['summary']['all_time']['tokens']['total'] = 'bad'
            else:
                payload['summary']['all_time']['by_provider'][0]['tokens'] = 'bad'
            with self.subTest(change=change):
                self.assertIsNotNone(validate_report_payload(payload))

    def test_rejects_untyped_dashboard_fields(self):
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "report.json"), encoding="utf-8") as f:
            base = json.load(f)
        cases = [
            ("cost_note", lambda p: p.update(cost_note=[])),
            ("plans", lambda p: p.update(plans={"antigravity": []})),
            ("quota", lambda p: p.update(quota_windows={"antigravity": []})),
            ("quota reset", lambda p: p["quota_windows"]["antigravity"].update(weekly_resets_at=[])),
            ("quota percent", lambda p: p["quota_windows"]["antigravity"].update(weekly_used_percent="bad")),
            ("extra windows", lambda p: p["quota_windows"]["antigravity"].update(extra_windows=[{"label": []}])),
            ("period date", lambda p: p["summary"]["all_time"].update(first_day=[])),
            ("provider label", lambda p: p["summary"]["all_time"]["by_provider"][0].update(label=[])),
            ("provider name", lambda p: p["summary"]["all_time"]["by_provider"][0].update(provider=[])),
            ("model name", lambda p: p["summary"]["all_time"]["top_models"][0].update(model=[])),
            ("agent label", lambda p: p["summary"]["all_time"]["by_agent"][0].update(label=[])),
            ("models used", lambda p: p["summary"]["all_time"].update(models_used=[[]])),
            ("long label", lambda p: p.update(member_label="x" * 4097)),
            ("boolean cost", lambda p: p["summary"]["all_time"].update(cost_usd=True)),
            ("device os", lambda p: p.update(device={"id": "0123456789abcdef", "name": "Mac", "os": []})),
        ]
        for name, change in cases:
            with self.subTest(name=name):
                payload = copy.deepcopy(base)
                change(payload)
                self.assertIsNotNone(validate_report_payload(payload))
