using Xunit;

namespace Kanjo.Core.Tests;

public sealed class SubscriptionTests : KanjoTestCase
{
    private static readonly TimeZoneInfo Shanghai = TimeZoneInfo.FindSystemTimeZoneById(
        OperatingSystem.IsWindows() ? "China Standard Time" : "Asia/Shanghai");

    private static Subscription Sub(
        string start = "2026-10-24T16:00:00Z", string end = "2026-11-24T16:00:00Z",
        string cycleSource = "subscription_date", string source = "detected") =>
        new("max_5x", "Claude Max 5x", 100, start, end, 25, cycleSource, false, source, null);

    [Fact]
    public void TestCycleCaptionInReportTimezone()
    {
        var now = Ts("2026-10-25T10:00:00Z");
        Assert.Equal("Oct 25 – Nov 25 · renews in 31 days", Fmt.CycleCaption(Sub(), Shanghai, now));
        Assert.Equal("Last 30 days · set renewal day for exact cycle",
            Fmt.CycleCaption(Sub(cycleSource: "rolling_30d"), Shanghai, now));
        Assert.Equal("Oct 25 – Nov 25 · renews in 31 days", Fmt.CycleCaption(Sub(cycleSource: "unknown"), Shanghai, now));
        Assert.Equal("Claude Max 5x · last 30 days (day not set)",
            Fmt.CycleRangeCaption(Sub(cycleSource: "rolling_30d"), Shanghai));
        Assert.Equal("Claude Max 5x since Oct 25", Fmt.CycleRangeCaption(Sub(), Shanghai));
        Assert.Equal("Oct 24 – Nov 24", Fmt.CycleDates(Sub(), TimeZoneInfo.Utc));
        Assert.Equal("Renewal day unknown; set it in Settings", SubscriptionValue.AssumedDayHelp);
    }

    [Fact]
    public void TestQuotaRows()
    {
        var utc = TimeZoneInfo.Utc;
        var now = Ts("2026-10-24T12:00:00Z");
        var codex = new QuotaWindow("2026-10-31T04:53:24Z", 168, 24.4,
            "2026-10-24T17:05:49Z", 5, 108, "tokei", null);
        var rows = SubscriptionValue.QuotaRows(codex, utc, now, "en");
        Assert.Equal(["5-hour", "Weekly"], rows.Select(r => r.Title).ToArray());
        Assert.Equal([100d, 24.4d], rows.Select(r => r.Percent).ToArray());
        Assert.Equal("Resets in 5h 6m · 5:05 PM", rows[0].Detail);
        Assert.Equal("Resets in 6d 16h · Sat 4:53 AM", rows[1].Detail);

        // 5 小时窗口已结束 → 「—」+ Window ended；没有 5 小时窗口（Grok）→ 只有周一行
        var ended = new QuotaWindow("2026-10-27T05:00:00Z", 168, 40, null, 5, null, "tokei", null);
        var e = SubscriptionValue.QuotaRows(ended, utc, now, "en");
        Assert.Null(e[0].Percent);
        Assert.Equal("Window ended", e[0].Detail);

        var grok = new QuotaWindow("2026-10-27T05:00:00Z", 168, 42, null, null, null, "tokei", null);
        Assert.Equal(["weekly"], SubscriptionValue.QuotaRows(grok, utc, now).Select(r => r.Id).ToArray());

        // 周重置已过（导出旧了）→ 也是已结束
        var stale = new QuotaWindow("2026-10-24T11:00:00Z", 168, 90, null, null, null, "tokei", null);
        Assert.Null(SubscriptionValue.QuotaRows(stale, utc, now)[0].Percent);
        Assert.Empty(SubscriptionValue.QuotaRows(null, utc));

        // Extra windows (e.g. Antigravity 3p Claude/GPT group)
        var extra = new[]
        {
            new ExtraQuotaWindow("antigravity-3p-weekly", "Claude/GPT 周", 10.0, "2026-10-31T04:53:24Z", 168),
            new ExtraQuotaWindow("antigravity-3p-5h", "Claude/GPT 5h", 50.0, "2026-10-24T11:00:00Z", 5),
        };
        var agy = new QuotaWindow("2026-10-31T04:53:24Z", 168, 80.1, "2026-10-24T17:05:49Z", 5, 25.0, "tokei", extra);
        var agyRows = SubscriptionValue.QuotaRows(agy, utc, now, "en");
        Assert.Equal(["five_hour", "weekly", "antigravity-3p-weekly", "antigravity-3p-5h"],
            agyRows.Select(r => r.Id).ToArray());
        Assert.Equal(["5-hour", "Weekly", "Claude/GPT 周", "Claude/GPT 5h"], agyRows.Select(r => r.Title).ToArray());
        Assert.Equal([25.0, 80.1, 10.0, null], agyRows.Select(r => r.Percent).ToArray());
        Assert.Contains("Resets in", agyRows[2].Detail);
        Assert.Equal("Window ended", agyRows[3].Detail);
    }

    [Fact]
    public void TestExtraWindowsDecoding()
    {
        // Backward compatibility: decoding without extra_windows
        const string without = """{"weekly_resets_at":"2026-10-31T04:53:24Z","weekly_window_hours":168,"source":"tokei"}""";
        using (var doc = System.Text.Json.JsonDocument.Parse(without))
        {
            Assert.Null(QuotaWindow.Decode(doc.RootElement, "").ExtraWindows);
        }

        const string with = """
        {
            "weekly_resets_at": "2026-10-31T04:53:24Z",
            "weekly_window_hours": 168,
            "source": "tokei",
            "extra_windows": [
                { "id": "antigravity-3p-weekly", "title": "Claude/GPT 周", "used_percent": 12.5,
                  "resets_at": "2026-10-31T04:53:24Z", "window_hours": 168 }
            ]
        }
        """;
        using (var doc = System.Text.Json.JsonDocument.Parse(with))
        {
            var decoded = QuotaWindow.Decode(doc.RootElement, "");
            Assert.Single(decoded.ExtraWindows!);
            Assert.Equal("antigravity-3p-weekly", decoded.ExtraWindows![0].Id);
            Assert.Equal("Claude/GPT 周", decoded.ExtraWindows[0].Title);
            Assert.Equal(12.5, decoded.ExtraWindows[0].UsedPercent);
        }

        const string live = """{"weekly_resets_at":"2026-10-31T04:53:24Z","weekly_window_hours":168,"source":"live"}""";
        using (var doc = System.Text.Json.JsonDocument.Parse(live))
        {
            Assert.Equal("live", QuotaWindow.Decode(doc.RootElement, "").Source);
        }
    }

    [Fact]
    public void TestRelativeResetAndLevels()
    {
        var now = Ts("2026-10-24T12:00:00Z");
        Assert.Equal("1 min", SubscriptionValue.Relative(now, now.AddSeconds(10)));
        Assert.Equal("59 min", SubscriptionValue.Relative(now, now.AddSeconds(59 * 60)));
        Assert.Equal("1h 0m", SubscriptionValue.Relative(now, now.AddSeconds(3600)));
        Assert.Equal("1d 2h", SubscriptionValue.Relative(now, now.AddSeconds(86400 + 2 * 3600)));

        Assert.Equal(QuotaLevel.Normal, SubscriptionValue.Level(null));
        Assert.Equal(QuotaLevel.Normal, SubscriptionValue.Level(79.9));
        Assert.Equal(QuotaLevel.Warning, SubscriptionValue.Level(80));
        Assert.Equal(QuotaLevel.Warning, SubscriptionValue.Level(94.9));
        Assert.Equal(QuotaLevel.Critical, SubscriptionValue.Level(95));
    }

    [Fact]
    public void TestResetTextZhHans()
    {
        var now = Ts("2026-10-24T12:00:00Z");
        var reset = Ts("2026-10-27T02:00:00Z");
        Assert.Equal("2 天 14 小时后重置 · 周二 10:00",
            SubscriptionValue.ResetText(reset, Shanghai, now, "zh-Hans"));
    }

    [Fact]
    public void TestRenewalTodayTomorrowAndExpired()
    {
        const string end = "2026-11-24T16:00:00Z";
        Assert.Equal("renews tomorrow", Fmt.Renewal(end, Shanghai, Ts("2026-11-24T15:59:00Z")));
        Assert.Equal("renews today", Fmt.Renewal(end, Shanghai, Ts("2026-11-25T10:00:00Z")));
        Assert.Equal("renewal date passed", Fmt.Renewal(end, Shanghai, Ts("2026-11-25T16:00:00Z")));
        Assert.Equal("Renewal date unavailable", Fmt.Renewal("invalid", Shanghai));
        Assert.Equal("Cycle dates unavailable", Fmt.CycleDates(Sub(start: "invalid"), Shanghai));
    }

    [Fact]
    public void TestRenewalAcrossDstAndYearBoundary()
    {
        var ny = TimeZoneInfo.FindSystemTimeZoneById(
            OperatingSystem.IsWindows() ? "Eastern Standard Time" : "America/New_York");
        // 跨春季夏令时只有 47 小时，但仍是两个自然日。
        Assert.Equal("renews in 2 days", Fmt.Renewal("2026-03-09T04:00:00Z", ny, Ts("2026-03-07T05:00:00Z")));
        var sub = Sub(start: "2026-12-25T05:00:00Z", end: "2027-01-25T05:00:00Z");
        Assert.Equal("Dec 25 – Jan 25 · renews in 31 days",
            Fmt.CycleCaption(sub, ny, Ts("2026-12-25T23:00:00Z")));
    }

    [Fact]
    public void TestAnchorSource()
    {
        Assert.Equal("detected", SubscriptionValue.AnchorSource(Sub()));
        Assert.Equal("manual", SubscriptionValue.AnchorSource(Sub(cycleSource: "manual")));
        Assert.Equal("not set · using last 30 days",
            SubscriptionValue.AnchorSource(Sub(cycleSource: "rolling_30d", source: "manual")));
        Assert.Equal("manual", SubscriptionValue.AnchorSource(Sub(cycleSource: "unknown", source: "manual")));
    }

    [Fact]
    public void TestBillingPages()
    {
        Assert.Equal("https://claude.ai/settings/billing", SubscriptionValue.BillingPage("claude"));
        Assert.Equal("https://chatgpt.com/settings/billing", SubscriptionValue.BillingPage("codex"));
        Assert.Equal("https://one.google.com/subscriptions", SubscriptionValue.BillingPage("antigravity"));
        Assert.Equal("https://github.com/settings/copilot", SubscriptionValue.BillingPage("copilot"));
        Assert.Equal("https://x.com/settings/premium", SubscriptionValue.BillingPage("grok"));
        Assert.Equal("https://platform.minimax.io", SubscriptionValue.BillingPage("minimax"));
        Assert.Equal("https://dashscope.console.aliyun.com", SubscriptionValue.BillingPage("qwen"));
        Assert.Equal("https://commandcode.ai", SubscriptionValue.BillingPage("commandcode"));
        Assert.Equal("https://opencode.ai", SubscriptionValue.BillingPage("opencode"));
        Assert.Null(SubscriptionValue.BillingPage("future-agent"));
    }

    [Fact]
    public void TestRowsForArbitraryAgentKeys()
    {
        var r = LoadFixture();
        var customSubs = new Dictionary<string, Subscription>(StringComparer.Ordinal)
        {
            ["grok"] = new("supergrok", "SuperGrok", 30, "2026-09-24T16:00:00Z", "2026-10-24T16:00:00Z", null,
                "rolling_30d", false, "detected", null),
            ["copilot"] = new("pro", "Copilot Pro", 10, "2026-09-24T16:00:00Z", "2026-10-24T16:00:00Z", 15,
                "manual", false, "manual", null),
            ["minimax"] = new("starter", "MiniMax Coding Plan Starter", 10, "2026-09-24T16:00:00Z",
                "2026-10-24T16:00:00Z", null, "rolling_30d", false, "manual", null),
            ["qwen"] = new("coding_plan", "Qwen Coding Plan Pro", 50, "2026-09-24T16:00:00Z", "2026-10-24T16:00:00Z",
                null, "rolling_30d", false, "manual", null),
            ["custom_bot"] = new("special", "Custom Bot", 15, "2026-09-24T16:00:00Z", "2026-10-24T16:00:00Z", 1,
                "manual", false, "manual", null),
        };
        r = r with { Subscriptions = customSubs };
        var rows = SubscriptionValue.Rows(r);
        Assert.Equal(customSubs.Keys.ToHashSet(), rows.Select(x => x.Agent).ToHashSet());
        Assert.Equal(5, rows.Count);
        foreach (var row in rows)
        {
            var expected = customSubs[row.Agent];
            Assert.Equal(expected.PlanLabel, row.PlanLabel);
            Assert.Equal(expected.MonthlyPriceUsd, row.MonthlyPriceUsd);
        }
        Assert.DoesNotContain(rows, x => x.Agent == "unsubscribed_agent");
    }

    [Fact]
    public void TestNudgeDismissalAndNewRollingAgent()
    {
        var rolling = Sub(cycleSource: "rolling_30d");
        var subs = new Dictionary<string, Subscription>(StringComparer.Ordinal)
        {
            ["codex"] = rolling,
            ["claude"] = Sub(),
            ["future-agent"] = rolling,
        };
        Assert.Equal(["codex", "future-agent"],
            RenewalNudge.PendingAgents(subs, new HashSet<string>(StringComparer.Ordinal)));
        var dismissed = RenewalNudge.ParseDismissed(" codex, ,codex,old-agent ");
        Assert.Equal(new HashSet<string> { "codex", "old-agent" }, dismissed);
        Assert.Equal(["future-agent"], RenewalNudge.PendingAgents(subs, dismissed));

        var allDismissed = new HashSet<string>(dismissed, StringComparer.Ordinal) { "future-agent" };
        Assert.Empty(RenewalNudge.PendingAgents(subs, allDismissed));
        Assert.Equal(allDismissed, RenewalNudge.ParseDismissed(RenewalNudge.SerializeDismissed(allDismissed)));
        Assert.Empty(RenewalNudge.PendingAgents(new Dictionary<string, Subscription>(), new HashSet<string>()));
        Assert.Empty(RenewalNudge.PendingAgents(
            new Dictionary<string, Subscription> { ["codex"] = Sub() }, new HashSet<string>()));
        Assert.Empty(RenewalNudge.PendingAgents(
            new Dictionary<string, Subscription> { ["codex"] = Sub(cycleSource: "unknown") }, new HashSet<string>()));
    }

    [Fact]
    public void TestSubscriptionSettingsRoute()
    {
        Assert.Equal("codex", SubscriptionSettingsRoute.Agent("settings:subscriptions:codex"));
        Assert.Equal("settings:subscriptions:codex", SubscriptionSettingsRoute.Anchor("codex"));
        Assert.Equal("future-agent", SubscriptionSettingsRoute.Agent("settings:subscriptions:future-agent"));
        foreach (var raw in new[]
                 {
                     "settings", "settings-bottom", "settings:subscriptions:", "settings:subscriptions:codex:extra",
                     "settings:subscriptions:codex:edit", "overview:subscriptions:codex",
                 })
        {
            Assert.Null(SubscriptionSettingsRoute.Agent(raw));
        }
        Assert.Equal("codex", SubscriptionSettingsRoute.EditAgent("settings:subscriptions:codex:edit"));
        Assert.Equal("future-agent", SubscriptionSettingsRoute.EditAgent("settings:subscriptions:future-agent:edit"));
        Assert.Equal("minimax", SubscriptionSettingsRoute.Parse("settings:subscriptions:minimax:edit")?.Agent);
        Assert.True(SubscriptionSettingsRoute.Parse("settings:subscriptions:minimax:edit")?.IsEdit);
        Assert.Equal("minimax", SubscriptionSettingsRoute.Parse("settings:subscriptions:minimax")?.Agent);
        Assert.False(SubscriptionSettingsRoute.Parse("settings:subscriptions:minimax")?.IsEdit);
        foreach (var raw in new[]
                 {
                     "settings", "settings-bottom", "settings:subscriptions:codex", "settings:subscriptions:codex:extra",
                     "settings:subscriptions::edit", "settings:subscriptions:codex:edit:extra",
                 })
        {
            Assert.Null(SubscriptionSettingsRoute.EditAgent(raw));
        }
    }

    [Fact]
    public void TestMultiplierAndShare()
    {
        Assert.Equal(15.72, SubscriptionValue.Multiplier(1572, 100)!.Value, 9);
        Assert.Equal(0, SubscriptionValue.Multiplier(0, 20));
        Assert.Null(SubscriptionValue.Multiplier(10, null));
        Assert.Null(SubscriptionValue.Multiplier(10, 0));
        Assert.Null(SubscriptionValue.Multiplier(10, -5));

        Assert.Equal(0.38, SubscriptionValue.Share(38, 100)!.Value, 9);
        Assert.Equal(0, SubscriptionValue.Share(0, 10));
        Assert.Null(SubscriptionValue.Share(5, 0));
        Assert.Null(SubscriptionValue.Share(5, -1));
        Assert.Equal(
            "You pay the flat fee on the left. The number on the right is what the same work would cost on API billing.",
            SubscriptionValue.Explanation);
    }

    [Fact]
    public void TestFixtureCycleUsageMatchesFilterAndSkipsUnsubscribed()
    {
        var r = LoadFixture();
        Assert.Equal("rolling_30d", r.Subscriptions!["codex"].CycleSource);
        var now = ReportDates.ParseTimestamp(r.GeneratedAt)!.Value;
        var usage = SubscriptionValue.CycleUsageOf(r, now);
        var filtered = RangeEngine.Filtered(r, RangeEngine.Spec(TimeRange.BillingCycle, r, now),
            p => DominantAgent.Of(p.ByAgent)?.Agent ?? p.ByAgent.FirstOrDefault()?.Agent ?? "unknown");

        foreach (var agent in new[] { "claude", "codex", "grok", "antigravity", "copilot" })
        {
            var fromProjects = filtered.Projects.Sum(p => p.ByAgent.FirstOrDefault(a => a.Agent == agent)?.Cost ?? 0);
            var fromBuckets = filtered.Unattributed.SessionsDetail.Concat(filtered.Excluded.SessionsDetail)
                .Where(s => s.Agent == agent)
                .Sum(s => s.Cost);
            Assert.Equal(fromProjects + fromBuckets, usage.Total(agent), 2);
            Assert.True(usage.Total(agent) > 0, agent);
        }
        Assert.Equal(0, usage.Total("qwen"));

        var rows = SubscriptionValue.Rows(r, now);
        Assert.Equal(rows.OrderByDescending(x => x.Usage).Select(x => x.Agent).ToArray(),
            rows.Select(x => x.Agent).ToArray());
        Assert.Equal(new HashSet<string> { "claude", "codex", "grok", "antigravity", "copilot" },
            rows.Select(x => x.Agent).ToHashSet());
        foreach (var row in rows)
        {
            var price = r.Subscriptions![row.Agent].MonthlyPriceUsd;
            Assert.Equal(SubscriptionValue.Multiplier(row.Usage, price), row.Multiplier);
            Assert.False(row.ExtraUsageEnabled);
        }

        var top = r.Projects[0];
        var shares = SubscriptionValue.Shares(top.Id, r, now);
        Assert.NotEmpty(shares);
        Assert.DoesNotContain(shares, s => s.Agent == "qwen");
        foreach (var s in shares)
        {
            var total = usage.Total(s.Agent);
            Assert.True(total > 0);
            Assert.Equal(s.ProjectCost / total, s.Share, 9);
            Assert.Equal(usage.Cost(top.Id, s.Agent), s.ProjectCost, 9);
        }

        // 总量为 0 的 agent 不出现：把 claude 的账期推到未来
        var claude = r.Subscriptions["claude"];
        var futureSubs = new Dictionary<string, Subscription>(r.Subscriptions, StringComparer.Ordinal)
        {
            ["claude"] = claude with { CycleStart = "2099-01-01T00:00:00Z" },
        };
        var future = r with { Subscriptions = futureSubs };
        var skipped = SubscriptionValue.Shares(top.Id, future, now);
        Assert.DoesNotContain(skipped, s => s.Agent == "claude");
        Assert.Equal(0, SubscriptionValue.Rows(future, now).First(x => x.Agent == "claude").Usage);
    }
}
