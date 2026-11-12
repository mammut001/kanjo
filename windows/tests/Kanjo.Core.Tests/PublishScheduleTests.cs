using Xunit;

namespace Kanjo.Core.Tests;

public sealed class PublishScheduleTests : KanjoTestCase
{
    private const string DummyRepo = "/Users/test/Documents/GitHub/resume";

    private static DateTimeOffset At(long seconds) => DateTimeOffset.FromUnixTimeSeconds(seconds);

    [Fact]
    public void TestDisabledState()
    {
        Assert.False(PublishSchedule.ShouldPublish(false, DummyRepo, PublishFrequency.Daily, null, null));
    }

    [Fact]
    public void TestEmptyRepoPath()
    {
        Assert.False(PublishSchedule.ShouldPublish(true, "", PublishFrequency.Daily, null, null));
        Assert.False(PublishSchedule.ShouldPublish(true, "   \t\n", PublishFrequency.Daily, null, null));
    }

    [Fact]
    public void TestFirstTimePublish()
    {
        var now = At(1_700_000_000);
        Assert.True(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Daily, null, null, now));
    }

    [Fact]
    public void TestFailureBackoff()
    {
        var now = At(1_700_000_000);
        var attemptRecent = now.AddSeconds(-1800);
        Assert.False(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Daily, null, attemptRecent, now));

        var attemptOld = now.AddSeconds(-3900);
        Assert.True(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Daily, null, attemptOld, now));

        var lastSuccess = now.AddSeconds(-3 * 86400);
        Assert.False(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Daily, lastSuccess, attemptRecent, now));
    }

    [Fact]
    public void TestDailyFrequency()
    {
        var now = At(1_700_000_000);
        var success23h = now.AddSeconds(-23 * 3600);
        Assert.False(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Daily, success23h, success23h, now));

        var success25h = now.AddSeconds(-25 * 3600);
        Assert.True(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Daily, success25h, success25h, now));
    }

    [Fact]
    public void TestWeeklyFrequency()
    {
        var now = At(1_700_000_000);
        var success6d = now.AddSeconds(-6 * 86400);
        Assert.False(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Weekly, success6d, success6d, now));

        var success7_5d = now.AddSeconds((long)(-7.5 * 86400));
        Assert.True(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Weekly, success7_5d, success7_5d, now));
    }

    [Fact]
    public void TestMonthlyFrequency()
    {
        var tz = TimeZoneInfo.Utc;
        DateTimeOffset D(int year, int month, int day, int hour = 0, int minute = 0) =>
            new(year, month, day, hour, minute, 0, TimeSpan.Zero);

        var oct15 = D(2026, 10, 15, 12);
        var oct31 = D(2026, 10, 31, 23, 59);
        var nov01 = D(2026, 11, 1, 0, 1);
        var nov20 = D(2026, 11, 20, 12);

        Assert.False(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Monthly, oct15, oct15, oct31, tz));
        Assert.True(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Monthly, oct31, oct31, nov01, tz));
        Assert.False(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Monthly, nov01, nov01, nov20, tz));

        var dec31 = D(2025, 12, 31, 18);
        var jan01 = D(2026, 1, 1, 9);
        Assert.True(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Monthly, dec31, dec31, jan01, tz));
    }

    [Fact]
    public void TestMonthlyFrequencyRespectsReportTimezone()
    {
        var utc = TimeZoneInfo.Utc;
        var toronto = TimeZoneInfo.FindSystemTimeZoneById(
            OperatingSystem.IsWindows() ? "Eastern Standard Time" : "America/Toronto");

        // 2026-11-01 02:00:00 UTC：UTC 是 11 月，多伦多还是 10 月 31 日 22:00。
        var exactNov1At2am = new DateTimeOffset(2026, 11, 1, 2, 0, 0, TimeSpan.Zero);
        var lastOct10 = new DateTimeOffset(2026, 10, 10, 10, 0, 0, TimeSpan.Zero);

        Assert.True(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Monthly,
            lastOct10, lastOct10, exactNov1At2am, utc));
        Assert.False(PublishSchedule.ShouldPublish(true, DummyRepo, PublishFrequency.Monthly,
            lastOct10, lastOct10, exactNov1At2am, toronto));
    }

    [Fact]
    public void TestPublishCommandConstruction()
    {
        var cmd = PublishCommand.Command("python.exe -m kanjo export", "/path/to/my repo",
            "src/data/token-usage.json", "main");
        Assert.Contains("publish-usage", cmd);
        Assert.Contains("--repo '/path/to/my repo'", cmd);
        Assert.Contains("--file src/data/token-usage.json", cmd);
        Assert.Contains("--branch main", cmd);
    }
}
