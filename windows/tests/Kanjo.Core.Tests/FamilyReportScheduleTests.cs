using Xunit;

namespace Kanjo.Core.Tests;

public sealed class FamilyReportScheduleTests : KanjoTestCase
{
    private const string DummyUrl = "https://usage.example.com";

    private static DateTimeOffset At(long seconds) => DateTimeOffset.FromUnixTimeSeconds(seconds);

    [Fact]
    public void TestDisabledState()
    {
        Assert.False(FamilyReportSchedule.ShouldReport(false, true, DummyUrl, null, null));
    }

    [Fact]
    public void TestMissingToken()
    {
        Assert.False(FamilyReportSchedule.ShouldReport(true, false, DummyUrl, null, null));
    }

    [Fact]
    public void TestUrlValidation()
    {
        Assert.True(FamilyReportSchedule.IsValidUrl("https://usage.example.com"));
        Assert.True(FamilyReportSchedule.IsValidUrl("https://example.com/api"));
        Assert.True(FamilyReportSchedule.IsValidUrl("http://127.0.0.1:8788"));
        Assert.True(FamilyReportSchedule.IsValidUrl("http://localhost:8788"));

        Assert.False(FamilyReportSchedule.IsValidUrl(""));
        Assert.False(FamilyReportSchedule.IsValidUrl("   "));
        Assert.False(FamilyReportSchedule.IsValidUrl("http://usage.example.com"));
        Assert.False(FamilyReportSchedule.IsValidUrl("ftp://127.0.0.1"));
        Assert.False(FamilyReportSchedule.IsValidUrl("not-a-url"));

        Assert.False(FamilyReportSchedule.ShouldReport(true, true, "http://insecure.example.com", null, null));
    }

    [Fact]
    public void TestNoNetwork()
    {
        Assert.False(FamilyReportSchedule.ShouldReport(true, true, DummyUrl, null, null, noNetwork: true));
    }

    [Fact]
    public void TestFirstTimeReport()
    {
        Assert.True(FamilyReportSchedule.ShouldReport(true, true, DummyUrl, null, null, At(1_700_000_000)));
    }

    [Fact]
    public void TestFailureBackoff()
    {
        var now = At(1_700_000_000);
        var attemptRecent = now.AddSeconds(-600);
        Assert.False(FamilyReportSchedule.ShouldReport(true, true, DummyUrl, null, attemptRecent, now));

        var attemptOld = now.AddSeconds(-2100);
        Assert.True(FamilyReportSchedule.ShouldReport(true, true, DummyUrl, null, attemptOld, now));

        var lastSuccess = now.AddSeconds(-3600);
        Assert.False(FamilyReportSchedule.ShouldReport(true, true, DummyUrl, lastSuccess, attemptRecent, now));
        Assert.True(FamilyReportSchedule.ShouldReport(true, true, DummyUrl, lastSuccess, attemptOld, now));
    }

    [Fact]
    public void TestSuccessInterval()
    {
        var now = At(1_700_000_000);
        var success10m = now.AddSeconds(-600);
        Assert.False(FamilyReportSchedule.ShouldReport(true, true, DummyUrl, success10m, success10m, now));

        var success16m = now.AddSeconds(-960);
        Assert.True(FamilyReportSchedule.ShouldReport(true, true, DummyUrl, success16m, success16m, now));
    }

    [Fact]
    public void TestClockSkew()
    {
        var now = At(1_700_000_000);
        Assert.False(FamilyReportSchedule.ShouldReport(true, true, DummyUrl, now.AddSeconds(3600), null, now));
    }

    [Fact]
    public void TestCommandConstruction()
    {
        var withLabel = FamilyReportCommand.Command("python.exe -m kanjo export", DummyUrl, "Alice (MacBook)");
        Assert.Equal("python.exe -m kanjo report-family --url https://usage.example.com --member-label 'Alice (MacBook)'",
            withLabel);

        var withoutLabel = FamilyReportCommand.Command("python.exe -m kanjo export", DummyUrl, null);
        Assert.Equal("python.exe -m kanjo report-family --url https://usage.example.com", withoutLabel);

        // 令牌永远不会出现在命令里
        Assert.DoesNotContain("token", withLabel, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("token", withoutLabel, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void TestFamilyReportStatusCalculation()
    {
        Assert.Equal(FamilyReportStatusStateKind.NoServer,
            FamilyReportStatus.State("", true, false, null, null, false).Kind);
        Assert.Equal(L10n.Tr("settings.family.status.no_server"),
            FamilyReportStatus.Text("", true, false, null, null, false));
        Assert.Equal(FamilyReportStatusStateKind.NoServer,
            FamilyReportStatus.State("invalid-url", true, false, null, null, false).Kind);
        Assert.Equal(FamilyReportStatusStateKind.MissingToken,
            FamilyReportStatus.State(DummyUrl, false, false, null, null, false).Kind);
        Assert.Equal(FamilyReportStatusStateKind.Never,
            FamilyReportStatus.State(DummyUrl, true, false, null, null, false).Kind);
        Assert.Equal(FamilyReportStatusStateKind.InProgress,
            FamilyReportStatus.State(DummyUrl, true, true, null, null, false).Kind);
        Assert.Equal(FamilyReportStatusStateKind.NoNetwork,
            FamilyReportStatus.State(DummyUrl, true, false, null, null, true).Kind);
        Assert.Equal(FamilyReportStatusStateKind.Failed,
            FamilyReportStatus.State(DummyUrl, true, false, "boom", null, false).Kind);
    }

    [Fact]
    public void TestEmptyOrInvalidUrlNoReport()
    {
        Assert.False(FamilyReportSchedule.ShouldReport(true, true, "", null, null));
        Assert.False(FamilyReportSchedule.ShouldReport(true, true, "   ", null, null));
        Assert.False(FamilyReportSchedule.ShouldReport(true, true, "http://remote.example.com", null, null));
    }
}
