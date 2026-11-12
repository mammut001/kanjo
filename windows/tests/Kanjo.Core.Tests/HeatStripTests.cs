using Xunit;

namespace Kanjo.Core.Tests;

public sealed class HeatStripTests : KanjoTestCase
{
    private static readonly TimeZoneInfo Utc = TimeZoneInfo.Utc;

    private static DateTimeOffset Date(string s) => Time.AtDay(Utc, ReportDates.ParseDay(s)!.Value);

    private static DayCost D(string day, double cost, Dictionary<string, double>? split = null) =>
        new(day, cost, 0, split, null);

    private static IReadOnlyList<WeekCost> Weekly(IReadOnlyList<DayCost> days, string fallback = "claude") =>
        HeatStrip.Weekly(days, End, fallback, HeatStrip.DefaultWeeks, Utc);

    private static WeekCost Week(Dictionary<string, double> split) =>
        new(End, split.Values.Sum(), 0, split, new Dictionary<string, long>());

    // 2026-10-24 是周六；它所在的周是 Oct 19 (Mon) – Oct 25 (Sun)。
    private static DateTimeOffset End => Date("2026-10-24");

    [Fact]
    public void TestWeekStartsAreMondaysOldestFirst()
    {
        var starts = HeatStrip.WeekStarts(End, HeatStrip.DefaultWeeks, Utc);
        Assert.Equal(8, starts.Count);
        Assert.Equal(Date("2026-10-19"), starts[^1]);
        Assert.Equal(Date("2026-08-31"), starts[0]);
        var startDates = starts.Select(s => Time.LocalDate(Utc, s)).ToList();
        Assert.All(startDates, d => Assert.Equal(DayOfWeek.Monday, d.DayOfWeek));
    }

    [Fact]
    public void TestEndOnSundayAndMonday()
    {
        Assert.Equal(Date("2026-10-19"),
            HeatStrip.WeekStarts(Date("2026-10-25"), HeatStrip.DefaultWeeks, Utc)[^1]);
        Assert.Equal(Date("2026-10-26"),
            HeatStrip.WeekStarts(Date("2026-10-26"), HeatStrip.DefaultWeeks, Utc)[^1]);
    }

    [Fact]
    public void TestEmptyInputGivesEightZeros()
    {
        var w = Weekly([]);
        Assert.Equal(Enumerable.Repeat(0.0, 8).ToArray(), w.Select(x => x.Cost).ToArray());
        Assert.Equal(HeatStrip.WeekStarts(End, HeatStrip.DefaultWeeks, Utc).ToArray(), w.Select(x => x.Start).ToArray());
        Assert.All(w, x => Assert.Empty(x.ByAgent));
        Assert.All(w, x => Assert.Null(x.TopAgent));
    }

    [Fact]
    public void TestSumsWithinWeeksAndSplitsAcrossWeekBoundary()
    {
        var days = new List<DayCost>
        {
            D("2026-10-18", 1), D("2026-10-19", 2), D("2026-10-24", 3),   // Sun | Mon, Sat
            D("2026-10-12", 4), D("2026-10-13", 0.5),
        };
        var w = Weekly(days);
        Assert.Equal(8, w.Count);
        Assert.Equal(5, w[7].Cost, 9);   // Oct 19 + Oct 24
        Assert.Equal(5.5, w[6].Cost, 9); // Oct 12 + Oct 13 + Oct 18
        Assert.Equal(0, w.Take(6).Sum(x => x.Cost));
    }

    [Fact]
    public void TestDropsDaysOlderThanEightWeeksAndAfterEndWeek()
    {
        var days = new List<DayCost>
        {
            D("2026-08-30", 100),  // 周日，第 1 周之前一天
            D("2026-08-31", 1),    // 第 1 周周一
            D("2026-10-26", 50),   // 结束周之后
            D("garbage", 7),
        };
        Assert.Equal([1, 0, 0, 0, 0, 0, 0, 0], Weekly(days).Select(x => x.Cost).ToArray());
    }

    [Fact]
    public void TestAccumulatesByAgentAcrossDaysAndWeeks()
    {
        var days = new List<DayCost>
        {
            D("2026-10-12", 3, new() { ["claude"] = 2, ["codex"] = 1 }),
            D("2026-10-14", 4, new() { ["codex"] = 4 }),
            D("2026-10-18", 1, new() { ["antigravity"] = 0.5, ["claude"] = 0.5 }), // 周日，仍是 Oct 12 那周
            D("2026-10-19", 6, new() { ["antigravity"] = 6 }),                     // 下一周
        };
        var w = Weekly(days);
        Assert.Equal(8, w[6].Cost, 9);
        Assert.Equal(2.5, w[6].ByAgent["claude"], 9);
        Assert.Equal(5, w[6].ByAgent["codex"], 9);
        Assert.Equal(0.5, w[6].ByAgent["antigravity"], 9);
        Assert.Equal("codex", w[6].TopAgent);
        Assert.Equal(["codex", "claude", "antigravity"], w[6].Ranked.Select(r => r.Agent).ToArray());
        Assert.Equal(6, w[7].ByAgent["antigravity"], 9);
        Assert.Equal("antigravity", w[7].TopAgent);
    }

    [Fact]
    public void TestMissingByAgentFallsBackToProjectAgent()
    {
        var days = new List<DayCost>
        {
            D("2026-10-19", 5),                                // 旧数据：没有 by_agent
            D("2026-10-20", 2, new Dictionary<string, double>()), // 空字典同样回退
            D("2026-10-21", 1, new() { ["claude"] = 1 }),
        };
        var w = Weekly(days, "codex");
        Assert.Equal(8, w[7].Cost, 9);
        Assert.Equal(7, w[7].ByAgent["codex"], 9);
        Assert.Equal(1, w[7].ByAgent["claude"], 9);
        Assert.Equal("codex", w[7].TopAgent);
        Assert.Equal(4, Weekly([D("2026-10-13", 4)], "antigravity")[6].ByAgent["antigravity"], 9);
    }

    [Fact]
    public void TestAccumulatesTokensAndByAgentTokens()
    {
        var d1 = new DayCost("2026-10-19", 5.0, 50_000,
            new Dictionary<string, double> { ["claude"] = 5.0 },
            new Dictionary<string, long> { ["claude"] = 50_000 });
        var d2 = new DayCost("2026-10-20", 2.0, 20_000, null, null); // 回退到 fallbackAgent
        var w = Weekly([d1, d2], "codex");
        Assert.Equal(7.0, w[7].Cost, 9);
        Assert.Equal(70_000, w[7].Tokens);
        Assert.Equal(50_000, w[7].ByAgentTokens["claude"]);
        Assert.Equal(20_000, w[7].ByAgentTokens["codex"]);
    }

    [Fact]
    public void TestSegmentsOrderedByCostAndSharesSumToOne()
    {
        var s = HeatStrip.Segments(Week(new Dictionary<string, double> { ["claude"] = 354, ["antigravity"] = 164 }));
        Assert.Equal(["claude", "antigravity"], s.Select(x => x.Agent).ToArray());
        Assert.Equal(354.0 / 518, s[0].Share, 9);
        Assert.Equal(1, s.Sum(x => x.Share), 9);
    }

    [Fact]
    public void TestSegmentsMergeSmallSharesIntoLargest()
    {
        // codex 5% < 10%：并进 claude
        var s = HeatStrip.Segments(Week(new Dictionary<string, double> { ["claude"] = 60, ["antigravity"] = 35, ["codex"] = 5 }));
        Assert.Equal(["claude", "antigravity"], s.Select(x => x.Agent).ToArray());
        Assert.Equal(0.65, s[0].Share, 9);
        Assert.Equal(0.35, s[1].Share, 9);
    }

    [Fact]
    public void TestSegmentsCapAtThree()
    {
        var s = HeatStrip.Segments(Week(new Dictionary<string, double> { ["a"] = 30, ["b"] = 25, ["c"] = 25, ["d"] = 20 }));
        Assert.Equal(["a", "b", "c"], s.Select(x => x.Agent).ToArray());
        Assert.Equal(0.5, s[0].Share, 9);
        Assert.Equal(1, s.Sum(x => x.Share), 9);
    }

    [Fact]
    public void TestSegmentsEmptyAndSingle()
    {
        Assert.Empty(HeatStrip.Segments(Week([])));
        Assert.Empty(HeatStrip.Segments(Week(new Dictionary<string, double> { ["claude"] = 0 })));
        var one = HeatStrip.Segments(Week(new Dictionary<string, double> { ["codex"] = 2 }));
        Assert.Equal(["codex"], one.Select(x => x.Agent).ToArray());
        Assert.Equal(1, one[0].Share, 9);
    }

    [Fact]
    public void TestLevels()
    {
        Assert.Equal(0, HeatStrip.Level(0, 10));
        Assert.Equal(0, HeatStrip.Level(5, 0));
        Assert.Equal(1, HeatStrip.Level(0.01, 10));
        Assert.Equal(1, HeatStrip.Level(2.5, 10));
        Assert.Equal(2, HeatStrip.Level(2.6, 10));
        Assert.Equal(3, HeatStrip.Level(7.5, 10));
        Assert.Equal(4, HeatStrip.Level(10, 10));
        Assert.Equal(4, HeatStrip.Level(20, 10));
    }

    [Fact]
    public void TestWeekLabel()
    {
        Assert.Equal("Oct 12–18", HeatStrip.WeekLabel(Date("2026-10-12"), Utc));
        Assert.Equal("Sep 28–Oct 4", HeatStrip.WeekLabel(Date("2026-09-28"), Utc));
        Assert.Equal("Dec 29, 2025–Jan 4, 2026", HeatStrip.WeekLabel(Date("2025-12-29"), Utc));
    }

    [Fact]
    public void TestDominantAgent()
    {
        var t = Tokens.Zero;
        var agents = new List<AgentCost>
        {
            new("codex", "Codex CLI", 1, t, 1),
            new("claude", "Claude Code", 3, t, 1),
        };
        var d = DominantAgent.Of(agents);
        Assert.NotNull(d);
        Assert.Equal("claude", d!.Value.Agent);
        Assert.Equal(0.75, d.Value.Share, 9);
        Assert.Null(DominantAgent.Of([]));
        Assert.Null(DominantAgent.Of([new AgentCost("x", "X", 0, t, 0)]));
    }
}
