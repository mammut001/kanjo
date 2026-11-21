"""Rounding reconciliation in public / family periods never makes a cost negative."""
import os
import sys
import unittest

FAMILY_SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "family-server"))
if FAMILY_SERVER_DIR not in sys.path:
    sys.path.insert(0, FAMILY_SERVER_DIR)

from family_server.validation import validate_report_payload

from kanjo import export
from kanjo.export import PublicPeriodAgg
from kanjo.sources.base import Message


def _msg(tokens):
    return Message(ts=1793000000.0, model="m", input=tokens)


class PublicCostReconcileTest(unittest.TestCase):
    def check(self, period):
        for name in ("by_provider", "by_agent"):
            costs = [item["cost_usd"] for item in period[name]]
            self.assertTrue(all(c >= 0 for c in costs), (name, costs))
            self.assertLessEqual(abs(sum(costs) - period["cost_usd"]), 0.01 + 1e-9, (name, costs))

    def test_token_leader_with_zero_cost(self):
        agg = PublicPeriodAgg("2026-10-02")
        agg.add_message(_msg(1000000), "claude", "anthropic", 0.0001, "2026-10-02")
        agg.add_message(_msg(10), "codex", "openai", 0.0051, "2026-10-02")
        agg.add_message(_msg(10), "copilot", "other", 0.0051, "2026-10-02")
        self.check(agg.to_json())

    def test_all_time_override_from_rounded_months(self):
        agg = PublicPeriodAgg("all")
        for month in range(6):
            day = "2026-%02d-01" % (month + 1)
            agg.add_message(_msg(1000000), "claude", "anthropic", 0.0, day)
            agg.add_message(_msg(10), "copilot", "other", 0.004, day)
            agg.add_message(_msg(10), "codex", "openai", 0.004, day)
        period = agg.to_json(cost_usd_override=0.0)
        self.check(period)
        doc = {"all_time": period, "months": [], "weeks": []}
        self.assertEqual(export.check_public_summary_invariants(doc), [])

    def test_family_payload_with_reconciled_period_is_accepted(self):
        agg = PublicPeriodAgg("all")
        for month in range(6):
            day = "2026-%02d-01" % (month + 1)
            agg.add_message(_msg(1000000), "claude", "anthropic", 0.0, day)
            agg.add_message(_msg(10), "copilot", "other", 0.004, day)
        period = agg.to_json(cost_usd_override=0.0)
        report = {
            "schema_version": 1, "kind": "kanjo-family-report", "member_label": None,
            "device": {"id": "0123456789abcdef", "name": "Mac", "os": "macos"},
            "generated_at": "2026-10-02T00:00:00Z", "timezone": "UTC",
            "generated_by": "kanjo test", "cost_note": export.COST_NOTE,
            "scope": {"agents": ["all"], "since": None, "accounts_filter": None},
            "plans": {}, "quota_windows": {},
            "summary": {"all_time": period, "months": [], "weeks": [], "days": []},
        }
        self.assertEqual(export.check_family_report_invariants(report), [])
        self.assertIsNone(validate_report_payload(report))

    def test_invariant_checks_flag_negative_costs(self):
        period = {"period": "all", "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total": 0},
                  "cost_usd": 0.0,
                  "by_provider": [{"provider": "a", "tokens": {"input": 0, "output": 0, "cache_read": 0,
                                                                "cache_write": 0, "total": 0}, "cost_usd": -0.01},
                                  {"provider": "b", "tokens": {"input": 0, "output": 0, "cache_read": 0,
                                                                "cache_write": 0, "total": 0}, "cost_usd": 0.01}],
                  "by_agent": [{"agent": "x", "tokens_total": 0, "cost_usd": 0.0}],
                  "top_models": [], "models_used": []}
        self.assertTrue(any("< 0" in p for p in export.check_public_summary_invariants(
            {"all_time": period, "months": [], "weeks": []})))
        self.assertTrue(any("< 0" in p for p in export.check_family_report_invariants(
            {"kind": "kanjo-family-report", "schema_version": 1, "summary": {"all_time": period}})))


if __name__ == "__main__":
    unittest.main()
