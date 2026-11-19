using System.Text;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>Mac <c>ShareSummaryTests</c>：同一份 7 个项目的报告，总额、Top 5、隐藏项目、agent 行。</summary>
public sealed class ShareSummaryTests : KanjoTestCase
{
    private static UsageReport MakeReport()
    {
        var projects = new StringBuilder();
        for (var i = 1; i <= 7; i++)
        {
            if (i > 1) projects.Append(',');
            var cost = (8 - i) * 10;
            var claudeCost = cost * 6 / 10;
            var codexCost = cost * 4 / 10;
            var claudeTokens = cost * 600;
            var codexTokens = cost * 400;
            projects.Append($$"""
                {
                    "id": "p{{i}}", "name": "Project {{i}}", "cost": {{cost}}, "tokens": {"total": {{cost * 1000}}}, "sessions": 2,
                    "by_agent": [
                        {"agent": "claude", "label": "Claude Code", "cost": {{claudeCost}}, "tokens": {"total": {{claudeTokens}}}, "sessions": 1},
                        {"agent": "codex", "label": "Codex", "cost": {{codexCost}}, "tokens": {"total": {{codexTokens}}}, "sessions": 1}
                    ],
                    "by_model": [],
                    "by_day": [{"day": "2026-11-17", "cost": {{cost}}, "tokens": {{cost * 1000}}, "by_agent": {"claude": {{claudeCost}}, "codex": {{codexCost}}}, "by_agent_tokens": {"claude": {{claudeTokens}}, "codex": {{codexTokens}}}],
                    "sessions_detail": [
                        {"id": "s1-{{i}}", "agent": "claude", "label": "Claude Code", "started": "2026-11-17T10:00:00Z", "ended": "2026-11-17T11:00:00Z", "cost": {{claudeCost}}, "tokens": {"input": 100, "output": 100, "cache_read": 100, "cache_write": 100, "thinking": 200, "total": {{claudeTokens}}}, "share": 0.6, "attribution": "none", "subagents": 0},
                        {"id": "s2-{{i}}", "agent": "codex", "label": "Codex", "started": "2026-11-17T10:00:00Z", "ended": "2026-11-17T11:00:00Z", "cost": {{codexCost}}, "tokens": {"input": 100, "output": 100, "cache_read": 100, "cache_write": 100, "thinking": 0, "total": {{codexTokens}}}, "share": 0.4, "attribution": "none", "subagents": 0}
                    ]
                }
                """);
        }

        var json = $$"""
            {
                "schema_version": 1,
                "generated_at": "2026-11-18T10:00:00Z",
                "currency": "USD",
                "cost_note": "",
                "totals": {"cost": 280, "tokens": {"total": 280000}, "sessions": 14},
                "projects": [{{projects}}],
                "buckets": {
                    "unattributed": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                    "excluded": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                    "parse_failed": {"sessions": 0, "files": []}
                }
            }
            """;
        return ReportDecoder.Decode(json);
    }

    [Fact]
    public void TestBuild()
    {
        var summary = ShareSummary.Build(MakeReport(), "all");
        Assert.Equal(280000, summary.Totals.Tokens);
        Assert.Equal(280, summary.Totals.Cost, 2);
        Assert.Equal(L10n.Tr("timerange.all.long"), summary.RangeLabel);
    }

    [Fact]
    public void TestTopProjectsSortedLimitedAndHidden()
    {
        var now = DateTimeOffset.FromUnixTimeSeconds(1763460000);
        var summary = ShareSummary.Build(MakeReport(), "all", now, new HashSet<string> { "p1" });

        Assert.Equal(5, summary.TopProjects.Count);
        Assert.Equal(
            ["Project 2", "Project 3", "Project 4", "Project 5", "Project 6"],
            summary.TopProjects.Select(project => project.Name).ToList());

        var costs = summary.TopProjects.Select(project => project.Cost).ToList();
        Assert.True(costs[0] > costs[1] && costs[1] > costs[2] && costs[2] > costs[3] && costs[3] > costs[4]);
        Assert.True(summary.TopProjects.Sum(project => project.Share) <= 1.0001);

        Assert.Equal(6, summary.MosaicProjects.Count);
        Assert.DoesNotContain(summary.MosaicProjects, project => project.Id == "p1");
        Assert.Equal(Ts("2026-11-18T10:00:00Z"), summary.Updated);
    }

    [Fact]
    public void TestAgentRowsMatchAgentSummary()
    {
        var now = DateTimeOffset.FromUnixTimeSeconds(1763460000);
        var report = MakeReport();
        var filtered = new RangeContext(report, "all", now).Filtered();

        // Windows 没有 AgentSummary 类型：这里按同一条规则自己加总（项目 by_agent + 范围内的桶会话）。
        var expectedCost = new Dictionary<string, double>(StringComparer.Ordinal);
        var expectedTokens = new Dictionary<string, long>(StringComparer.Ordinal);
        foreach (var project in filtered.Projects)
        {
            foreach (var agent in project.ByAgent)
            {
                expectedCost[agent.Agent] = expectedCost.GetValueOrDefault(agent.Agent) + agent.Cost;
                expectedTokens[agent.Agent] = expectedTokens.GetValueOrDefault(agent.Agent) + agent.Tokens.Total;
            }
        }

        foreach (var session in filtered.Unattributed.SessionsDetail.Concat(filtered.Excluded.SessionsDetail))
        {
            var (cost, tokens) = filtered.Spec.InRangeCostAndTokens(session);
            expectedCost[session.Agent] = expectedCost.GetValueOrDefault(session.Agent) + cost;
            expectedTokens[session.Agent] = expectedTokens.GetValueOrDefault(session.Agent) + tokens;
        }

        var summary = ShareSummary.Build(report, "all", now);
        var expectedAgents = expectedTokens.Where(pair => pair.Value > 0).Select(pair => pair.Key).OrderBy(agent => agent).ToList();
        Assert.Equal(expectedAgents, summary.AgentRows.Select(row => row.Agent).OrderBy(agent => agent).ToList());
        foreach (var row in summary.AgentRows)
        {
            Assert.Equal(expectedTokens[row.Agent], row.Tokens);
            Assert.Equal(expectedCost[row.Agent], row.Cost, 6);
        }
    }

    [Fact]
    public void TestTotalsMatchFiltered()
    {
        var now = DateTimeOffset.FromUnixTimeSeconds(1763460000);
        var report = MakeReport();
        var filtered = new RangeContext(report, "all", now).Filtered();
        var summary = ShareSummary.Build(report, "all", now);

        Assert.Equal(filtered.Tokens, summary.Totals.Tokens);
        Assert.Equal(filtered.Cost, summary.Totals.Cost, 6);
        Assert.Equal(2, summary.AgentRows.Count);
    }
}
