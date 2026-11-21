using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace Kanjo.Core.Tests;

// Set KANJO_PARITY_DUMP to a path to regenerate the Windows golden file.
public sealed class ParityDumpTests : KanjoTestCase
{
    [Fact]
    public void TestDump()
    {
        var fixture = LoadFixture();
        (string Zone, string Instant)[] scenarios = [
            ("America/New_York", "2026-10-24T07:00:00Z"),
            ("Asia/Shanghai", "2026-10-24T07:00:00Z"),
            ("Europe/Berlin", "2026-10-24T07:00:00Z"),
            ("America/New_York", "2026-03-08T07:30:00Z"), // DST transition
            ("America/New_York", "2026-10-26T04:30:00Z"), // Monday 00:30
            ("Asia/Shanghai", "2026-01-31T12:00:00Z"),
            ("Europe/Berlin", "2025-02-28T12:00:00Z"),
            ("America/New_York", "2024-02-29T12:00:00Z"),
        ];
        static long Cents(double x) => (long)Math.Round(x * 100, MidpointRounding.AwayFromZero);
        static string Stamp(DateTimeOffset date) => date.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'");
        static string Fallback(Project p) => DominantAgent.Of(p.ByAgent)?.Agent ?? p.ByAgent.FirstOrDefault()?.Agent ?? "unknown";
        var result = new Dictionary<string, object>();
        foreach (var (zone, instant) in scenarios)
        {
            var report = fixture with { Timezone = zone };
            var tz = TimeZoneInfo.FindSystemTimeZoneById(zone);
            var now = ReportDates.ParseTimestamp(instant)!.Value;
            var ranges = new Dictionary<string, object>();
            foreach (var range in TimeRanges.All)
            {
                var f = RangeEngine.Filtered(report, RangeEngine.Spec(range, report, now), Fallback);
                var share = ShareSummary.Build(report, range.RawValue(), now);
                var t = share.Totals;
                var projects = f.Projects.ToDictionary(p => p.Id, p => new {
                    cost = Cents(p.Cost), tokens = p.Tokens, sessions = p.Sessions,
                    agents = p.ByAgent.ToDictionary(a => a.Agent, a => new { cost = Cents(a.Cost), tokens = a.Tokens.Total })
                });
                var agentCosts = new Dictionary<string, double>();
                var agentTokens = new Dictionary<string, long>();
                foreach (var agent in f.Projects.SelectMany(p => p.ByAgent))
                {
                    agentCosts[agent.Agent] = agentCosts.GetValueOrDefault(agent.Agent) + agent.Cost;
                    agentTokens[agent.Agent] = agentTokens.GetValueOrDefault(agent.Agent) + agent.Tokens.Total;
                }
                foreach (var session in f.Unattributed.SessionsDetail.Concat(f.Excluded.SessionsDetail))
                {
                    var (cost, tokens) = f.Spec.InRangeCostAndTokens(session);
                    agentCosts[session.Agent] = agentCosts.GetValueOrDefault(session.Agent) + cost;
                    agentTokens[session.Agent] = agentTokens.GetValueOrDefault(session.Agent) + tokens;
                }
                var agents = agentCosts.Keys.Union(agentTokens.Keys).ToDictionary(a => a,
                    a => new { cost = Cents(agentCosts.GetValueOrDefault(a)), tokens = agentTokens.GetValueOrDefault(a) });
                var models = ModelAggregation.Aggregate(f).ToDictionary(m => m.Id, m => new { cost = Cents(m.Cost), tokens = m.Tokens.Total, estimated = m.Estimated });
                ranges[range.RawValue()] = new { start = f.Spec.Start is { } start ? Stamp(start) : null, end = f.Spec.End is { } end ? Stamp(end) : null, agentStarts = f.Spec.AgentStarts.ToDictionary(a => a.Key, a => Stamp(a.Value)), cost = Cents(f.Cost), tokens = f.Tokens, sessions = f.Sessions, projects, models,
                    agents, shareRows = share.AgentRows.ToDictionary(a => a.Agent, a => new { sessions = a.SessionCount, input = a.TokenBreakdown.Input, output = a.TokenBreakdown.Output, cacheRead = a.TokenBreakdown.CacheRead, cacheWrite = a.TokenBreakdown.CacheWrite, thinking = a.TokenBreakdown.Thinking, multiplier = a.Multiplier is { } m ? Cents(m) : (long?)null }), share = new { cost = Cents(t.Cost), tokens = t.Tokens, sessions = t.Sessions, agents = t.AgentsCount, input = t.Input, output = t.Output, cacheRead = t.CacheRead, cacheWrite = t.CacheWrite, thinking = t.Thinking } };
            }
            var subs = SubscriptionValue.Rows(report, now).ToDictionary(row => row.Agent, row => {
                var sub = report.Subscriptions![row.Agent];
                return new { plan = sub.Plan, start = sub.CycleStart, end = sub.CycleEnd, value = Cents(row.Usage), multiplier = row.Multiplier is { } m ? Cents(m) : (long?)null };
            });
            var quotas = report.QuotaWindows!.ToDictionary(pair => pair.Key, pair => SubscriptionValue.QuotaRows(pair.Value, tz, now).Select(row => new { id = row.Id, reset = row.Id == "weekly" ? pair.Value.WeeklyResetsAt : row.Id == "five_hour" ? pair.Value.FiveHourResetsAt : pair.Value.ExtraWindows?.FirstOrDefault(w => w.Id == row.Id)?.ResetsAt, ended = row.Detail == L10n.Tr("overview.quota.ended"), percent = row.Percent }).ToArray());
            var heat = report.Projects.ToDictionary(p => p.Id, p => HeatStrip.Weekly(p.ByDay, now, Fallback(p), timezone: tz).Select(w => new { start = w.Start.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"), cost = Cents(w.Cost), tokens = w.Tokens, agents = w.ByAgent.ToDictionary(a => a.Key, a => Cents(a.Value)), agentTokens = w.ByAgentTokens }).ToArray());
            var reference = WeeklyTokens.Reference(now, ReportDates.ParseTimestamp(report.GeneratedAt));
            result[zone + "|" + instant] = new { ranges, subscriptions = subs, quotas, weeklyTokens = WeeklyTokens.Since(reference, report.Projects, tz), heat };
        }
        var json = JsonSerializer.Serialize(result);
        var path = Environment.GetEnvironmentVariable("KANJO_PARITY_DUMP");
        if (path is not null) File.WriteAllText(path, json);
        else
        {
            var root = Directory.GetParent(Directory.GetParent(Directory.GetParent(FixturePath)!.FullName)!.FullName)!.FullName;
            var golden = File.ReadAllText(Path.Combine(root, "parity", "windows.json"));
            Assert.True(JsonNode.DeepEquals(JsonNode.Parse(golden), JsonNode.Parse(json)), "Windows parity dump changed; regenerate and compare both goldens");
        }
    }
}
