using Xunit;

namespace Kanjo.Core.Tests;

public sealed class ModelAggregationTests : KanjoTestCase
{
    private static Tokens MakeTokens(long input = 10, long output = 20, long cacheRead = 30, long cacheWrite = 40) =>
        new(input, output, cacheRead, cacheWrite, 5, input + output + cacheRead + cacheWrite);

    private static Project MakeProject(string id, RoList<ModelCost> models, RoList<Session>? sessions = null)
    {
        var sessionsList = sessions ?? [];
        return new Project(
            id, id, null, [$"/path/{id}"], false,
            models.Sum(m => m.Cost), Tokens.WithTotal(models.Sum(m => m.Tokens.Total)), sessionsList.Count,
            "2026-10-10", "2026-10-24", [], models, [], [], sessionsList);
    }

    private static FilteredReport MakeFilteredReport(
        RoList<FilteredProject> projects,
        FilteredBucket? unattributed = null,
        FilteredBucket? excluded = null,
        bool isAll = false,
        RangeSpec? spec = null)
    {
        var u = unattributed ?? new FilteredBucket(0, 0, 0, [], null, null);
        var e = excluded ?? new FilteredBucket(0, 0, 0, [], null, null);
        var rangeSpec = spec ?? new RangeSpec(isAll ? TimeRange.All : TimeRange.Days7,
            TimeZoneInfo.Utc, null, null, new Dictionary<string, DateTimeOffset>());
        return new FilteredReport(
            rangeSpec, projects, u, e,
            projects.Sum(p => p.Cost) + u.Cost + e.Cost,
            projects.Sum(p => p.Tokens) + u.Tokens + e.Tokens,
            projects.Sum(p => p.Sessions) + u.Sessions + e.Sessions,
            "2026-10-18", "2026-10-24");
    }

    /// <summary>All 范围：直接汇总各项目的 by_model（精确值），包含 cache 读写并按总 token 降序排序。</summary>
    [Fact]
    public void TestAllRangeUsesProjectByModelExact()
    {
        var t1 = MakeTokens(100, 200, 300, 400); // total = 1000
        var t2 = MakeTokens(50, 50, 500, 400);   // total = 1000
        var t3 = MakeTokens(10, 10, 30, 50);     // total = 100

        var p1 = MakeProject("p1",
        [
            new ModelCost("opus", "claude", 15.0, t1, false),
            new ModelCost("haiku", "claude", 1.0, t3, false),
        ]);
        var p2 = MakeProject("p2", [new ModelCost("opus", "claude", 10.0, t2, false)]);

        var fp1 = new FilteredProject(p1, p1.Cost, p1.Tokens.Total, 0, [], [], [], null, null);
        var fp2 = new FilteredProject(p2, p2.Cost, p2.Tokens.Total, 0, [], [], [], null, null);

        var result = ModelAggregation.Aggregate(MakeFilteredReport([fp1, fp2], isAll: true));

        Assert.Equal(2, result.Count);
        var opus = result.First(m => m.Model == "opus");
        Assert.Equal(2000, opus.Tokens.Total);
        Assert.Equal(800, opus.Tokens.CacheRead);
        Assert.Equal(800, opus.Tokens.CacheWrite);
        Assert.Equal(25.0, opus.Cost, 9);
        Assert.False(opus.Estimated);

        var haiku = result.First(m => m.Model == "haiku");
        Assert.Equal(100, haiku.Tokens.Total);
        Assert.Equal(30, haiku.Tokens.CacheRead);
        Assert.Equal(50, haiku.Tokens.CacheWrite);
        Assert.Equal(1.0, haiku.Cost, 9);
    }

    /// <summary>非 All 范围：不使用全量 by_model，仅从范围内会话汇总。</summary>
    [Fact]
    public void TestNonAllRangeAggregatesOnlyFromInRangeSessions()
    {
        var p = MakeProject("p",
        [
            new ModelCost("opus", "claude", 100.0, Tokens.WithTotal(100_000), false),
            new ModelCost("sonnet", "claude", 50.0, Tokens.WithTotal(50_000), false),
        ]);

        var inRangeSession = new Session("s1", "claude", "Claude Code",
            "2026-10-22T10:00:00Z", "2026-10-22T10:30:00Z", null, null, ["sonnet"], 1.2,
            MakeTokens(200, 200, 400, 400), 1, "dominant", 0, "recent session", null);

        var fp = new FilteredProject(p, inRangeSession.Cost, inRangeSession.Tokens.Total, 1, [], [],
            [inRangeSession], null, null);

        var result = ModelAggregation.Aggregate(MakeFilteredReport([fp]));
        Assert.Single(result);
        Assert.Equal("sonnet", result[0].Model);
        Assert.Equal(1200, result[0].Tokens.Total);
        Assert.Equal(1.2, result[0].Cost, 9);
        Assert.False(result[0].Estimated);
    }

    /// <summary>多模型会话平分 token，整除余数给首个模型，标记 estimated=true；单模型会话 estimated=false。</summary>
    [Fact]
    public void TestMultiModelSessionSplitsEvenlyWithRemainderToFirstModel()
    {
        var multiSession = new Session("s_multi", "claude", "Claude Code",
            "2026-10-22T10:00:00Z", "2026-10-22T10:30:00Z", null, null, ["m0", "m1", "m2"], 30.0,
            MakeTokens(10, 20, 30, 40), 1, "dominant", 0, null, null);

        var fp = new FilteredProject(MakeProject("p", []), multiSession.Cost, multiSession.Tokens.Total, 1,
            [], [], [multiSession], null, null);

        var result = ModelAggregation.Aggregate(MakeFilteredReport([fp]));
        Assert.Equal(3, result.Count);
        var m0 = result.First(m => m.Model == "m0");
        var m1 = result.First(m => m.Model == "m1");
        var m2 = result.First(m => m.Model == "m2");

        Assert.Equal(4, m0.Tokens.Input);
        Assert.Equal(3, m1.Tokens.Input);
        Assert.Equal(3, m2.Tokens.Input);

        Assert.Equal(8, m0.Tokens.Output);
        Assert.Equal(6, m1.Tokens.Output);
        Assert.Equal(6, m2.Tokens.Output);

        Assert.Equal(36, m0.Tokens.Total);
        Assert.Equal(32, m1.Tokens.Total);
        Assert.Equal(32, m2.Tokens.Total);
        Assert.Equal(100, m0.Tokens.Total + m1.Tokens.Total + m2.Tokens.Total);

        Assert.Equal(10.0, m0.Cost, 9);
        Assert.Equal(10.0, m1.Cost, 9);
        Assert.Equal(10.0, m2.Cost, 9);

        Assert.True(m0.Estimated);
        Assert.True(m1.Estimated);
        Assert.True(m2.Estimated);
    }

    /// <summary>范围报告下模型行总 token 之和严格等于总览 hero 总 token 数。</summary>
    [Fact]
    public void TestSumInvariantMatchesHeroTotalTokens()
    {
        var sProjSingle = new Session("s1", "claude", "Claude Code", "2026-10-22T08:00:00Z",
            "2026-10-22T08:10:00Z", null, null, ["opus"], 5.0, MakeTokens(100, 200, 300, 400),
            1, "dominant", 0, null, null); // 1000
        var sProjMulti = new Session("s2", "claude", "Claude Code", "2026-10-22T09:00:00Z",
            "2026-10-22T09:10:00Z", null, null, ["sonnet", "haiku", "opus"], 9.0, MakeTokens(77, 88, 99, 111),
            1, "dominant", 0, null, null); // 375
        var sUnattributed = new Session("s3", "codex", "Codex CLI", "2026-10-22T10:00:00Z",
            "2026-10-22T10:10:00Z", null, null, ["gpt-4o", "gpt-4o-mini"], 4.0, MakeTokens(15, 25, 35, 45),
            1, "cwd", 0, null, null); // 120
        var sExcluded = new Session("s4", "antigravity", "Antigravity", "2026-10-22T11:00:00Z",
            "2026-10-22T11:10:00Z", null, null, ["gemini-pro"], 2.0, MakeTokens(50, 50, 50, 50),
            1, "override", 0, null, null); // 200

        var fp = new FilteredProject(MakeProject("p1", []),
            sProjSingle.Cost + sProjMulti.Cost, sProjSingle.Tokens.Total + sProjMulti.Tokens.Total, 2,
            [], [], [sProjSingle, sProjMulti], null, null);
        var u = new FilteredBucket(sUnattributed.Cost, sUnattributed.Tokens.Total, 1, [sUnattributed], null, null);
        var e = new FilteredBucket(sExcluded.Cost, sExcluded.Tokens.Total, 1, [sExcluded], null, null);

        var report = MakeFilteredReport([fp], u, e);
        var heroTokens = report.Tokens;
        Assert.Equal(1000 + 375 + 120 + 200, heroTokens);

        var models = ModelAggregation.Aggregate(report);
        Assert.Equal(heroTokens, models.Sum(m => m.Tokens.Total));
    }

    /// <summary>跨天会话在非 All 范围下只计入范围内份额，不变量依然严格成立。</summary>
    [Fact]
    public void TestSumInvariantHoldsWithSessionSpanningYesterdayToToday()
    {
        var cal = TimeZoneInfo.Utc;
        var todayStart = new DateTimeOffset(2026, 10, 22, 0, 0, 0, TimeSpan.Zero);
        var todayEnd = new DateTimeOffset(2026, 10, 23, 0, 0, 0, TimeSpan.Zero);
        var todaySpec = new RangeSpec(TimeRange.Today, cal, todayStart, todayEnd, new Dictionary<string, DateTimeOffset>());

        var spanningSession = new Session("s_spanning", "claude", "Claude Code",
            "2026-10-21T18:00:00Z", "2026-10-22T06:00:00Z", null, null, ["claude-opus-5-5"], 558.42,
            MakeTokens(400_000, 480_000, 500_000, 500_000), 1, "dominant", 0, "spanning session", null);

        var todayDayCost = new DayCost("2026-10-22", 91.00, 91_000, null, null);
        var fp = new FilteredProject(MakeProject("p_today", []), todayDayCost.Cost, todayDayCost.Tokens, 1,
            [new AgentCost("claude", "Claude Code", 91.00, Tokens.WithTotal(91_000), 1)],
            [todayDayCost], [spanningSession], "2026-10-22", "2026-10-22");

        var report = new FilteredReport(todaySpec, [fp], new FilteredBucket(0, 0, 0, [], null, null),
            new FilteredBucket(0, 0, 0, [], null, null), 91.00, 91_000, 1, "2026-10-22", "2026-10-22");

        var models = ModelAggregation.Aggregate(report);
        Assert.Single(models);
        var opus = models.First(m => m.Model == "claude-opus-5-5");
        Assert.Equal(91_000, opus.Tokens.Total);
        Assert.Equal(91.00, opus.Cost, 4);
        Assert.Equal(report.Tokens, models.Sum(m => m.Tokens.Total));

        // 会话自带 per-session byDay 数据
        var sessionWithByDay = new Session("s_by_day", "claude", "Claude Code",
            "2026-10-21T18:00:00Z", "2026-10-22T06:00:00Z", null, null, ["claude-opus-5-5"], 50.0,
            MakeTokens(1000, 1000, 1000, 1000), 1, "dominant", 0, "session with by day",
            [new DayCost("2026-10-21", 40.0, 3200, null, null), new DayCost("2026-10-22", 10.0, 800, null, null)]);

        var fpWithByDay = new FilteredProject(MakeProject("p_by_day", []), 10.0, 800, 1, [],
            [new DayCost("2026-10-22", 10.0, 800, null, null)], [sessionWithByDay], "2026-10-22", "2026-10-22");
        var reportWithByDay = new FilteredReport(todaySpec, [fpWithByDay],
            new FilteredBucket(0, 0, 0, [], null, null), new FilteredBucket(0, 0, 0, [], null, null),
            10.0, 800, 1, "2026-10-22", "2026-10-22");

        var modelsWithByDay = ModelAggregation.Aggregate(reportWithByDay);
        Assert.Single(modelsWithByDay);
        Assert.Equal(800, modelsWithByDay[0].Tokens.Total);
        Assert.Equal(10.0, modelsWithByDay[0].Cost, 4);
        Assert.Equal(reportWithByDay.Tokens, modelsWithByDay.Sum(m => m.Tokens.Total));
    }

    [Fact]
    public void TestApportionIsExact()
    {
        var parts = ModelAggregation.Apportion(100, [1, 1, 1]);
        Assert.Equal(100, parts.Sum());
        Assert.Equal([34, 33, 33], parts.ToArray());

        var zeroWeights = ModelAggregation.Apportion(10, [0, 0, 0]);
        Assert.Equal(10, zeroWeights.Sum());

        Assert.Empty(ModelAggregation.Apportion(10, []));
        Assert.Equal([0, 0], ModelAggregation.Apportion(0, [1.0, 2.0]).ToArray());
    }
}
