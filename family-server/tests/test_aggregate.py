"""Unit tests for pure per-member multi-device report merging."""

import json
import unittest

from family_server.aggregate import merge_member_reports


def _make_period(
    period: str,
    first_day: str,
    last_day: str,
    inp: int,
    out: int,
    cost: float,
    agent: str = "antigravity",
    provider: str = "google",
    model: str = "gemini-3.8-pro",
    start: str = None,
) -> dict:
    total = inp + out
    p = {
        "period": period,
        "first_day": first_day,
        "last_day": last_day,
        "tokens": {
            "input": inp,
            "output": out,
            "cache_read": 0,
            "cache_write": 0,
            "total": total,
        },
        "cost_usd": cost,
        "by_provider": [
            {
                "provider": provider,
                "label": provider.capitalize(),
                "tokens": {
                    "input": inp,
                    "output": out,
                    "cache_read": 0,
                    "cache_write": 0,
                    "total": total,
                },
                "cost_usd": cost,
                "models": [{"model": model, "tokens_total": total, "cost_usd": cost}],
            }
        ],
        "by_agent": [
            {
                "agent": agent,
                "label": agent.capitalize(),
                "tokens_total": total,
                "cost_usd": cost,
            }
        ],
        "top_models": [
            {
                "model": model,
                "provider": provider,
                "tokens_total": total,
                "cost_usd": cost,
            }
        ],
        "models_used": [model],
    }
    if start is not None:
        p["start"] = start
    return p


def _make_report(
    device_id: str,
    device_name: str,
    device_os: str,
    received_at: str,
    timezone: str,
    generated_by: str,
    all_time: dict,
    months=None,
    weeks=None,
    days=None,
    plans=None,
    quota_windows=None,
    member_label=None,
) -> dict:
    payload = {
        "schema_version": 1,
        "kind": "kanjo-family-report",
        "member_label": member_label,
        "generated_at": received_at,
        "timezone": timezone,
        "generated_by": generated_by,
        "plans": plans or {},
        "quota_windows": quota_windows or {},
        "summary": {
            "all_time": all_time,
            "months": months or [],
            "weeks": weeks or [],
            "days": days or [],
        },
    }
    if device_id:
        payload["device"] = {"id": device_id, "name": device_name, "os": device_os}
    return {
        "device_id": device_id,
        "device_name": device_name if device_id else None,
        "received_at": received_at,
        "generated_at": received_at,
        "payload_json": json.dumps(payload),
    }


class TestMergeMemberReports(unittest.TestCase):
    def test_empty_reports_returns_none(self):
        self.assertIsNone(merge_member_reports([]))

    def test_merge_two_devices_sums_all_levels(self):
        rep_mac = _make_report(
            device_id="1111222233334444",
            device_name="Alice-Mac",
            device_os="macos",
            received_at="2026-11-10T12:00:00+00:00",
            timezone="Asia/Shanghai",
            generated_by="kanjo 0.6.3",
            all_time=_make_period("all", "2026-11-01", "2026-11-10", 4000, 1000, 1.50,
                                  agent="antigravity", provider="google", model="gemini-3.8-pro"),
            months=[
                _make_period("2026-11", "2026-11-01", "2026-11-10", 4000, 1000, 1.50,
                             agent="antigravity", provider="google", model="gemini-3.8-pro"),
            ],
            weeks=[
                _make_period("2026-W46", "2026-11-09", "2026-11-10", 1000, 500, 0.50,
                             start="2026-11-09"),
            ],
            days=[
                _make_period("2026-11-09", "2026-11-09", "2026-11-09", 3000, 500, 1.00),
                _make_period("2026-11-10", "2026-11-10", "2026-11-10", 1000, 500, 0.50),
            ],
            plans={"antigravity": "Google AI Ultra"},
            # Newer report, but has NO quota_windows -> should pick Linux's quota_windows
            quota_windows={},
        )

        rep_linux = _make_report(
            device_id="aaaa5555bbbb6666",
            device_name="Alice-Linux",
            device_os="linux",
            received_at="2026-11-10T11:00:00+00:00",
            timezone="UTC",
            generated_by="kanjo 0.6.3",
            all_time=_make_period("all", "2026-10-20", "2026-11-09", 2000, 500, 2.00,
                                  agent="claude", provider="anthropic", model="claude-opus-5.5"),
            months=[
                _make_period("2026-10", "2026-10-20", "2026-10-25", 1000, 200, 1.00,
                             agent="claude", provider="anthropic", model="claude-opus-5.5"),
                _make_period("2026-11", "2026-11-03", "2026-11-09", 1000, 300, 1.00,
                             agent="claude", provider="anthropic", model="claude-opus-5.5"),
            ],
            weeks=[
                _make_period("2026-W46", "2026-11-09", "2026-11-09", 1000, 300, 1.00,
                             agent="claude", provider="anthropic", model="claude-opus-5.5",
                             start="2026-11-09"),
            ],
            days=[
                _make_period("2026-11-09", "2026-11-09", "2026-11-09", 1000, 300, 1.00,
                             agent="claude", provider="anthropic", model="claude-opus-5.5"),
            ],
            plans={"claude": "Claude Pro"},
            quota_windows={"antigravity": {"weekly_used_percent": 35.0, "weekly_resets_at": "2026-11-14T12:00:00Z"}},
        )

        merged = merge_member_reports([rep_linux, rep_mac])
        self.assertIsNotNone(merged)
        self.assertFalse(merged["_meta"]["legacy_excluded"])
        self.assertEqual(len(merged["_meta"]["devices"]), 2)

        # all_time summed
        at = merged["summary"]["all_time"]
        self.assertEqual(at["first_day"], "2026-10-20")
        self.assertEqual(at["last_day"], "2026-11-10")
        self.assertEqual(at["tokens"]["input"], 6000)
        self.assertEqual(at["tokens"]["output"], 1500)
        self.assertEqual(at["tokens"]["total"], 7500)
        self.assertEqual(at["cost_usd"], 3.50)
        self.assertEqual({a["agent"] for a in at["by_agent"]}, {"antigravity", "claude"})
        self.assertEqual({p["provider"] for p in at["by_provider"]}, {"google", "anthropic"})
        self.assertEqual(at["models_used"], ["claude-opus-5.5", "gemini-3.8-pro"])

        # months: 2026-10 (linux only) and 2026-11 (merged)
        months = {m["period"]: m for m in merged["summary"]["months"]}
        self.assertEqual(sorted(months.keys()), ["2026-10", "2026-11"])
        self.assertEqual(months["2026-11"]["first_day"], "2026-11-01")
        self.assertEqual(months["2026-11"]["last_day"], "2026-11-10")
        self.assertEqual(months["2026-11"]["tokens"]["total"], 6300)
        self.assertEqual(months["2026-11"]["cost_usd"], 2.50)

        # weeks: 2026-W46 merged
        weeks = {w["period"]: w for w in merged["summary"]["weeks"]}
        self.assertEqual(weeks["2026-W46"]["tokens"]["total"], 2800)
        self.assertEqual(weeks["2026-W46"]["start"], "2026-11-09")

        # days: 2026-11-09 merged (two agents/models), 2026-11-10 mac only
        days = {d["period"]: d for d in merged["summary"]["days"]}
        self.assertEqual(sorted(days.keys()), ["2026-11-09", "2026-11-10"])
        self.assertEqual(days["2026-11-09"]["tokens"]["total"], 4800)
        self.assertEqual(days["2026-11-09"]["cost_usd"], 2.00)
        self.assertEqual({a["agent"] for a in days["2026-11-09"]["by_agent"]}, {"antigravity", "claude"})
        self.assertEqual(len(days["2026-11-09"]["top_models"]), 2)

        # plans union
        self.assertEqual(merged["plans"], {"antigravity": "Google AI Ultra", "claude": "Claude Pro"})

        # quota_windows picked from most recent device that has them (rep_linux)
        self.assertEqual(merged["quota_windows"]["antigravity"]["weekly_used_percent"], 35.0)

    def test_legacy_excluded_when_device_report_is_newer(self):
        legacy = _make_report(
            device_id="",
            device_name="",
            device_os="",
            received_at="2026-11-09T10:00:00+00:00",
            timezone="UTC",
            generated_by="kanjo 0.6.2",
            all_time=_make_period("all", "2026-11-01", "2026-11-09", 5000, 1000, 5.0),
        )
        tagged = _make_report(
            device_id="1111222233334444",
            device_name="MacBook",
            device_os="macos",
            received_at="2026-11-10T10:00:00+00:00",
            timezone="UTC",
            generated_by="kanjo 0.6.3",
            all_time=_make_period("all", "2026-11-01", "2026-11-10", 6000, 1000, 6.0),
        )

        merged = merge_member_reports([legacy, tagged])
        self.assertTrue(merged["_meta"]["legacy_excluded"])
        self.assertEqual(len(merged["_meta"]["devices"]), 1)
        # Must NOT double-count legacy
        self.assertEqual(merged["summary"]["all_time"]["tokens"]["total"], 7000)

    def test_legacy_included_when_newer_than_all_device_reports(self):
        tagged = _make_report(
            device_id="1111222233334444",
            device_name="MacBook",
            device_os="macos",
            received_at="2026-11-09T10:00:00+00:00",
            timezone="UTC",
            generated_by="kanjo 0.6.3",
            all_time=_make_period("all", "2026-11-01", "2026-11-09", 1000, 500, 1.0),
        )
        legacy = _make_report(
            device_id="",
            device_name="",
            device_os="",
            received_at="2026-11-10T10:00:00+00:00",
            timezone="UTC",
            generated_by="kanjo 0.6.2",
            all_time=_make_period("all", "2026-11-01", "2026-11-10", 2000, 500, 2.0),
        )

        merged = merge_member_reports([tagged, legacy])
        self.assertFalse(merged["_meta"]["legacy_excluded"])
        self.assertEqual(merged["_meta"]["legacy_excluded_count"], 0)
        self.assertEqual(len(merged["_meta"]["devices"]), 2)
        self.assertEqual(merged["summary"]["all_time"]["tokens"]["total"], 4000)

    def test_legacy_rule_two_legacy_groups_and_one_tagged_device(self):
        # legacy '' (Nov 8), tagged device (Nov 10), legacy:3 (Nov 11)
        # -> '' is excluded (older than tagged), legacy:3 is included (newer than tagged)
        leg_own = _make_report(
            device_id="",
            device_name="",
            device_os="",
            received_at="2026-11-08T10:00:00+00:00",
            timezone="UTC",
            generated_by="kanjo 0.6.2",
            all_time=_make_period("all", "2026-11-01", "2026-11-08", 5000, 0, 5.0),
        )
        tagged = _make_report(
            device_id="1111222233334444",
            device_name="Payton-Mac",
            device_os="macos",
            received_at="2026-11-10T10:00:00+00:00",
            timezone="UTC",
            generated_by="kanjo 0.6.3",
            all_time=_make_period("all", "2026-11-01", "2026-11-10", 6000, 0, 6.0),
        )
        leg_merged_newer = _make_report(
            device_id="legacy:3",
            device_name="",
            device_os="",
            received_at="2026-11-11T10:00:00+00:00",
            timezone="UTC",
            generated_by="kanjo 0.6.2",
            all_time=_make_period("all", "2026-11-01", "2026-11-11", 2500, 0, 2.5),
        )
        leg_merged_newer["device_name"] = None

        merged = merge_member_reports(
            [leg_own, tagged, leg_merged_newer],
            member_names={3: "Windows VM"},
        )
        self.assertTrue(merged["_meta"]["legacy_excluded"])
        self.assertEqual(merged["_meta"]["legacy_excluded_count"], 1)
        # Only tagged (6000) + legacy:3 (2500) = 8500
        self.assertEqual(merged["summary"]["all_time"]["tokens"]["total"], 8500)
        self.assertEqual(len(merged["_meta"]["devices"]), 2)
        names = {d["device_id"]: d["device_name"] for d in merged["_meta"]["devices"]}
        self.assertEqual(names["legacy:3"], "旧版客户端 (Windows VM)")
        self.assertEqual(names["1111222233334444"], "Payton-Mac")

        # Now make legacy:3 ALSO older than tagged (Nov 9 < Nov 10) -> both legacy groups excluded
        leg_merged_older = _make_report(
            device_id="legacy:3",
            device_name="",
            device_os="",
            received_at="2026-11-09T10:00:00+00:00",
            timezone="UTC",
            generated_by="kanjo 0.6.2",
            all_time=_make_period("all", "2026-11-01", "2026-11-09", 2500, 0, 2.5),
        )
        leg_merged_older["device_name"] = None

        merged_both_excluded = merge_member_reports([leg_own, tagged, leg_merged_older])
        self.assertTrue(merged_both_excluded["_meta"]["legacy_excluded"])
        self.assertEqual(merged_both_excluded["_meta"]["legacy_excluded_count"], 2)
        self.assertEqual(merged_both_excluded["summary"]["all_time"]["tokens"]["total"], 6000)
        self.assertEqual(len(merged_both_excluded["_meta"]["devices"]), 1)

        # Without any tagged devices -> both legacy groups included and summed
        merged_no_tagged = merge_member_reports([leg_own, leg_merged_older])
        self.assertFalse(merged_no_tagged["_meta"]["legacy_excluded"])
        self.assertEqual(merged_no_tagged["_meta"]["legacy_excluded_count"], 0)
        self.assertEqual(merged_no_tagged["summary"]["all_time"]["tokens"]["total"], 7500)
        self.assertEqual(len(merged_no_tagged["_meta"]["devices"]), 2)
        names_no_map = {d["device_id"]: d["device_name"] for d in merged_no_tagged["_meta"]["devices"]}
        self.assertEqual(names_no_map[""], "旧版客户端")
        self.assertEqual(names_no_map["legacy:3"], "旧版客户端")


if __name__ == "__main__":
    unittest.main()
