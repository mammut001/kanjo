using Xunit;

namespace Kanjo.Core.Tests;

public sealed class TimeRangeTests : KanjoTestCase
{
    private static readonly TimeZoneInfo Shanghai = TimeZoneInfo.FindSystemTimeZoneById(
        OperatingSystem.IsWindows() ? "China Standard Time" : "Asia/Shanghai");

    private static DateTimeOffset Day(string s) =>
        Time.AtDay(Shanghai, ReportDates.ParseDay(s)!.Value);

    // 2026-10-24 是周六。now = 上海时间 Oct 24 15:00。
    private static readonly DateTimeOffset Now = Ts("2026-10-24T07:00:00Z");

    [Fact]
    public void TestMenuBarPrefix()
    {
        Assert.Equal(
            new string?[] { null, "today", "7d", "30d", null, null, null },
            TimeRanges.All.Select(r => r.MenuBarSuffix()).ToArray());
        Assert.Equal("Today", TimeRange.Today.ShortLabel());
        Assert.Equal("Today", TimeRange.Today.LongLabel());
        Assert.Equal("today", TimeRange.Today.MenuBarSuffix());
        Assert.Equal("Cycle", TimeRange.BillingCycle.ShortLabel());
        Assert.Equal("Billing cycle", TimeRange.BillingCycle.LongLabel());
        Assert.Null(TimeRange.BillingCycle.MenuBarSuffix());
    }

    private static RangeSpec Spec(
        TimeRange r,
        IReadOnlyDictionary<string, QuotaWindow>? quota = null,
        IReadOnlyDictionary<string, Subscription>? subscriptions = null,
        DateTimeOffset? now = null) =>
        RangeEngine.DateInterval(r, now ?? Now, Shanghai, quota, subscriptions);

    private static Subscription Sub(
        string plan = "max_5x", string label = "Claude Max 5x", double? price = 100,
        string start = "2026-09-24T16:00:00Z", int? anchor = 25, string cycleSource = "subscription_date") =>
        new(plan, label, price, start, "2026-11-25T00:00:00Z", anchor, cycleSource, false, "detected", null);

    // MARK: - 区间

    [Fact]
    public void TestAllIsUnbounded()
    {
        var s = Spec(TimeRange.All);
        Assert.True(s.IsAll);
        Assert.Null(s.Start);
        Assert.Null(s.End);
        Assert.True(s.Includes(DateTimeOffset.MinValue, "anything"));
    }

    [Fact]
    public void TestToday()
    {
        var s = Spec(TimeRange.Today);
        Assert.Equal(Day("2026-10-24"), s.Start);
        Assert.Equal(Now, s.End);

        // 边界日：Oct 24 算，Oct 23 不算。
        Assert.True(s.IncludesDay(Day("2026-10-24"), Day("2026-10-25"), "claude"));
        Assert.False(s.IncludesDay(Day("2026-10-23"), Day("2026-10-24"), "claude"));

        // 上海 Oct 24 00:00 = UTC Oct 23 16:00。
        Assert.True(s.Includes(Ts("2026-10-23T16:00:00Z"), "claude"));
        Assert.True(s.Includes(Ts("2026-10-24T06:59:59Z"), "claude"));
        // 排除昨天 23:59
        Assert.False(s.Includes(Ts("2026-10-23T15:59:00Z"), "claude"));
        Assert.False(s.Includes(Ts("2026-10-23T15:59:59Z"), "claude"));
        // 排除 end 及未来
        Assert.False(s.Includes(Now, "claude"));
    }

    [Fact]
    public void TestSevenAndThirtyDays()
    {
        var s7 = Spec(TimeRange.Days7);
        Assert.Equal(Day("2026-10-18"), s7.Start);
        Assert.Equal(Now, s7.End);
        var s30 = Spec(TimeRange.Days30);
        Assert.Equal(Day("2026-09-25"), s30.Start);

        Assert.True(s7.IncludesDay(Day("2026-10-18"), Day("2026-10-19"), "claude"));
        Assert.False(s7.IncludesDay(Day("2026-10-17"), Day("2026-10-18"), "claude"));
        Assert.True(s7.IncludesDay(Day("2026-10-24"), Day("2026-10-25"), "claude"));
        // 上海 Oct 18 00:00 = UTC Oct 17 16:00。
        Assert.True(s7.Includes(Ts("2026-10-17T16:00:00Z"), "x"));
        Assert.False(s7.Includes(Ts("2026-10-17T15:59:59Z"), "x"));
    }

    [Fact]
    public void TestLastWeekIsPreviousMondayToSunday()
    {
        var s = Spec(TimeRange.LastWeek);
        Assert.Equal(Day("2026-10-12"), s.Start);
        Assert.Equal(Day("2026-10-19"), s.End);
        Assert.True(s.IncludesDay(Day("2026-10-18"), Day("2026-10-19"), "c"));  // 周日
        Assert.False(s.IncludesDay(Day("2026-10-19"), Day("2026-10-20"), "c")); // 本周一
        Assert.False(s.IncludesDay(Day("2026-10-11"), Day("2026-10-12"), "c"));
    }

    [Fact]
    public void TestMondayAlgorithmOnEveryWeekday()
    {
        // Oct 19 (Mon) … Oct 25 (Sun) 都属于同一周，上周是 Oct 12–18。
        for (var d = 19; d <= 25; d++)
        {
            var n = Ts($"2026-10-{d:00}T04:00:00Z");
            Assert.Equal(Day("2026-10-12"), Spec(TimeRange.LastWeek, now: n).Start);
            var local = Time.LocalDate(Shanghai, n);
            Assert.Equal(new DateOnly(2026, 10, 19), Time.MondayOnOrBefore(Shanghai, local));
        }
        // 周一凌晨（上海 00:30）：本周就是这周，上周是前一周。
        Assert.Equal(Day("2026-10-19"), Spec(TimeRange.LastWeek, now: Ts("2026-10-25T16:30:00Z")).Start);
        // 时区决定是哪一天：UTC 周日 20:00 在上海已是周一。
        var utcSpec = RangeEngine.DateInterval(TimeRange.LastWeek, Ts("2026-10-25T20:00:00Z"), TimeZoneInfo.Utc, null);
        Assert.Equal(Ts("2026-10-12T00:00:00Z"), utcSpec.Start);
        Assert.Equal(Day("2026-10-19"), Spec(TimeRange.LastWeek, now: Ts("2026-10-25T20:00:00Z")).Start);
    }

    [Fact]
    public void TestSinceResetPerAgentStarts()
    {
        var quota = new Dictionary<string, QuotaWindow>
        {
            ["claude"] = new("2026-10-27T10:00:00Z", 168, null, null, null, null, "tokei", null),
            ["codex"] = new("2026-10-28T08:00:00Z", 168, null, null, null, null, "manual", null),
            ["grok"] = new("2026-10-27T05:00:00Z", 168, null, null, null, null, "tokei", null),
        };
        var s = Spec(TimeRange.SinceReset, quota);
        Assert.Equal(Ts("2026-10-20T10:00:00Z"), s.AgentStarts["claude"]);
        Assert.Equal(Ts("2026-10-21T08:00:00Z"), s.AgentStarts["codex"]);
        Assert.Equal(Ts("2026-10-20T05:00:00Z"), s.AgentStarts["grok"]);
        Assert.Null(s.Window("antigravity"));
        Assert.False(s.Includes(Now, "antigravity"));
        Assert.True(s.Includes(Ts("2026-10-20T10:00:00Z"), "claude"));
        Assert.False(s.Includes(Ts("2026-10-20T10:00:00Z"), "codex"));
        // Oct 20（上海）与 claude 的窗口相交，与 codex 的不相交。
        Assert.True(s.IncludesDay(Day("2026-10-20"), Day("2026-10-21"), "claude"));
        Assert.False(s.IncludesDay(Day("2026-10-20"), Day("2026-10-21"), "codex"));
    }

    [Fact]
    public void TestWindowStartRollsBackAndForward()
    {
        // 下次重置在一个多窗口之后（起点仍在未来）→ 再往前推一个窗口。
        var far = new QuotaWindow("2026-11-02T07:00:00Z", 168, null, null, null, null, "tokei", null);
        Assert.Equal(Ts("2026-10-19T07:00:00Z"), RangeEngine.WindowStart(far, Now));
        // 缓存过期：重置时间已过去 → 当前窗口从那次重置开始。
        var stale = new QuotaWindow("2026-10-22T07:00:00Z", 168, null, null, null, null, "tokei", null);
        Assert.Equal(Ts("2026-10-22T07:00:00Z"), RangeEngine.WindowStart(stale, Now));
        var fiveHour = new QuotaWindow("2026-10-24T09:00:00Z", 5, null, null, null, null, "tokei", null);
        Assert.Equal(Ts("2026-10-24T04:00:00Z"), RangeEngine.WindowStart(fiveHour, Now));
        var grokDay = new QuotaWindow("2026-10-25T05:00:00Z", 24, null, null, null, null, "tokei", null);
        Assert.Equal(Ts("2026-10-24T05:00:00Z"), RangeEngine.WindowStart(grokDay, Now));
        Assert.Null(RangeEngine.WindowStart(new QuotaWindow("garbage", 168, null, null, null, null, "tokei", null), Now));
        Assert.Null(RangeEngine.WindowStart(new QuotaWindow("2026-10-27T10:00:00Z", 0, null, null, null, null, "tokei", null), Now));
    }

    [Fact]
    public void TestWindowStartAcrossDst()
    {
        var ny = TimeZoneInfo.FindSystemTimeZoneById(
            OperatingSystem.IsWindows() ? "Eastern Standard Time" : "America/New_York");

        // 1. Spring forward: 2026-03-08 02:00 NY turns UTC-5 into UTC-4.
        // Stale reset is Sunday 10:00 AM EST (15:00:00Z). 1 calendar week later is Sunday 10:00 AM EDT (14:00:00Z).
        var staleSpring = new QuotaWindow("2026-03-01T15:00:00Z", 168, null, null, null, null, "tokei", null);
        var nowSpring = Ts("2026-03-10T15:00:00Z");
        Assert.Equal(Ts("2026-03-08T14:00:00Z"), RangeEngine.WindowStart(staleSpring, nowSpring, ny));

        var specSpring = RangeEngine.DateInterval(TimeRange.SinceReset, nowSpring, ny,
            new Dictionary<string, QuotaWindow> { ["claude"] = staleSpring });
        Assert.Equal(Ts("2026-03-08T14:00:00Z"), specSpring.AgentStarts["claude"]);

        // 2. Fall back: 2026-11-01 02:00 NY turns UTC-4 into UTC-5.
        // Stale reset is Sunday 10:00 AM EDT (14:00:00Z). 1 calendar week later is Sunday 10:00 AM EST (15:00:00Z).
        var staleFall = new QuotaWindow("2026-10-25T14:00:00Z", 168, null, null, null, null, "tokei", null);
        var nowFall = Ts("2026-11-04T15:00:00Z");
        Assert.Equal(Ts("2026-11-01T15:00:00Z"), RangeEngine.WindowStart(staleFall, nowFall, ny));

        // 3. Non-168h window keeps fixed steps
        var dayWindow = new QuotaWindow("2026-03-08T06:00:00Z", 24, null, null, null, null, "tokei", null);
        Assert.Equal(Ts("2026-03-09T06:00:00Z"), RangeEngine.WindowStart(dayWindow, Ts("2026-03-09T08:00:00Z"), ny));
    }

    [Fact]
    public void TestBillingCyclePerAgentStarts()
    {
        var subs = new Dictionary<string, Subscription>
        {
            ["claude"] = Sub(start: "2026-09-24T16:00:00Z"),
            ["codex"] = Sub("plus", "ChatGPT Plus", 20, "2026-09-30T16:00:00Z", null, "rolling_30d"),
        };
        var s = Spec(TimeRange.BillingCycle, null, subs);
        Assert.Equal(Ts("2026-09-24T16:00:00Z"), s.AgentStarts["claude"]);
        Assert.Equal(Ts("2026-09-30T16:00:00Z"), s.AgentStarts["codex"]);
        Assert.Null(s.Window("antigravity"));
        Assert.False(s.Includes(Now, "antigravity"));
        // 上海 9 月 25 日零点起算 claude；前一天整天不相交。
        Assert.False(s.IncludesDay(Day("2026-09-24"), Day("2026-09-25"), "claude"));
        Assert.True(s.IncludesDay(Day("2026-09-25"), Day("2026-09-26"), "claude"));
        // codex 从上海 10 月 1 日零点起；9 月 30 日整天不相交。
        Assert.False(s.IncludesDay(Day("2026-09-30"), Day("2026-10-01"), "codex"));
        Assert.True(s.IncludesDay(Day("2026-10-01"), Day("2026-10-02"), "codex"));
        Assert.True(s.Includes(Ts("2026-09-24T16:00:00Z"), "claude"));
        Assert.False(s.Includes(Ts("2026-09-24T16:00:00Z"), "codex"));
    }

    [Fact]
    public void TestBillingCycleUsesEachAgentsOwnStart()
    {
        var subs = new Dictionary<string, Subscription>
        {
            ["claude"] = Sub(start: "2026-10-17T16:00:00Z"),   // 上海 10 月 18 日
            ["codex"] = Sub("plus", "ChatGPT Plus", 20, "2026-10-21T16:00:00Z", null, "rolling_30d"),
        };
        var f = RangeEngine.Filter(Project(), Spec(TimeRange.BillingCycle, null, subs), "claude");
        // claude：Oct 18（2）+ Oct 20（4）；codex：只有 Oct 22（6）；antigravity 无订阅，不计入。
        Assert.Equal(12, f.Cost, 9);
        Assert.Equal(1200, f.Tokens);
        Assert.Equal(["claude", "codex"], f.ByAgent.Select(a => a.Agent).OrderBy(a => a, StringComparer.Ordinal).ToArray());
        Assert.Equal(["2026-10-18", "2026-10-20", "2026-10-22"], f.ByDay.Select(d => d.Day).ToArray());
        Assert.Equal(4, f.ByDay.First(d => d.Day == "2026-10-20").ByAgent!["claude"]);
        Assert.Equal(3, f.Sessions);
        Assert.Equal(2, f.ByAgent.First(a => a.Agent == "claude").Sessions);
        Assert.Equal(1, f.ByAgent.First(a => a.Agent == "codex").Sessions);
    }

    [Fact]
    public void TestBillingCycleWithoutSubscriptionIncludesNothing()
    {
        foreach (var subs in new IReadOnlyDictionary<string, Subscription>?[]
                 { null, new Dictionary<string, Subscription>() })
        {
            var s = Spec(TimeRange.BillingCycle, null, subs);
            Assert.Empty(s.AgentStarts);
            Assert.False(s.Includes(Now, "claude"));
            var f = RangeEngine.Filter(Project(), s, "claude");
            Assert.Equal(0, f.Cost);
            Assert.False(f.HasUsage);
        }
    }

    [Fact]
    public void TestBillingCycleIgnoresUnparseableStart()
    {
        var s = Spec(TimeRange.BillingCycle, null,
            new Dictionary<string, Subscription> { ["claude"] = Sub(start: "not-a-date") });
        Assert.Null(s.Window("claude"));
        Assert.False(s.Includes(Now, "claude"));
    }

    [Fact]
    public void TestSinceResetWithoutQuotaIncludesNothing()
    {
        var s = Spec(TimeRange.SinceReset);
        Assert.Empty(s.AgentStarts);
        var f = RangeEngine.Filter(Project(), s, "claude");
        Assert.Equal(0, f.Cost);
        Assert.Equal(0, f.Tokens);
        Assert.Equal(0, f.Sessions);
        Assert.False(f.HasUsage);
    }

    // MARK: - 过滤

    private static Session MakeSession(string agent, string started, double cost = 1) =>
        new(Guid.NewGuid().ToString(), agent, Capitalize(agent), started, started, null, null, [], cost,
            Tokens.WithTotal(10), 1, "dominant", 0, null, null);

    private static string Capitalize(string s) => s.Length == 0 ? s : char.ToUpperInvariant(s[0]) + s[1..];

    /// <summary>上海时区的天：Oct 12、Oct 18、Oct 20、Oct 22。</summary>
    private static Project Project(bool byAgentTokens = true)
    {
        DayCost D(string day, Dictionary<string, double> split, Dictionary<string, long> toks) =>
            new(day, split.Values.Sum(), toks.Values.Sum(), split, byAgentTokens ? toks : null);

        var days = new List<DayCost>
        {
            D("2026-10-12", new() { ["claude"] = 1 }, new() { ["claude"] = 100 }),
            D("2026-10-18", new() { ["claude"] = 2, ["codex"] = 3 }, new() { ["claude"] = 200, ["codex"] = 300 }),
            D("2026-10-20", new() { ["claude"] = 4, ["antigravity"] = 5 }, new() { ["claude"] = 400, ["antigravity"] = 500 }),
            D("2026-10-22", new() { ["codex"] = 6 }, new() { ["codex"] = 600 }),
        };
        var sessions = new List<Session>
        {
            MakeSession("codex", "2026-10-22T03:00:00Z", 6),
            MakeSession("antigravity", "2026-10-20T05:00:00Z", 5),
            MakeSession("claude", "2026-10-20T05:00:00Z", 4),    // claude 重置（10:00Z）之前
            MakeSession("codex", "2026-10-18T03:00:00Z", 3),
            MakeSession("claude", "2026-10-18T02:00:00Z", 2),
            MakeSession("claude", "2026-10-12T02:00:00Z", 1),
        };
        var agents = new Dictionary<string, double> { ["claude"] = 7.0, ["codex"] = 9.0, ["antigravity"] = 5.0 };
        var byAgent = agents
            .OrderByDescending(kv => kv.Value)
            .Select(kv => new AgentCost(kv.Key, Capitalize(kv.Key), kv.Value, Tokens.WithTotal((long)(kv.Value * 100)),
                sessions.Count(s => s.Agent == kv.Key)))
            .ToList();
        return new Project("p", "p", null, [], false, 21, Tokens.WithTotal(2100), 6,
            "2026-10-12", "2026-10-22", byAgent, [], days, [], sessions);
    }

    [Fact]
    public void TestSevenDaysFilter()
    {
        var f = RangeEngine.Filter(Project(), Spec(TimeRange.Days7), "claude");
        Assert.Equal(20, f.Cost, 9);
        Assert.Equal(2000, f.Tokens);
        Assert.Equal(5, f.Sessions);
        Assert.Equal(["2026-10-18", "2026-10-20", "2026-10-22"], f.ByDay.Select(d => d.Day).ToArray());
        Assert.Equal("2026-10-18", f.FirstActive);
        Assert.Equal("2026-10-22", f.LastActive);
        Assert.Equal(["codex", "claude", "antigravity"], f.ByAgent.Select(a => a.Agent).ToArray());
        Assert.Equal(900, f.ByAgent[0].Tokens.Total);
        Assert.Equal(2, f.ByAgent[0].Sessions);
        Assert.Equal(20, f.Projected.Cost, 9);
        Assert.Equal(5, f.Projected.SessionsDetail.Count);
    }

    [Fact]
    public void TestLastWeekFilter()
    {
        var f = RangeEngine.Filter(Project(), Spec(TimeRange.LastWeek), "claude");
        Assert.Equal(6, f.Cost, 9);     // Oct 12 + Oct 18
        Assert.Equal(600, f.Tokens);
        Assert.Equal(3, f.Sessions);
    }

    [Fact]
    public void TestSinceResetFilterPerAgent()
    {
        var quota = new Dictionary<string, QuotaWindow>
        {
            ["claude"] = new("2026-10-27T10:00:00Z", 168, null, null, null, null, "tokei", null),
            ["codex"] = new("2026-10-28T08:00:00Z", 168, null, null, null, null, "tokei", null),
        };
        var f = RangeEngine.Filter(Project(), Spec(TimeRange.SinceReset, quota), "claude");
        // claude：Oct 20 那天与窗口相交（4）；codex：只有 Oct 22（6）；antigravity 无 quota，不计入。
        Assert.Equal(10, f.Cost, 9);
        Assert.Equal(1000, f.Tokens);
        Assert.Equal(["claude", "codex"], f.ByAgent.Select(a => a.Agent).OrderBy(a => a, StringComparer.Ordinal).ToArray());
        Assert.Equal(["2026-10-20", "2026-10-22"], f.ByDay.Select(d => d.Day).ToArray());
        Assert.Equal(4, f.ByDay[0].ByAgent!["claude"]);
        Assert.Equal(4, f.ByDay[0].Cost, 9);
        // 会话按精确时刻：claude 那条 05:00Z 早于重置，不算；codex Oct 22 算。
        Assert.Equal(1, f.Sessions);
        Assert.Equal(["codex"], f.SessionsDetail.Select(s => s.Agent).ToArray());
        Assert.Equal(0, f.ByAgent.First(a => a.Agent == "claude").Sessions);
    }

    [Fact]
    public void TestMissingByAgentTokensFallsBackToFallbackAgent()
    {
        var quota = new Dictionary<string, QuotaWindow>
        {
            ["codex"] = new("2026-10-28T08:00:00Z", 168, null, null, null, null, "tokei", null),
        };
        var p = Project(byAgentTokens: false);
        var all7 = RangeEngine.Filter(p, Spec(TimeRange.Days7), "codex");
        Assert.Equal(2000, all7.Tokens);
        Assert.Equal(2000, all7.ByAgent.First(a => a.Agent == "codex").Tokens.Total);
        Assert.Equal(0, all7.ByAgent.First(a => a.Agent == "claude").Tokens.Total);

        // sinceReset 下只有 codex 有 quota：回退到 codex 的 tokens 按 codex 的窗口算（Oct 22 一天 600）。
        var sr = RangeEngine.Filter(p, Spec(TimeRange.SinceReset, quota), "codex");
        Assert.Equal(600, sr.Tokens);
        Assert.Equal(6, sr.Cost, 9);

        // 缺 by_agent（cost）同样回退。
        var old = p with { ByDay = p.ByDay.Select(d => new DayCost(d.Day, d.Cost, d.Tokens, null, null)).ToList() };
        var f = RangeEngine.Filter(old, Spec(TimeRange.Days7), "claude");
        Assert.Equal("claude", f.ByAgent[0].Agent);
        Assert.Equal(20, f.ByAgent[0].Cost, 9);
    }

    [Fact]
    public void TestSessionCountingRangeOverlap()
    {
        var todaySpec = Spec(TimeRange.Today);

        // 1. 会话昨天开始、今天仍在用 -> 计入 Today
        var sessionActiveToday = new Session("s1", "claude", "Claude Code",
            "2026-10-23T10:00:00Z", "2026-10-24T02:00:00Z", null, null, [], 5, Tokens.WithTotal(50), 1, "dominant", 0, null, null);
        Assert.True(todaySpec.Includes(sessionActiveToday));

        // 2. 会话在范围前已结束 -> 不计入 Today
        var sessionEndedBefore = new Session("s2", "claude", "Claude Code",
            "2026-10-23T10:00:00Z", "2026-10-23T15:59:00Z", null, null, [], 5, Tokens.WithTotal(50), 1, "dominant", 0, null, null);
        Assert.False(todaySpec.Includes(sessionEndedBefore));

        // 3. 有按日数据：优先使用按日数据（仅昨天有用量 -> 不计入 Today）
        var sessionWithYesterdayOnly = new Session("s3", "claude", "Claude Code",
            "2026-10-23T10:00:00Z", "2026-10-24T02:00:00Z", null, null, [], 5, Tokens.WithTotal(50), 1, "dominant", 0, null,
            [new DayCost("2026-10-23", 5, 50, null, null)]);
        Assert.False(todaySpec.Includes(sessionWithYesterdayOnly));

        // 有今天用量 -> 计入 Today
        var sessionWithTodayUsage = new Session("s4", "claude", "Claude Code",
            "2026-10-23T10:00:00Z", "2026-10-24T02:00:00Z", null, null, [], 5, Tokens.WithTotal(50), 1, "dominant", 0, null,
            [new DayCost("2026-10-23", 3, 30, null, null), new DayCost("2026-10-24", 2, 20, null, null)]);
        Assert.True(todaySpec.Includes(sessionWithTodayUsage));

        // 4. 项目过滤验证（project row / overview summary）
        var dayToday = new DayCost("2026-10-24", 2, 20,
            new Dictionary<string, double> { ["claude"] = 2 }, new Dictionary<string, long> { ["claude"] = 20 });
        var p = new Project("proj1", "proj1", null, [], false, 7, Tokens.WithTotal(70), 2, "2026-10-23", "2026-10-24",
            [new AgentCost("claude", "Claude", 7, Tokens.WithTotal(70), 2)], [], [dayToday], [],
            [sessionActiveToday, sessionEndedBefore]);
        var filteredProject = RangeEngine.Filter(p, todaySpec, "claude");
        Assert.Equal(1, filteredProject.Sessions);
        Assert.Single(filteredProject.SessionsDetail);
        Assert.Equal("s1", filteredProject.SessionsDetail[0].Id);

        // 5. 桶过滤验证
        var bucket = new SessionBucket(10, Tokens.WithTotal(100), 2, "2026-10-23", "2026-10-24",
            [sessionActiveToday, sessionEndedBefore]);
        var filteredBucket = RangeEngine.Filter(bucket, todaySpec);
        Assert.Equal(1, filteredBucket.Sessions);
        Assert.Single(filteredBucket.SessionsDetail);
        Assert.Equal("s1", filteredBucket.SessionsDetail[0].Id);
    }

    // MARK: - 夹具

    private static string Fallback(Project p) => DominantAgent.Of(p.ByAgent)?.Agent ?? "unknown";

    [Fact]
    public void TestAllEqualsReport()
    {
        var r = LoadFixture();
        var f = RangeEngine.Filtered(r, RangeEngine.Spec(TimeRange.All, r, Now), Fallback);
        Assert.Equal(r.Totals.Cost, f.Cost);
        Assert.Equal(r.Totals.Tokens.Total, f.Tokens);
        Assert.Equal(r.Totals.Sessions, f.Sessions);
        Assert.Equal(r.Totals.FirstActive, f.FirstActive);
        Assert.Equal(r.Totals.LastActive, f.LastActive);
        Assert.Equal(r.Projects.Select(p => p.Id).ToArray(), f.Projects.Select(p => p.Id).ToArray());
        foreach (var (fp, p) in f.Projects.Zip(r.Projects))
        {
            Assert.Equal(p, fp.Projected);
            Assert.Equal(p.Cost, fp.Cost);
            Assert.Equal(p.Tokens.Total, fp.Tokens);
            Assert.Equal(p.Sessions, fp.Sessions);
        }
        Assert.Equal(r.Buckets.Unattributed.Cost, f.Unattributed.Cost);
        Assert.Equal(r.Buckets.Excluded.Sessions, f.Excluded.Sessions);
    }

    /// <summary>走累加路径但区间无界：结果与报告原值一致（金额容忍 0.01）。</summary>
    [Fact]
    public void TestUnboundedIntervalMatchesReport()
    {
        var r = LoadFixture();
        var tz = RangeEngine.TimezoneOf(r);
        var spec = new RangeSpec(TimeRange.Days30, tz, DateTimeOffset.MinValue, DateTimeOffset.MaxValue,
            new Dictionary<string, DateTimeOffset>());
        var f = RangeEngine.Filtered(r, spec, Fallback);
        Assert.Equal(r.Totals.Cost, f.Cost, 2);
        Assert.Equal(r.Totals.Tokens.Total, f.Tokens);
        Assert.Equal(r.Totals.Sessions, f.Sessions);
        foreach (var p in r.Projects)
        {
            var fp = f.Project_(p.Id);
            Assert.NotNull(fp);
            Assert.Equal(p.Cost, fp!.Cost, 2);
            Assert.Equal(p.Tokens.Total, fp.Tokens);
            Assert.Equal(p.Sessions, fp.Sessions);
            Assert.Equal(p.ByDay.Select(d => d.Day).ToArray(), fp.ByDay.Select(d => d.Day).ToArray());
            foreach (var a in p.ByAgent)
            {
                var fa = fp.ByAgent.FirstOrDefault(x => x.Agent == a.Agent);
                Assert.NotNull(fa);
                Assert.Equal(a.Cost, fa!.Cost, 2);
                Assert.Equal(a.Tokens.Total, fa.Tokens.Total);
                Assert.Equal(a.Sessions, fa.Sessions);
            }
        }
    }

    [Fact]
    public void TestFixtureRangesAreConsistent()
    {
        var r = LoadFixture();
        Assert.Equal("live", r.QuotaWindows!["claude"].Source);
        Assert.NotNull(r.QuotaWindows!.GetValueOrDefault("antigravity"));
        Assert.Null(r.QuotaWindows!.GetValueOrDefault("qwen"));
        Assert.Equal("max_5x", r.Subscriptions!["claude"].Plan);
        Assert.Equal("google_ai_pro", r.Subscriptions!["antigravity"].Plan);
        Assert.Null(r.Subscriptions!.GetValueOrDefault("qwen"));

        foreach (var range in TimeRanges.All)
        {
            var f = RangeEngine.Filtered(r, RangeEngine.Spec(range, r, Now), Fallback);
            Assert.True(f.Cost <= r.Totals.Cost + 0.01, range.RawValue());
            var costs = f.Projects.Select(p => p.Cost).ToArray();
            Assert.Equal(costs.OrderByDescending(c => c).ToArray(), costs, new DoubleComparer());
            var sum = f.Projects.Sum(p => p.Cost) + f.Unattributed.Cost + f.Excluded.Cost;
            Assert.Equal(f.Cost, sum, 2);
            foreach (var p in f.Projects)
            {
                Assert.Equal(p.Cost, p.ByDay.Sum(d => d.Cost), 6);
                Assert.Equal(p.Cost, p.ByAgent.Sum(a => a.Cost), 6);
                if (range is TimeRange.SinceReset or TimeRange.BillingCycle)
                {
                    Assert.DoesNotContain(p.ByAgent, a => a.Agent == "qwen");
                }
            }
        }
    }

    [Fact]
    public void TestFilterSessionBucketUsesInRangeShare()
    {
        var utc = TimeZoneInfo.Utc;
        var todayStart = new DateTimeOffset(2026, 10, 22, 0, 0, 0, TimeSpan.Zero);
        var todayEnd = new DateTimeOffset(2026, 10, 23, 0, 0, 0, TimeSpan.Zero);
        var todaySpec = new RangeSpec(TimeRange.Today, utc, todayStart, todayEnd,
            new Dictionary<string, DateTimeOffset>());

        // 会话 1：带 byDay，跨两天（昨天 $30/3000 tokens，今天 $10/1000 tokens）
        var sWithByDay = new Session("s1", "claude", "Claude Code",
            "2026-10-21T18:00:00Z", "2026-10-22T06:00:00Z", null, null, ["opus"], 40.0,
            Tokens.WithTotal(4000), 1, "none", 0, null,
            [new DayCost("2026-10-21", 30.0, 3000, null, null), new DayCost("2026-10-22", 10.0, 1000, null, null)]);

        // 会话 2：不带 byDay，跨 12 小时（昨天 18:00 到今天 06:00，刚好今天占 50%）
        var sOverlap = new Session("s2", "codex", "Codex CLI",
            "2026-10-21T18:00:00Z", "2026-10-22T06:00:00Z", null, null, ["codex"], 20.0,
            Tokens.WithTotal(2000), 1, "none", 0, null, null);

        var bucket = new SessionBucket(60.0, Tokens.WithTotal(6000), 2, "2026-10-21", "2026-10-22",
            [sWithByDay, sOverlap]);

        var filtered = RangeEngine.Filter(bucket, todaySpec);
        Assert.Equal(2, filtered.Sessions);
        // sWithByDay 的今天份额为 $10 / 1000 tokens；sOverlap 的今天时间重叠份额为 50% = $10 / 1000 tokens
        Assert.Equal(20.0, filtered.Cost, 4);
        Assert.Equal(2000, filtered.Tokens);
    }

    private sealed class DoubleComparer : IEqualityComparer<double>
    {
        public bool Equals(double x, double y) => Math.Abs(x - y) < 1e-9;
        public int GetHashCode(double obj) => obj.GetHashCode();
    }
}
