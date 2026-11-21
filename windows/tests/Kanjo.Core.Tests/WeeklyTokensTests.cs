using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>本周 token：周一边界、周日深夜、旧报告、空数据。日期全部写死。</summary>
public sealed class WeeklyTokensTests : KanjoTestCase
{
    private static readonly TimeZoneInfo Shanghai = TimeZoneInfo.FindSystemTimeZoneById(
        OperatingSystem.IsWindows() ? "China Standard Time" : "Asia/Shanghai");

    private static Project Project(string id, params (string Day, long Tokens)[] days) =>
        new(id, id, null, [], false, 0, Tokens.Zero, 0, null, null, [], [],
            days.Select(d => new DayCost(d.Day, 0, d.Tokens, null, null)).ToArray(), [], []);

    private static long Since(DateTimeOffset now, IReadOnlyList<Project> projects, TimeZoneInfo timeZone) =>
        WeeklyTokens.Since(now, projects, timeZone);

    /// <summary>上海时间 2026-10-19 00:00 整点翻周：前一秒仍算 10-12 那周。</summary>
    [Fact]
    public void TestMondayBoundary()
    {
        var projects = new[]
        {
            Project("a", ("2026-10-11", 1), ("2026-10-12", 10), ("2026-10-18", 20)),
            Project("b", ("2026-10-19", 40), ("2026-10-23", 7), ("nope", 100)),
        };
        var monday = Ts("2026-10-18T16:00:00Z");      // Mon Oct 19 00:00 CST
        var justBefore = Ts("2026-10-18T15:59:59Z");  // Sun Oct 18 23:59:59 CST
        Assert.Equal(47, Since(monday, projects, Shanghai));
        Assert.Equal(77, Since(justBefore, projects, Shanghai));
    }

    /// <summary>周日 23:59 仍属于上周一开的那周，不会从下一个周一开始。</summary>
    [Fact]
    public void TestSundayNight()
    {
        var projects = new[]
        {
            Project("a", ("2026-10-18", 5), ("2026-10-19", 7), ("2026-10-25", 11)),
        };
        var sundayNight = Ts("2026-10-25T23:59:59Z");
        Assert.Equal(18, Since(sundayNight, projects, TimeZoneInfo.Utc));
        Assert.Equal(DayOfWeek.Sunday, TimeZoneInfo.ConvertTime(sundayNight, TimeZoneInfo.Utc).DayOfWeek);
    }

    /// <summary>报告比墙钟旧：按生成时间那一周算，不按「现在」算成 0。</summary>
    [Fact]
    public void TestOldReportUsesGeneratedAt()
    {
        var now = Ts("2026-11-20T08:00:00Z");
        var generated = Ts("2026-10-23T02:00:00Z");
        var projects = new[]
        {
            Project("a",
                ("2026-10-18", 100),
                ("2026-10-20", 200),
                ("2026-10-23", 300)),
        };
        var reference = WeeklyTokens.Reference(now, generated);
        Assert.Equal(generated, reference);
        Assert.Equal(500, Since(reference, projects, TimeZoneInfo.Utc));
        // 同一份旧数据按墙钟（11 月）算是 0。
        Assert.Equal(0, Since(now, projects, TimeZoneInfo.Utc));
        Assert.Equal(now, WeeklyTokens.Reference(now, Ts("2026-11-21T00:00:00Z")));
        Assert.Equal(now, WeeklyTokens.Reference(now, null));
        Assert.Equal(now, WeeklyTokens.Reference(now, now));
    }

    [Fact]
    public void TestEmpty()
    {
        var now = Ts("2026-10-23T02:00:00Z");
        Assert.Equal(0, Since(now, [], TimeZoneInfo.Utc));
        Assert.Equal(0, Since(now, [Project("a")], TimeZoneInfo.Utc));
        Assert.Equal(0, Since(now, [Project("a", ("garbage", 50), ("2026-10-18", 9))], TimeZoneInfo.Utc));
    }

    /// <summary>三语都用 Mac 字符串表里已有的 overview.this_week_tokens，数字走紧凑 token 格式。</summary>
    [Fact]
    public void TestThisWeekLineUsesExistingTranslations()
    {
        Assert.Equal("This week: 12.3k tokens",
            L10n.TrL("en", "overview.this_week_tokens", Fmt.Tokens(12_345, "en")));
        Assert.Equal("本周：1.2万 token",
            L10n.TrL("zh-Hans", "overview.this_week_tokens", Fmt.Tokens(12_345, "zh-Hans")));
        Assert.Equal("Cette semaine : 12,3k jetons",
            L10n.TrL("fr", "overview.this_week_tokens", Fmt.Tokens(12_345, "fr")));
    }
}
