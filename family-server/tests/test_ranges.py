"""Unit tests for the pure per-range aggregation (family_server.ranges)."""

from datetime import date, datetime, timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from family_server import ranges
from family_server.aggregate import merge_member_reports
from family_server.dashboard import compute_cycle_boundaries

TORONTO = ZoneInfo("America/Toronto")


def _day(period, tokens, cost=1.0, models=None, agent="antigravity", provider="google",
         inp=None, out=0, cache_read=0):
    """Daily Period; ``models`` is [(name, tokens, cost)] for top_models (may be partial)."""
    if models is None:
        models = [("gemini-3.8-pro", tokens, cost)]
    inp = tokens - out - cache_read if inp is None else inp
    tok = {"input": inp, "output": out, "cache_read": cache_read, "cache_write": 0, "total": tokens}
    return {
        "period": period,
        "first_day": period,
        "last_day": period,
        "tokens": tok,
        "cost_usd": cost,
        "by_provider": [{"provider": provider, "label": provider.capitalize(), "tokens": dict(tok),
                         "cost_usd": cost, "models": []}],
        "by_agent": [{"agent": agent, "label": agent, "tokens_total": tokens, "cost_usd": cost}],
        "top_models": [{"model": n, "provider": provider, "tokens_total": t, "cost_usd": c} for n, t, c in models],
    }


def _summary(days, months=None, all_time=None):
    return {"days": days, "weeks": [], "months": months or [], "all_time": all_time or {}}


def _member(mid, name, summary, devices=None):
    return {"id": mid, "name": name, "color": "#3b82f6", "summary": summary,
            "devices": devices if devices is not None else ([summary] if summary else [])}


def _build(members, today, anchor=None, tracking_start=None, pool=None, now=None):
    now = now or datetime(today.year, today.month, today.day, 17, 0, tzinfo=timezone.utc)
    return ranges.build_ranges(members, today=today, now=now,
                               cycle=compute_cycle_boundaries(anchor, today),
                               tracking_start=tracking_start, pool=pool, tz=TORONTO)


class RangeBoundsTests(unittest.TestCase):
    cycle = (date(2026, 10, 9), date(2026, 11, 9), date(2026, 12, 9))

    def test_week_starts_monday(self):
        for today in (date(2026, 11, 16), date(2026, 11, 19), date(2026, 11, 22)):
            with self.subTest(today=today):
                b = ranges.range_bounds("this_week", today, self.cycle)
                self.assertEqual((b["start"], b["end"]), (date(2026, 11, 16), date(2026, 11, 22)))
                lw = ranges.range_bounds("last_week", today, self.cycle)
                self.assertEqual((lw["start"], lw["end"]), (date(2026, 11, 9), date(2026, 11, 15)))
                # A finished week compares with the whole week before it.
                self.assertEqual(lw["prev"], (date(2026, 11, 2), date(2026, 11, 8)))
                self.assertEqual(lw["compare_mode"], "full")

    def test_in_progress_ranges_compare_same_elapsed_days(self):
        # This week on Monday: Monday vs last Monday only; on Thursday: Mon-Thu vs Mon-Thu.
        b = ranges.range_bounds("this_week", date(2026, 11, 16), self.cycle)
        self.assertEqual(b["prev"], (date(2026, 11, 9), date(2026, 11, 9)))
        self.assertEqual((b["compare_label"], b["compare_mode"]), ("较上周同期", "same_elapsed"))
        b = ranges.range_bounds("this_week", date(2026, 11, 19), self.cycle)
        self.assertEqual(b["prev"], (date(2026, 11, 9), date(2026, 11, 12)))
        # Cycle day 3 vs the first 3 days of the previous cycle.
        b = ranges.range_bounds("cycle", date(2026, 11, 11), self.cycle)
        self.assertEqual(b["prev"], (date(2026, 10, 9), date(2026, 10, 11)))
        self.assertEqual(b["compare_label"], "较上周期同期")
        # A shorter previous cycle (February) caps at its last day.
        cycle = compute_cycle_boundaries(1, date(2026, 3, 31))
        b = ranges.range_bounds("cycle", date(2026, 3, 31), cycle)
        self.assertEqual(b["prev"], (date(2026, 2, 1), date(2026, 2, 28)))
        # 7 / 30 days stay full-period comparisons.
        self.assertEqual(ranges.range_bounds("7d", date(2026, 11, 16), self.cycle)["compare_mode"], "full")

    def test_month_crossing(self):
        today = date(2026, 12, 2)  # Wednesday
        b = ranges.range_bounds("this_week", today, self.cycle)
        self.assertEqual((b["start"], b["end"]), (date(2026, 11, 30), date(2026, 12, 6)))
        b = ranges.range_bounds("30d", today, self.cycle)
        self.assertEqual((b["start"], b["end"]), (date(2026, 11, 3), date(2026, 12, 2)))
        self.assertEqual(b["prev"], (date(2026, 10, 4), date(2026, 11, 2)))
        b = ranges.range_bounds("7d", date(2027, 1, 3), self.cycle)
        self.assertEqual(b["start"], date(2026, 12, 28))

    def test_today_compares_with_yesterday_and_all_has_no_comparison(self):
        b = ranges.range_bounds("today", date(2026, 11, 1), self.cycle)
        self.assertEqual(b["prev"], (date(2026, 10, 31), date(2026, 10, 31)))
        self.assertEqual((b["compare_label"], b["compare_mode"]), ("昨天全天", "reference"))
        a = ranges.range_bounds("all", date(2026, 11, 1), self.cycle)
        self.assertIsNone(a["prev"])
        self.assertEqual(a["bucket"], "month")

    def test_cycle_uses_anchor_boundaries(self):
        cycle = compute_cycle_boundaries(9, date(2026, 11, 22))
        b = ranges.range_bounds("cycle", date(2026, 11, 22), cycle)
        self.assertEqual((b["start"], b["end"]), (date(2026, 11, 9), date(2026, 12, 8)))
        self.assertEqual(b["prev"], (date(2026, 10, 9), date(2026, 10, 22)))  # 14 elapsed days

    def test_dst_changes_use_local_dates(self):
        # 2026-11-01 04:30Z is 23:30 EST on Sunday Nov 1 (DST ended that morning).
        today = datetime(2026, 11, 2, 4, 30, tzinfo=timezone.utc).astimezone(TORONTO).date()
        self.assertEqual(today, date(2026, 11, 1))
        b = ranges.range_bounds("this_week", today, self.cycle)
        self.assertEqual((b["start"], b["end"]), (date(2026, 10, 26), date(2026, 11, 1)))
        # 2026-03-09 03:30Z is 23:30 EDT on Sunday Mar 8 (DST started that morning).
        today = datetime(2026, 3, 9, 3, 30, tzinfo=timezone.utc).astimezone(TORONTO).date()
        self.assertEqual(today, date(2026, 3, 8))
        b = ranges.range_bounds("this_week", today, self.cycle)
        self.assertEqual(b["start"], date(2026, 3, 2))
        b = ranges.range_bounds("7d", today, self.cycle)
        self.assertEqual(b["start"], date(2026, 3, 2))

    def test_since_reset_needs_a_reset_day(self):
        self.assertIsNone(ranges.range_bounds("since_reset", date(2026, 11, 22), self.cycle, None))
        b = ranges.range_bounds("since_reset", date(2026, 11, 22), self.cycle, date(2026, 11, 18))
        self.assertEqual((b["start"], b["end"]), (date(2026, 11, 18), date(2026, 11, 22)))
        # Same 5 days at the start of the previous quota week.
        self.assertEqual(b["prev"], (date(2026, 11, 11), date(2026, 11, 15)))
        self.assertEqual(b["compare_label"], "较上次重置同期")

    def test_parse_range_key(self):
        self.assertEqual(ranges.parse_range_key("last_week"), "last_week")
        self.assertEqual(ranges.parse_range_key(None), "this_week")
        self.assertEqual(ranges.parse_range_key("<script>"), "this_week")


class ResetDayTests(unittest.TestCase):
    def test_reset_day_is_local_day_of_last_reset(self):
        now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
        rs = ranges.last_reset_start(datetime(2026, 11, 25, 6, 24, tzinfo=timezone.utc), 168, now)
        self.assertEqual(rs, datetime(2026, 11, 18, 6, 24, tzinfo=timezone.utc))
        self.assertEqual(rs.astimezone(TORONTO).date(), date(2026, 11, 18))
        # 03:00Z is the previous evening in Toronto: the whole local start day counts.
        rs = ranges.last_reset_start(datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc), 168, now)
        self.assertEqual(rs.astimezone(TORONTO).date(), date(2026, 11, 17))

    def test_stale_reset_rolls_forward(self):
        now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
        rs = ranges.last_reset_start(datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc), 168, now)
        self.assertEqual(rs, datetime(2026, 11, 17, 3, 0, tzinfo=timezone.utc))
        self.assertIsNone(ranges.last_reset_start(None, 168, now))

    def test_since_reset_range_includes_whole_start_day(self):
        today = date(2026, 11, 22)
        now = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)
        pool = {"reset_start": datetime(2026, 11, 18, 3, 0, tzinfo=timezone.utc),  # Nov 17 22:00 local
                "window_hours": 168, "weekly_pct": 40.0}
        s = _summary([_day("2026-11-16", 1000), _day("2026-11-17", 2000), _day("2026-11-22", 4000)])
        r = _build([_member(1, "A", s)], today, pool=pool, now=now)["ranges"]["since_reset"]
        self.assertEqual(r["start"], "2026-11-17")
        self.assertEqual(r["total"]["tokens"]["total"], 6000)
        self.assertIn("按天近似", r["note"])
        keys = [i["key"] for i in r["insights"]]
        self.assertIn("projection", keys)


class AggregationTests(unittest.TestCase):
    today = date(2026, 11, 22)

    def test_multi_device_sum_and_device_split(self):
        def report(dev, days):
            return {"device_id": dev, "received_at": "2026-11-22T10:00:00Z",
                    "payload": {"device": {"id": dev, "name": dev}, "summary": _summary(days)}}
        mac = [_day("2026-11-20", 60000, 3.0), _day("2026-11-21", 1000, 0.1)]
        linux = [_day("2026-11-20", 40000, 2.0)]
        merged = merge_member_reports([report("1111222233334444", mac), report("aaaa5555bbbb6666", linux)])
        dev_summaries = [merge_member_reports([report("1111222233334444", mac)])["summary"],
                         merge_member_reports([report("aaaa5555bbbb6666", linux)])["summary"]]
        r = _build([_member(1, "A", merged["summary"], dev_summaries)], self.today)["ranges"]["this_week"]
        row = r["members"][0]
        self.assertEqual(row["tokens"], 101000)
        self.assertAlmostEqual(row["cost"], 5.1)
        self.assertEqual([d["tokens"] for d in row["devices"]], [61000, 40000])
        self.assertEqual(r["chart"]["totals"][4], 100000)  # Fri 11-20
        self.assertEqual(len(r["chart"]["buckets"]), 7)

    def test_member_without_data(self):
        s = _summary([_day("2026-11-20", 5000)])
        out = _build([_member(1, "A", s), _member(2, "Never", None)], self.today)["ranges"]
        for key in ranges.RANGE_ORDER:
            r = out[key]
            if r is None:
                continue
            with self.subTest(key=key):
                self.assertEqual(r["member_count"], 2)
                never = [m for m in r["members"] if m["id"] == 2][0]
                self.assertEqual(never["tokens"], 0)
                self.assertEqual(never["models"], [])
                self.assertEqual(never["devices"], [])
                self.assertEqual(r["members"][-1]["id"], 2)
        self.assertEqual(out["this_week"]["active_members"], 1)
        self.assertIsNone(out["since_reset"])  # no pool reset known

    def test_other_models_reconcile_with_total(self):
        days = [
            _day("2026-11-20", 10000, 2.0, models=[("m1", 6000, 1.0), ("m2", 1000, 0.2)]),
            _day("2026-11-21", 5000, 1.0, models=[("m1", 4000, 0.9)]),
        ]
        s2 = _summary([_day("2026-11-21", 3000, 0.5, models=[("m3", 2000, 0.3)])])
        r = _build([_member(1, "A", _summary(days)), _member(2, "B", s2)], self.today)["ranges"]["this_week"]
        self.assertEqual(r["total"]["tokens"]["total"], 18000)
        self.assertEqual(sum(m["tokens"] for m in r["models"]), 18000)
        other = r["models"][-1]
        self.assertTrue(other["other"])
        self.assertEqual(other["model"], "其他")
        self.assertEqual(other["tokens"], 18000 - 13000)
        self.assertAlmostEqual(sum(m["share"] for m in r["models"]), 100.0)
        m1 = [m for m in r["models"] if m["model"] == "m1"][0]
        self.assertEqual((m1["tokens"], m1["users"]), (10000, 1))
        a = [m for m in r["members"] if m["id"] == 1][0]
        self.assertEqual(sum(m["tokens"] for m in a["models"]), 15000)
        # Trend by model also reconciles per bucket.
        model_series = r["chart"]["model"]
        for i, total in enumerate(r["chart"]["totals"]):
            self.assertEqual(sum(s["values"][i] for s in model_series), total)

    def test_comparison_present_and_omitted(self):
        days = [_day("2026-11-10", 1000), _day("2026-11-17", 3000)]
        out = _build([_member(1, "A", _summary(days))], self.today)["ranges"]
        tw = out["this_week"]  # Sunday: the full 7 days on both sides
        self.assertEqual(tw["total"]["prev_tokens"], 1000)
        self.assertAlmostEqual(tw["total"]["change_pct"], 200.0)
        self.assertEqual(tw["compare_label"], "较上周同期")
        self.assertEqual(tw["members"][0]["prev_tokens"], 1000)
        self.assertIsNone(out["all"]["compare_label"])
        self.assertIsNone(out["all"]["total"]["prev_tokens"])

        # Previous period reaches past the 62-day daily window: no comparison at all.
        now = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)
        pool = {"reset_start": now - timedelta(days=40), "window_hours": 24 * 45, "weekly_pct": None}
        sr = _build([_member(1, "A", _summary(days))], self.today, pool=pool, now=now)["ranges"]["since_reset"]
        self.assertIsNone(sr["compare_label"])
        self.assertIsNone(sr["total"]["prev_tokens"])
        self.assertIsNone(sr["members"][0]["prev_tokens"])
        self.assertIsNone(sr["members"][0]["change_pct"])

        # Previous period starts before tracking_start: also omitted.
        out = _build([_member(1, "A", _summary(days))], self.today, tracking_start=date(2026, 11, 12))["ranges"]
        self.assertIsNone(out["this_week"]["compare_label"])
        self.assertEqual(out["this_week"]["total"]["tokens"]["total"], 3000)

    def test_monday_compares_with_last_monday_only(self):
        monday = date(2026, 11, 23)
        days = [_day("2026-11-16", 1000), _day("2026-11-17", 50000), _day("2026-11-23", 1500)]
        out = _build([_member(1, "A", _summary(days))], monday)["ranges"]
        tw = out["this_week"]
        self.assertEqual(tw["total"]["prev_tokens"], 1000)
        self.assertAlmostEqual(tw["total"]["change_pct"], 50.0)
        self.assertAlmostEqual(tw["members"][0]["change_pct"], 50.0)
        self.assertEqual(tw["elapsed_days"], 1)
        self.assertNotIn("peak", [i["key"] for i in tw["insights"]])
        # Last week is complete: compared with the whole week before.
        self.assertEqual(out["last_week"]["compare_mode"], "full")

    def test_today_shows_yesterday_as_reference_only(self):
        days = [_day("2026-11-21", 8000, 2.0), _day("2026-11-22", 2000, 0.5)]
        r = _build([_member(1, "A", _summary(days))], self.today)["ranges"]["today"]
        self.assertEqual(r["compare_mode"], "reference")
        self.assertEqual(r["compare_label"], "昨天全天")
        self.assertEqual(r["total"]["prev_tokens"], 8000)
        self.assertEqual(r["total"]["prev_cost"], 2.0)
        self.assertIsNone(r["total"]["change_pct"])
        self.assertIsNone(r["members"][0]["prev_tokens"])
        self.assertIsNone(r["members"][0]["change_pct"])

    def test_all_range_uses_all_time_and_monthly_trend(self):
        months = [
            {"period": "2026-10", "tokens": {"total": 7000}, "cost_usd": 1.0, "top_models": []},
            {"period": "2026-11", "tokens": {"total": 3000}, "cost_usd": 0.5, "top_models": []},
        ]
        all_time = {"period": "all", "first_day": "2026-10-05", "tokens": {"input": 10000, "total": 10000},
                    "cost_usd": 1.5, "top_models": [{"model": "m1", "tokens_total": 9000, "cost_usd": 1.2}]}
        s = _summary([_day("2026-11-17", 3000)], months=months, all_time=all_time)
        r = _build([_member(1, "A", s)], self.today)["ranges"]["all"]
        self.assertEqual(r["bucket"], "month")
        self.assertEqual(r["chart"]["buckets"], ["2026-10", "2026-11"])
        self.assertEqual(r["chart"]["totals"], [7000, 3000])
        self.assertEqual(r["total"]["tokens"]["total"], 10000)
        self.assertEqual([m["tokens"] for m in r["models"]], [9000, 1000])
        self.assertEqual(r["elapsed_days"], (self.today - date(2026, 10, 5)).days + 1)

    def test_all_range_honours_tracking_start(self):
        months = [{"period": "2026-10", "tokens": {"total": 7000}, "cost_usd": 1.0},
                  {"period": "2026-11", "tokens": {"total": 9000}, "cost_usd": 1.0}]
        days = [_day("2026-11-02", 4000), _day("2026-11-10", 5000)]
        s = _summary(days, months=months, all_time={"tokens": {"total": 16000}})
        r = _build([_member(1, "A", s)], self.today, tracking_start=date(2026, 11, 9))["ranges"]["all"]
        self.assertEqual(r["total"]["tokens"]["total"], 5000)
        self.assertEqual(r["chart"]["buckets"], ["2026-11"])
        self.assertIn("2026-11-09", r["note"])

    def test_insights_only_when_computable(self):
        s = _summary([_day("2026-11-20", 10000, 2.0, out=1000, cache_read=6000)])
        r = _build([_member(1, "A", s)], self.today)["ranges"]["this_week"]
        by_key = {i["key"]: i for i in r["insights"]}
        self.assertEqual(by_key["cache"]["value"], "66.7%")  # 6000 / (3000 + 6000)
        self.assertEqual(by_key["output"]["value"], "10.0%")
        self.assertEqual(by_key["peak"]["value"], "2026-11-20")
        self.assertEqual(by_key["top_member"]["value"], "A")
        self.assertNotIn("projection", by_key)  # no pool data
        empty = _build([_member(1, "A", _summary([]))], self.today)["ranges"]["today"]
        self.assertEqual(empty["insights"], [])
        self.assertIsNone(empty["peak"])

    def test_heatmap_covers_62_days(self):
        s = _summary([_day("2026-11-22", 500), _day("2026-09-22", 100), _day("2026-09-21", 999)])
        hm = _build([_member(1, "A", s)], self.today)["heatmap"]
        self.assertEqual(len(hm["days"]), 62)
        self.assertEqual(hm["days"][0], {"date": "2026-09-22", "tokens": 100, "cost": 1.0})
        self.assertEqual(hm["days"][-1]["tokens"], 500)
        self.assertEqual(hm["max"], 500)


if __name__ == "__main__":
    unittest.main()
