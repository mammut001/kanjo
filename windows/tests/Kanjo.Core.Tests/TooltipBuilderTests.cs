using Xunit;

namespace Kanjo.Core.Tests;

public sealed class TooltipBuilderTests : KanjoTestCase
{
    [Fact]
    public void TestCostAndTokensFormatting()
    {
        // zh-Hans: 万 / 亿
        Assert.Equal("$12.34 · 1.2亿 token",
            TooltipBuilder.CostAndTokens(12.34, 120_000_000, "USD", "zh-Hans"));
        Assert.Equal("$10.00 · 9000万 token",
            TooltipBuilder.CostAndTokens(10.00, 90_000_000, "USD", "zh-Hans"));
        Assert.Equal("$0.00 · 0 token",
            TooltipBuilder.CostAndTokens(0, 0, "USD", "zh-Hans"));

        // en: k / M / B
        Assert.Equal("$12.34 · 120.0M tokens",
            TooltipBuilder.CostAndTokens(12.34, 120_000_000, "USD", "en"));
        Assert.Equal("$10.00 · 90.0M tokens",
            TooltipBuilder.CostAndTokens(10.00, 90_000_000, "USD", "en"));
        Assert.Equal("$0.00 · 0 tokens",
            TooltipBuilder.CostAndTokens(0, 0, "USD", "en"));

        // fr: k / M / Md
        Assert.Equal("$12.34 · 120M tokens",
            TooltipBuilder.CostAndTokens(12.34, 120_000_000, "USD", "fr"));
        Assert.Equal("$10.00 · 90M tokens",
            TooltipBuilder.CostAndTokens(10.00, 90_000_000, "USD", "fr"));

        // Non-USD currency
        Assert.Equal("EUR 12.34 · 1.2亿 token",
            TooltipBuilder.CostAndTokens(12.34, 120_000_000, "EUR", "zh-Hans"));
    }

    [Fact]
    public void TestAgentLineFormatting()
    {
        Assert.Equal("● Claude Code  $10.00 · 9000万 token",
            TooltipBuilder.AgentLine("Claude Code", 10.00, 90_000_000, "USD", "zh-Hans"));
        Assert.Equal("● Codex  $2.34 · 30.0M tokens",
            TooltipBuilder.AgentLine("Codex", 2.34, 30_000_000, "USD", "en"));
    }

    [Fact]
    public void TestAgentLinesSortedByCostAndZeroFiltered()
    {
        var items = new (string Label, double Cost, long Tokens)[]
        {
            ("Codex", 2.34, 30_000_000),
            ("Zero Agent", 0.0, 0),
            ("Claude Code", 10.00, 90_000_000),
            ("A-Free Agent", 0.0, 50_000),
        };

        var lines = TooltipBuilder.AgentLines(items, "USD", "zh-Hans");
        Assert.Equal(3, lines.Count); // Zero Agent is filtered out
        Assert.Equal("● Claude Code  $10.00 · 9000万 token", lines[0]);
        Assert.Equal("● Codex  $2.34 · 3000万 token", lines[1]);
        Assert.Equal("● A-Free Agent  $0.00 · 5万 token", lines[2]);
    }

    [Fact]
    public void TestAgentLinesFromDictionaries()
    {
        var byAgent = new Dictionary<string, double> { ["claude"] = 10.0, ["codex"] = 2.34 };
        var byAgentTokens = new Dictionary<string, long> { ["claude"] = 90_000_000, ["codex"] = 30_000_000 };
        var labels = new Dictionary<string, string> { ["claude"] = "Claude Code", ["codex"] = "Codex" };

        var lines = TooltipBuilder.AgentLines(byAgent, byAgentTokens, labels, "USD", "zh-Hans");
        Assert.Equal(2, lines.Count);
        Assert.Equal("● Claude Code  $10.00 · 9000万 token", lines[0]);
        Assert.Equal("● Codex  $2.34 · 3000万 token", lines[1]);
    }

    [Fact]
    public void TestProjectTileTooltip()
    {
        var agents = new List<AgentCost>
        {
            new("claude", "Claude Code", 10.0, Tokens.WithTotal(90_000_000), 5),
            new("codex", "Codex", 2.34, Tokens.WithTotal(30_000_000), 2),
        };
        var tooltip = TooltipBuilder.ProjectTileTooltip("Kanjo", 12.34, 120_000_000, agents, "USD", "zh-Hans");
        var expected = string.Join("\n",
            "Kanjo · $12.34 · 1.2亿 token",
            "● Claude Code  $10.00 · 9000万 token",
            "● Codex  $2.34 · 3000万 token");
        Assert.Equal(expected, tooltip);
    }

    [Fact]
    public void TestMergedTileSumAndTooltip()
    {
        var sum = TooltipBuilder.MergedTileSum([(10.0, 90_000_000L), (2.34, 30_000_000L)]);
        Assert.Equal(12.34, sum.Cost, 9);
        Assert.Equal(120_000_000, sum.Tokens);

        var p1 = new Project("p1", "Alpha", null, [], false, 10.0, Tokens.WithTotal(90_000_000), 1,
            null, null, [], [], [], [], []);
        var p2 = new Project("p2", "Beta", null, [], false, 2.34, Tokens.WithTotal(30_000_000), 1,
            null, null, [], [], [], [], []);

        var zh = TooltipBuilder.MergedTileTooltip([p1, p2], "USD", "zh-Hans");
        Assert.Contains("2 个较小项目 · $12.34 · 1.2亿 token", zh);
        Assert.Contains("Alpha  $10.00 · 9000万 token", zh);
        Assert.Contains("Beta  $2.34 · 3000万 token", zh);

        var en = TooltipBuilder.MergedTileTooltip([p1, p2], "USD", "en");
        Assert.Contains("2 smaller projects · $12.34 · 120.0M tokens", en);
        Assert.Contains("Alpha  $10.00 · 90.0M tokens", en);
        Assert.Contains("Beta  $2.34 · 30.0M tokens", en);
    }

    [Fact]
    public void TestWeekTooltip()
    {
        var byAgent = new Dictionary<string, double> { ["claude"] = 30.0, ["codex"] = 12.10 };
        var byAgentTokens = new Dictionary<string, long> { ["claude"] = 90_000_000, ["codex"] = 30_000_000 };
        var labels = new Dictionary<string, string> { ["claude"] = "Claude Code", ["codex"] = "Codex" };

        var tooltip = TooltipBuilder.WeekTooltip("Oct 13–19", 42.10, 120_000_000, byAgent, byAgentTokens, labels, "USD", "zh-Hans");
        var expected = string.Join("\n",
            "Oct 13–19 · $42.10 · 1.2亿 token",
            "● Claude Code  $30.00 · 9000万 token",
            "● Codex  $12.10 · 3000万 token");
        Assert.Equal(expected, tooltip);
    }

    [Fact]
    public void TestDayTooltip()
    {
        var byAgent = new Dictionary<string, double> { ["claude"] = 10.00 };
        var byAgentTokens = new Dictionary<string, long> { ["claude"] = 90_000_000 };
        var labels = new Dictionary<string, string> { ["claude"] = "Claude Code" };

        var tooltip = TooltipBuilder.DayTooltip("2026-10-24", 10.00, 90_000_000, byAgent, byAgentTokens, labels, "USD", "en");
        Assert.StartsWith("Oct 24, 2026 · $10.00 · 90.0M tokens", tooltip);
        Assert.Contains("● Claude Code  $10.00 · 90.0M tokens", tooltip);
    }

    [Fact]
    public void TestModelTooltip()
    {
        var tooltip = TooltipBuilder.ModelTooltip("claude-3-5-sonnet", "claude", 10.00, 90_000_000, "USD", "zh-Hans");
        Assert.Equal("claude-3-5-sonnet (claude) · $10.00 · 9000万 token", tooltip);
    }

    [Fact]
    public void TestOverviewSummaryTextDropsDateForToday()
    {
        // zh-Hans Today: drops the date part
        var zhToday = OverviewSummaryText.Make(TimeRange.Today, "10月26日", 5, 16, 340_000_000, language: "zh-Hans");
        Assert.Equal("5 个项目 · 16 次会话 · 3.4亿 token", zhToday);
        Assert.DoesNotContain("10月26日", zhToday);

        // zh-Hans Other range (e.g. 7d): keeps the date part
        var zh7d = OverviewSummaryText.Make(TimeRange.Days7, "10月20日 – 10月26日", 5, 16, 340_000_000, language: "zh-Hans");
        Assert.Equal("10月20日 – 10月26日 · 5 个项目 · 16 次会话 · 3.4亿 token", zh7d);

        // en Today: drops date
        var enToday = OverviewSummaryText.Make(TimeRange.Today, "Oct 26", 5, 16, 340_000_000, language: "en");
        Assert.Equal("5 projects · 16 sessions · 340.0M tokens", enToday);

        // en Other range: keeps date
        var en7d = OverviewSummaryText.Make(TimeRange.Days7, "Oct 20 – Oct 26", 5, 16, 340_000_000, language: "en");
        Assert.Equal("Oct 20 – Oct 26 · 5 projects · 16 sessions · 340.0M tokens", en7d);
    }

    [Fact]
    public void TestProjectSubtitleTextDropsDateForToday()
    {
        Assert.Equal("16 次会话", ProjectSubtitleText.Make(TimeRange.Today, 16, "10月26日", "zh-Hans"));
        Assert.Equal("16 次会话 · 10月20日 – 10月26日",
            ProjectSubtitleText.Make(TimeRange.Days7, 16, "10月20日 – 10月26日", "zh-Hans"));

        Assert.Equal("16 sessions", ProjectSubtitleText.Make(TimeRange.Today, 16, "Oct 26", "en"));
        Assert.Equal("16 sessions · Oct 20 – Oct 26",
            ProjectSubtitleText.Make(TimeRange.Days7, 16, "Oct 20 – Oct 26", "en"));
    }
}
