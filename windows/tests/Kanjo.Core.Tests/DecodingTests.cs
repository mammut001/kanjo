using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace Kanjo.Core.Tests;

public sealed class DecodingTests : KanjoTestCase
{
    private static UsageReport Load() => ReportDecoder.Decode(File.ReadAllBytes(FixturePath));

    private static byte[] MutatedFixture(Action<JsonObject> mutate)
    {
        var text = File.ReadAllText(FixturePath);
        var obj = JsonNode.Parse(text)!.AsObject();
        mutate(obj);
        return System.Text.Encoding.UTF8.GetBytes(obj.ToJsonString());
    }

    [Fact]
    public void TestFixtureDecodes()
    {
        var r = Load();
        Assert.Equal(1, r.SchemaVersion);
        Assert.False(r.IsNewerSchema);
        Assert.Equal("USD", r.Currency);
        Assert.False(string.IsNullOrEmpty(r.CostNote));
        Assert.Equal(L10n.Tr("common.cost_note_default"), r.CostNoteDisplayText);
        Assert.InRange(r.Projects.Count, 6, 8);
    }

    [Fact]
    public void TestQuotaWindowUsageDecodes()
    {
        var q = Load().QuotaWindows!["claude"];
        Assert.Equal(57, q.WeeklyUsedPercent);
        Assert.Equal(13, q.FiveHourUsedPercent);
        Assert.Equal(5, q.FiveHourWindowHours);

        // 旧导出没有这些字段：仍能解码，值为 null
        const string old = """{"weekly_resets_at":"2026-10-27T14:00:00Z","weekly_window_hours":168,"five_hour_resets_at":null,"source":"tokei"}""";
        using var doc = JsonDocument.Parse(old);
        var w = QuotaWindow.Decode(doc.RootElement, "");
        Assert.Null(w.WeeklyUsedPercent);
        Assert.Null(w.FiveHourWindowHours);
    }

    [Fact]
    public void TestCostNoteDisplayText()
    {
        var r = Load();
        r = r with { CostNote = "API-equivalent cost estimated from public API prices. Not actual subscription spend." };
        Assert.Equal(L10n.Tr("common.cost_note_default"), r.CostNoteDisplayText);

        r = r with { CostNote = "   Custom cost note   " };
        Assert.Equal("Custom cost note", r.CostNoteDisplayText);

        r = r with { CostNote = "" };
        Assert.Null(r.CostNoteDisplayText);

        r = r with { CostNote = "   \n\t  " };
        Assert.Null(r.CostNoteDisplayText);
    }

    [Fact]
    public void TestTopLevelInvariantHolds()
    {
        var rec = new Reconciliation(Load());
        Assert.True(rec.Cost.Ok, $"cost diff {rec.Cost.Diff}");
        Assert.True(rec.Tokens.Ok, $"token diff {rec.Tokens.Diff}");
        Assert.True(rec.Sessions.Ok, $"session diff {rec.Sessions.Diff}");
    }

    [Fact]
    public void TestProjectInvariants()
    {
        var r = Load();
        var costs = r.Projects.Select(p => p.Cost).ToArray();
        Assert.Equal(costs.OrderByDescending(c => c).ToArray(), costs);
        foreach (var p in r.Projects)
        {
            var t = p.Tokens;
            Assert.Equal(t.Input + t.Output + t.CacheRead + t.CacheWrite, t.Total);
            Assert.True(t.Thinking <= t.Output, p.Id);
            Assert.Equal(p.Cost, p.ByAgent.Sum(a => a.Cost), 2);
            Assert.Equal(p.Cost, p.ByModel.Sum(m => m.Cost), 2);
            Assert.Equal(p.Cost, p.ByDay.Sum(d => d.Cost), 2);
            Assert.Equal(p.Cost, p.SessionsDetail.Sum(s => s.Cost), 2);
            Assert.Equal(p.Tokens, p.ByAgent.Aggregate(Tokens.Zero, (acc, a) => acc + a.Tokens));
            Assert.Equal(t.Total, p.ByModel.Sum(m => m.Tokens.Total));
            Assert.Equal(t.Total, p.ByDay.Sum(d => d.Tokens));
            Assert.Equal(p.Sessions, p.SessionsDetail.Count);
            Assert.Equal(p.Sessions, p.ByAgent.Sum(a => a.Sessions));
            if (p.ByBranch.Count > 0) Assert.Equal(p.Cost, p.ByBranch.Sum(b => b.Cost), 2);
            var days = p.ByDay.Select(d => d.Day).ToArray();
            Assert.Equal(days.OrderBy(d => d, StringComparer.Ordinal).ToArray(), days);

            var agentKeys = p.ByAgent.Select(a => a.Agent).ToHashSet();
            foreach (var d in p.ByDay)
            {
                Assert.NotNull(d.ByAgent);
                Assert.Equal(d.Cost, d.ByAgent!.Values.Sum(), 2);
                Assert.True(d.ByAgent.Keys.All(agentKeys.Contains));

                Assert.NotNull(d.ByAgentTokens);
                Assert.Equal(d.Tokens, d.ByAgentTokens!.Values.Sum());
                Assert.Equal(d.ByAgentTokens.Keys.OrderBy(k => k).ToArray(), d.ByAgent.Keys.OrderBy(k => k).ToArray());
            }

            var starts = p.SessionsDetail.Select(s => s.StartedDate).ToList();
            Assert.All(starts, s => Assert.NotNull(s));
            Assert.Equal(starts.OrderByDescending(s => s).ToArray(), starts.ToArray());

            foreach (var s in p.SessionsDetail)
            {
                Assert.True(s.Share > 0 && s.Share <= 1, s.Id);
                if (s.Attribution == "split") Assert.True(s.Share < 1, s.Id);
            }
        }
    }

    [Fact]
    public void TestFixtureCoversRequiredCases()
    {
        var r = Load();
        var agents = r.Projects.SelectMany(p => p.ByAgent.Select(a => a.Agent)).ToHashSet();
        Assert.Equal(
            new HashSet<string> { "claude", "codex", "antigravity", "grok", "qwen", "commandcode", "minimax", "opencode", "copilot" },
            agents);
        Assert.Contains(r.Projects, p => p.ByAgent.Count == 1);
        Assert.Contains(r.Projects, p => p.PathMissing);
        Assert.Contains(r.Projects, p => p.Remote is null && p.Id.StartsWith("/", StringComparison.Ordinal));
        var attrs = r.Projects.SelectMany(p => p.SessionsDetail.Select(s => s.Attribution)).ToHashSet();
        Assert.Superset(new HashSet<string> { "dominant", "split", "cwd" }, attrs);
        Assert.Contains(r.Projects, p => p.ByModel.Any(m => m.Estimated));
        Assert.True(r.Buckets.Unattributed.Cost > 0);
        Assert.True(r.Buckets.Excluded.Cost > 0);
        Assert.True(r.Buckets.ParseFailed.Sessions > 0);
        Assert.All(r.Buckets.Unattributed.SessionsDetail, s => Assert.Equal(("none", 1.0), (s.Attribution, s.Share)));
        Assert.All(r.Buckets.Excluded.SessionsDetail, s => Assert.Equal(("excluded", 1.0), (s.Attribution, s.Share)));

        // 拆分会话：同一 id 出现在两个项目，share 之和为 1
        var shares = new Dictionary<string, double>(StringComparer.Ordinal);
        foreach (var p in r.Projects)
        {
            foreach (var s in p.SessionsDetail.Where(s => s.Attribution == "split"))
            {
                shares[s.Id] = shares.GetValueOrDefault(s.Id) + s.Share;
            }
        }
        Assert.NotEmpty(shares);
        foreach (var (id, sum) in shares) Assert.Equal(1, sum, 4);
    }

    // MARK: - 变体

    [Fact]
    public void TestSubscriptionsDecode()
    {
        var r = Load();
        var claude = r.Subscriptions!["claude"];
        Assert.Equal("max_5x", claude.Plan);
        Assert.Equal("Claude Max 5x", claude.PlanLabel);
        Assert.Equal(100, claude.MonthlyPriceUsd);
        Assert.Equal("2026-09-24T16:00:00Z", claude.CycleStart);
        Assert.Equal("2026-10-24T16:00:00Z", claude.CycleEnd);
        Assert.Equal(25, claude.AnchorDay);
        Assert.Equal("subscription_date", claude.CycleSource);
        Assert.False(claude.ExtraUsageEnabled);
        Assert.Equal("detected", claude.Source);

        var codex = r.Subscriptions["codex"];
        Assert.Equal("plus", codex.Plan);
        Assert.Equal("ChatGPT Plus", codex.PlanLabel);
        Assert.Equal(20, codex.MonthlyPriceUsd);
        Assert.Null(codex.AnchorDay);
        Assert.Equal("rolling_30d", codex.CycleSource);
        var generatedAt = ReportDates.ParseTimestamp(r.GeneratedAt)!.Value;
        var cycleStart = ReportDates.ParseTimestamp(codex.CycleStart)!.Value;
        Assert.Equal(TimeSpan.FromDays(30), generatedAt - cycleStart);
        Assert.Equal(r.GeneratedAt, codex.CycleEnd);
        Assert.Equal("detected", codex.Source);

        var grok = r.Subscriptions["grok"];
        Assert.Equal("supergrok", grok.Plan);
        Assert.Equal("SuperGrok", grok.PlanLabel);
        Assert.Equal(30, grok.MonthlyPriceUsd);
        Assert.Null(grok.AnchorDay);
        Assert.Equal("rolling_30d", grok.CycleSource);
        Assert.Equal("detected", grok.Source);

        var antigravity = r.Subscriptions["antigravity"];
        Assert.Equal("google_ai_pro", antigravity.Plan);
        Assert.Equal("Google AI Pro", antigravity.PlanLabel);
        Assert.Equal(19.99, antigravity.MonthlyPriceUsd);
        Assert.Null(antigravity.AnchorDay);
        Assert.Equal("rolling_30d", antigravity.CycleSource);
        Assert.Equal("detected", antigravity.Source);

        var copilot = r.Subscriptions["copilot"];
        Assert.Equal("pro", copilot.Plan);
        Assert.Equal("Copilot Pro", copilot.PlanLabel);
        Assert.Equal(10, copilot.MonthlyPriceUsd);
        Assert.Null(copilot.AnchorDay);
        Assert.Equal("rolling_30d", copilot.CycleSource);
        Assert.Equal("manual", copilot.Source);

        Assert.Null(r.Subscriptions.GetValueOrDefault("qwen"));
    }

    [Fact]
    public void TestMissingSubscriptionsDecodesAsNil()
    {
        var data = MutatedFixture(o => o.Remove("subscriptions"));
        Assert.Null(ReportDecoder.Decode(data).Subscriptions);
    }

    [Fact]
    public void TestNullSubscriptionsDecodesAsNil()
    {
        var data = MutatedFixture(o => o["subscriptions"] = null);
        Assert.Null(ReportDecoder.Decode(data).Subscriptions);
    }

    [Fact]
    public void TestNullMonthlyPriceDecodes()
    {
        var data = MutatedFixture(o =>
        {
            var subs = o["subscriptions"]!.AsObject();
            subs["claude"]!["monthly_price_usd"] = null;
        });
        var r = ReportDecoder.Decode(data);
        Assert.Null(r.Subscriptions!["claude"].MonthlyPriceUsd);
        Assert.Equal("Claude Max 5x", r.Subscriptions["claude"].PlanLabel);
        Assert.Null(SubscriptionValue.Multiplier(10, r.Subscriptions["claude"].MonthlyPriceUsd));
    }

    [Fact]
    public void TestSlimMobileSessionsDecode()
    {
        var slim = new JsonArray
        {
            new JsonObject
            {
                ["agent"] = "claude",
                ["started"] = "2026-10-12T09:30:00Z",
                ["ended"] = "2026-10-12T11:02:00Z",
                ["cost"] = 4.21,
                ["tokens"] = new JsonObject { ["total"] = 1234 },
                ["models"] = new JsonArray("claude-opus-5-5"),
            },
        };
        var data = MutatedFixture(o =>
        {
            var projects = o["projects"]!.AsArray();
            projects[0]!["sessions_detail"] = slim.DeepClone();
            var buckets = o["buckets"]!.AsObject();
            buckets["unattributed"]!["sessions_detail"] = slim.DeepClone();
        });
        var r = ReportDecoder.Decode(data);
        var s = r.Projects[0].SessionsDetail[0];
        Assert.Equal("claude@2026-10-12T09:30:00Z", s.Id);
        Assert.Equal("Claude Code", s.Label);
        Assert.Equal(1, s.Share);
        Assert.Equal("none", s.Attribution);
        Assert.Equal(0, s.Subagents);
        Assert.Equal(1234, s.Tokens.Total);
        Assert.Equal(0, s.Tokens.Input);
        Assert.Equal(["claude-opus-5-5"], s.Models.ToArray());
        Assert.Null(s.Cwd);
        Assert.Null(s.Branch);
        Assert.Null(s.Title);
        Assert.Null(s.ByDay);
        Assert.Equal(1234, r.Buckets.Unattributed.SessionsDetail[0].Tokens.Total);
    }

    [Fact]
    public void TestDayWithoutByAgentDecodesAsNil()
    {
        const string json = """[{"day": "2026-10-22", "cost": 3.2, "tokens": 120000},""" +
                            """{"day": "2026-10-23", "cost": 1, "tokens": 5, "by_agent": {"claude": 0.75, "codex": 0.25}}]""";
        using var doc = JsonDocument.Parse(json);
        var days = J.List(doc.RootElement, "", DayCost.Decode);
        Assert.Null(days[0].ByAgent);
        Assert.Equal(0.75, days[1].ByAgent!["claude"]);
        Assert.Equal(0.25, days[1].ByAgent!["codex"]);
    }

    [Fact]
    public void TestNewerSchemaStillDecodes()
    {
        var data = MutatedFixture(o => o["schema_version"] = 2);
        var r = ReportDecoder.Decode(data);
        Assert.True(r.IsNewerSchema);
    }

    [Fact]
    public void TestUnknownAgentKeyDecodes()
    {
        var data = MutatedFixture(o =>
        {
            var agents = o["projects"]!.AsArray()[0]!["by_agent"]!.AsArray();
            agents[0]!["agent"] = "gemini-cli";
            agents[0]!["label"] = "Gemini CLI";
        });
        var r = ReportDecoder.Decode(data);
        Assert.Equal("gemini-cli", r.Projects[0].ByAgent[0].Agent);
        Assert.Equal("Gemini CLI", r.Projects[0].ByAgent[0].Label);
    }

    [Fact]
    public void TestBrokenCostFailsReconciliation()
    {
        var data = MutatedFixture(o =>
        {
            var projects = o["projects"]!.AsArray();
            projects[0]!["cost"] = projects[0]!["cost"]!.GetValue<double>() + 1.5;
        });
        var rec = new Reconciliation(ReportDecoder.Decode(data));
        Assert.False(rec.Cost.Ok);
        Assert.Equal(-1.5, rec.Cost.Diff, 4);
    }

    [Fact]
    public void TestInvalidJsonThrowsReadableError()
    {
        var e = Assert.Throws<DataSourceError>(() => ReportDecoder.Decode("{\"schema_version\": 1,"));
        Assert.Equal(DataSourceErrorKind.InvalidJson, e.Kind);
        Assert.Contains("Not valid JSON", e.Message);
    }

    [Fact]
    public void TestMissingFieldNamesThePath()
    {
        var data = MutatedFixture(o =>
        {
            var projects = o["projects"]!.AsArray();
            projects[1]!.AsObject().Remove("by_day");
        });
        var e = Assert.Throws<DataSourceError>(() => ReportDecoder.Decode(data));
        Assert.Contains("projects[1].by_day", e.Message);
    }

    [Fact]
    public void TestEmptyInputIsReported()
    {
        var e = Assert.Throws<DataSourceError>(() => ReportDecoder.Decode("  \n"));
        Assert.Equal(DataSourceErrorKind.EmptyInput, e.Kind);
    }

    [Fact]
    public void TestFileDataSourceMissingFile()
    {
        var e = Assert.Throws<DataSourceError>(
            () => new FileDataSource("/nonexistent/kanjo.json").Load());
        Assert.Equal(DataSourceErrorKind.FileNotFound, e.Kind);
        Assert.Equal("Data file not found: /nonexistent/kanjo.json", e.Message);
    }

    [Fact]
    public void TestFileDataSourceReadsFixture()
    {
        var r = new FileDataSource(FixturePath).Load();
        Assert.Equal(1, r.SchemaVersion);
    }

    [Fact]
    public void TestDataOverrideArgument()
    {
        // ResolvePath makes the value absolute with the host's rules, so the
        // expectation is the host's spelling of the same path ("/" is a rooted
        // path on Windows too: it resolves against the current drive).
        Assert.Equal(Path.GetFullPath("/tmp/a.json"), DefaultPaths.DataOverride(
            ["x", "--data", "/tmp/a.json"], new Dictionary<string, string>()));
        Assert.Equal(Path.GetFullPath("/tmp/b.json"), DefaultPaths.DataOverride(
            ["x"], new Dictionary<string, string> { ["KANJO_DATA"] = "/tmp/b.json" }));
        Assert.Null(DefaultPaths.DataOverride(["x"], new Dictionary<string, string>()));

        // Absolute Windows paths are the normal case there and come back unchanged.
        var windowsAbsolute = Path.Combine(Path.GetTempPath(), "kanjo-data");
        Assert.Equal(windowsAbsolute, DefaultPaths.DataOverride(
            ["x", "--data", windowsAbsolute], new Dictionary<string, string>()));
    }

    [Fact]
    public void TestResolvedCliDirectoryFallsBackInOrder()
    {
        var root = TempDir();
        var home = Path.Combine(root, "home");
        var bundled = Path.Combine(root, "bundle", "cli");
        var repo = Path.Combine(root, "repo", "cli");
        var user = Path.Combine(root, "localappdata", "KanjoFamily", "cli");

        var candidates = new[] { bundled, repo, user };
        Assert.Null(DefaultPaths.ResolvedCliDirectory(candidates));

        // 只建目录不建 kanjo/ 包，不算。
        Directory.CreateDirectory(user);
        Assert.Null(DefaultPaths.ResolvedCliDirectory(candidates));

        Directory.CreateDirectory(Path.Combine(user, "kanjo"));
        File.WriteAllText(Path.Combine(user, "kanjo", "__init__.py"), "");
        Assert.Equal(user, DefaultPaths.ResolvedCliDirectory(candidates));

        Directory.CreateDirectory(Path.Combine(repo, "kanjo"));
        File.WriteAllText(Path.Combine(repo, "kanjo", "__init__.py"), "");
        Assert.Equal(repo, DefaultPaths.ResolvedCliDirectory(candidates));

        Directory.CreateDirectory(Path.Combine(bundled, "kanjo"));
        Assert.Equal(repo, DefaultPaths.ResolvedCliDirectory(candidates));

        File.WriteAllText(Path.Combine(bundled, "kanjo", "__init__.py"), "");
        Assert.Equal(bundled, DefaultPaths.ResolvedCliDirectory(candidates));
    }

    [Fact]
    public void TestRepoCliDirectoryIsFoundFromSource()
    {
        if (DefaultPaths.IsDebugBuild)
        {
            Assert.NotNull(DefaultPaths.RepoRoot);
            Assert.Equal(Path.Combine(DefaultPaths.RepoRoot!, "cli"), DefaultPaths.RepoCliDirectory);
            Assert.Equal(DefaultPaths.RepoCliDirectory, DefaultPaths.ResolvedCliDirectory());
        }
        else
        {
            Assert.Null(DefaultPaths.RepoRoot);
            Assert.Null(DefaultPaths.RepoCliDirectory);
        }
    }
}
