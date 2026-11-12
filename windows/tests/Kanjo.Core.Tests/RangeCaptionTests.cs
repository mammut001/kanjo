using Xunit;

namespace Kanjo.Core.Tests;

public sealed class RangeCaptionTests : KanjoTestCase
{
    private static readonly TimeZoneInfo Shanghai = TimeZoneInfo.FindSystemTimeZoneById(
        OperatingSystem.IsWindows() ? "China Standard Time" : "Asia/Shanghai");

    private static DateTimeOffset Ts2(string s) => Ts(s);

    private static readonly Dictionary<string, string> Labels = new(StringComparer.Ordinal)
    {
        ["claude"] = "Claude Code",
        ["codex"] = "Codex CLI",
        ["grok"] = "Grok CLI",
        ["copilot"] = "Copilot CLI",
        ["minimax"] = "MiniMax",
        ["qwen"] = "Qwen Code",
        ["commandcode"] = "Command Code",
        ["opencode"] = "OpenCode",
        ["antigravity"] = "Antigravity CLI",
    };

    [Fact]
    public void TestShortName()
    {
        Assert.Equal("Claude", RangeCaptionBuilder.ShortName("claude", Labels));
        Assert.Equal("Copilot", RangeCaptionBuilder.ShortName("copilot", Labels));
        Assert.Equal("Command", RangeCaptionBuilder.ShortName("commandcode", Labels));
        Assert.Equal("MiniMax", RangeCaptionBuilder.ShortName("minimax", Labels));
        Assert.Equal("Unknown_Agent", RangeCaptionBuilder.ShortName("unknown_agent", Labels));
    }

    [Fact]
    public void TestAgentOrder()
    {
        var report = LoadFixture();
        Assert.Equal(
            ["claude", "codex", "grok", "antigravity", "copilot", "commandcode", "qwen", "minimax", "opencode"],
            RangeCaptionBuilder.AgentOrder(report).ToArray());

        // 加一个只在 quota_windows / subscriptions 里出现的 agent
        var quota = new Dictionary<string, QuotaWindow>(report.QuotaWindows!)
        {
            ["future_bot"] = new("2026-10-27T00:00:00Z", 168, null, null, null, null, "manual", null),
        };
        var subs = new Dictionary<string, Subscription>(report.Subscriptions!)
        {
            ["extra_agent"] = new("pro", "Extra Agent", 10, "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", 1,
                "manual", false, "manual", null),
        };
        var updated = report with { QuotaWindows = quota, Subscriptions = subs };
        Assert.Equal(
            ["claude", "codex", "grok", "antigravity", "copilot", "commandcode", "qwen", "minimax", "opencode",
             "extra_agent", "future_bot"],
            RangeCaptionBuilder.AgentOrder(updated).ToArray());
    }

    [Fact]
    public void TestAllRangeReturnsNil()
    {
        var spec = new RangeSpec(TimeRange.All, Shanghai, null, null, new Dictionary<string, DateTimeOffset>());
        Assert.Null(RangeCaptionBuilder.Caption(TimeRange.All, spec, ["claude"]));
    }

    [Fact]
    public void TestFixedRangesReturnNil()
    {
        var start = Ts2("2026-10-24T00:00:00Z");
        var end = Ts2("2026-10-25T00:00:00Z");
        var today = new RangeSpec(TimeRange.Today, Shanghai, start, end, new Dictionary<string, DateTimeOffset>());
        Assert.Null(RangeCaptionBuilder.Caption(TimeRange.Today, today, ["claude"], language: "en"));

        var d7 = new RangeSpec(TimeRange.Days7, Shanghai, Ts2("2026-10-18T00:00:00Z"), end, new Dictionary<string, DateTimeOffset>());
        Assert.Null(RangeCaptionBuilder.Caption(TimeRange.Days7, d7, ["claude"], language: "en"));

        var d30 = new RangeSpec(TimeRange.Days30, Shanghai, Ts2("2026-09-25T00:00:00Z"), end, new Dictionary<string, DateTimeOffset>());
        Assert.Null(RangeCaptionBuilder.Caption(TimeRange.Days30, d30, ["claude"], language: "en"));

        var lastWeek = new RangeSpec(TimeRange.LastWeek, Shanghai, Ts2("2026-10-12T00:00:00Z"),
            Ts2("2026-10-19T00:00:00Z"), new Dictionary<string, DateTimeOffset>());
        Assert.Null(RangeCaptionBuilder.Caption(TimeRange.LastWeek, lastWeek, ["claude"], language: "en"));
    }

    private static RangeSpec SinceResetSpec(Dictionary<string, DateTimeOffset> starts) =>
        new(TimeRange.SinceReset, Shanghai, null, null, starts);

    [Fact]
    public void TestSinceResetAllHaveReset()
    {
        var agentOrder = new[] { "claude", "codex", "grok" };
        var starts = new Dictionary<string, DateTimeOffset>
        {
            ["claude"] = Ts2("2026-10-20T10:00:00Z"),
            ["codex"] = Ts2("2026-10-26T02:10:00Z"),
            ["grok"] = Ts2("2026-10-20T05:29:00Z"),
        };
        var result = RangeCaptionBuilder.Caption(TimeRange.SinceReset, SinceResetSpec(starts), agentOrder, Labels, language: "en");
        Assert.NotNull(result);
        Assert.Contains("Since Claude reset", result!.Text);
        Assert.Contains("Codex reset", result.Text);
        Assert.Contains("Grok reset", result.Text);
        Assert.DoesNotContain("others", result.Text);
        Assert.DoesNotContain("no reset info", result.Text);
        Assert.Null(result.Help);
    }

    [Fact]
    public void TestSinceResetOneMissing()
    {
        var agentOrder = new[] { "claude", "codex", "grok", "copilot" };
        var starts = new Dictionary<string, DateTimeOffset>
        {
            ["claude"] = Ts2("2026-10-20T10:00:00Z"),
            ["codex"] = Ts2("2026-10-26T02:10:00Z"),
            ["grok"] = Ts2("2026-10-20T05:29:00Z"),
        };
        var result = RangeCaptionBuilder.Caption(TimeRange.SinceReset, SinceResetSpec(starts), agentOrder, Labels, language: "en");
        Assert.NotNull(result);
        Assert.Contains("Since Claude reset", result!.Text);
        Assert.Contains("Codex reset", result.Text);
        Assert.Contains("Grok reset", result.Text);
        Assert.EndsWith("Copilot: no reset info", result.Text);
        Assert.DoesNotContain("others", result.Text);
        Assert.Null(result.Help);
    }

    private static readonly string[] ManyAgents =
        ["claude", "codex", "grok", "copilot", "minimax", "qwen", "commandcode", "opencode", "antigravity"];

    private static RangeSpec ThreeStarts() => SinceResetSpec(new Dictionary<string, DateTimeOffset>
    {
        ["claude"] = Ts2("2026-10-20T10:00:00Z"),
        ["codex"] = Ts2("2026-10-26T02:10:00Z"),
        ["grok"] = Ts2("2026-10-20T05:29:00Z"),
    });

    [Fact]
    public void TestSinceResetMultipleMissingEnglish()
    {
        var result = RangeCaptionBuilder.Caption(TimeRange.SinceReset, ThreeStarts(), ManyAgents, Labels, language: "en");
        Assert.NotNull(result);
        Assert.Contains("Since Claude reset", result!.Text);
        Assert.Contains("Codex reset", result.Text);
        Assert.Contains("Grok reset", result.Text);
        Assert.EndsWith("6 others have no reset info (not counted)", result.Text);
        Assert.Equal("Copilot, MiniMax, Qwen, Command, OpenCode, Antigravity", result.Help);
    }

    [Fact]
    public void TestSinceResetMultipleMissingChineseAndFrench()
    {
        var zh = RangeCaptionBuilder.Caption(TimeRange.SinceReset, ThreeStarts(), ManyAgents, Labels, language: "zh-Hans");
        Assert.NotNull(zh);
        Assert.Contains("自 Claude 重置", zh!.Text);
        Assert.EndsWith("其余 6 个无重置信息（不计入）", zh.Text);
        Assert.Equal("Copilot, MiniMax, Qwen, Command, OpenCode, Antigravity", zh.Help);

        var fr = RangeCaptionBuilder.Caption(TimeRange.SinceReset, ThreeStarts(), ManyAgents, Labels, language: "fr");
        Assert.NotNull(fr);
        Assert.Contains("Depuis réinit. Claude", fr!.Text);
        Assert.EndsWith("6 autres sans info de réinitialisation (non comptés)", fr.Text);
        Assert.Equal("Copilot, MiniMax, Qwen, Command, OpenCode, Antigravity", fr.Help);
    }

    private static Dictionary<string, Subscription> ClaudeAndCodexSubs() => new(StringComparer.Ordinal)
    {
        ["claude"] = new("max_5x", "Claude Max 5x", 100, "2026-10-25T00:00:00Z", "2026-11-25T00:00:00Z", 25,
            "manual", false, "manual", null),
        ["codex"] = new("plus", "ChatGPT Plus", 20, "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z", 1,
            "manual", false, "manual", null),
    };

    private static RangeSpec CycleSpec(Dictionary<string, DateTimeOffset> starts) =>
        new(TimeRange.BillingCycle, Shanghai, null, null, starts);

    [Fact]
    public void TestBillingCycleAllHaveSubscription()
    {
        var starts = new Dictionary<string, DateTimeOffset>
        {
            ["claude"] = Ts2("2026-10-25T00:00:00Z"),
            ["codex"] = Ts2("2026-11-01T00:00:00Z"),
        };
        var result = RangeCaptionBuilder.Caption(TimeRange.BillingCycle, CycleSpec(starts),
            ["claude", "codex"], Labels, ClaudeAndCodexSubs(), language: "en");
        Assert.NotNull(result);
        Assert.StartsWith("Billing cycle · ", result!.Text);
        Assert.Contains("Claude Max 5x since", result.Text);
        Assert.Contains("ChatGPT Plus since", result.Text);
        Assert.DoesNotContain("others", result.Text);
        Assert.DoesNotContain("no subscription", result.Text);
        Assert.Null(result.Help);
    }

    [Fact]
    public void TestBillingCycleOneMissing()
    {
        var starts = new Dictionary<string, DateTimeOffset> { ["claude"] = Ts2("2026-10-25T00:00:00Z") };
        var result = RangeCaptionBuilder.Caption(TimeRange.BillingCycle, CycleSpec(starts),
            ["claude", "copilot"], Labels, ClaudeAndCodexSubs(), language: "en");
        Assert.NotNull(result);
        Assert.StartsWith("Billing cycle · ", result!.Text);
        Assert.Contains("Claude Max 5x since", result.Text);
        Assert.EndsWith("Copilot: no subscription", result.Text);
        Assert.DoesNotContain("others", result.Text);
        Assert.Null(result.Help);
    }

    [Fact]
    public void TestBillingCycleMultipleMissing()
    {
        var starts = new Dictionary<string, DateTimeOffset> { ["claude"] = Ts2("2026-10-25T00:00:00Z") };
        var spec = CycleSpec(starts);
        var order = new[] { "claude", "copilot", "minimax", "antigravity" };
        var subs = ClaudeAndCodexSubs();

        var en = RangeCaptionBuilder.Caption(TimeRange.BillingCycle, spec, order, Labels, subs, language: "en");
        Assert.NotNull(en);
        Assert.StartsWith("Billing cycle · ", en!.Text);
        Assert.EndsWith("3 others have no subscription (not counted)", en.Text);
        Assert.Equal("Copilot, MiniMax, Antigravity", en.Help);

        var zh = RangeCaptionBuilder.Caption(TimeRange.BillingCycle, spec, order, Labels, subs, language: "zh-Hans");
        Assert.NotNull(zh);
        Assert.StartsWith("账单周期 · ", zh!.Text);
        Assert.EndsWith("其余 3 个无订阅（不计入）", zh.Text);
        Assert.Equal("Copilot, MiniMax, Antigravity", zh.Help);

        var fr = RangeCaptionBuilder.Caption(TimeRange.BillingCycle, spec, order, Labels, subs, language: "fr");
        Assert.NotNull(fr);
        Assert.StartsWith("Cycle de facturation · ", fr!.Text);
        Assert.EndsWith("3 autres sans abonnement (non comptés)", fr.Text);
        Assert.Equal("Copilot, MiniMax, Antigravity", fr.Help);
    }

    [Fact]
    public void TestCaptionFromReportMatchesSpecOverload()
    {
        var report = LoadFixture();
        var now = Ts("2026-10-23T02:00:00Z");
        var direct = RangeCaptionBuilder.Caption(TimeRange.BillingCycle, report, now, "en");
        var spec = RangeEngine.Spec(TimeRange.BillingCycle, report, now);
        var viaSpec = RangeCaptionBuilder.Caption(TimeRange.BillingCycle, spec,
            RangeCaptionBuilder.AgentOrder(report), report.AgentLabels(), report.Subscriptions, "en");
        Assert.Equal(viaSpec, direct);
        Assert.Null(RangeCaptionBuilder.Caption(TimeRange.Days7, report, now, "en"));
    }
}
