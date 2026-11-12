using Xunit;

namespace Kanjo.Core.Tests;

public sealed class SyncFingerprintTests : KanjoTestCase
{
    [Fact]
    public void TestFingerprintIsStableAndTracksTotals()
    {
        var report = LoadFixture();
        var baseValue = SyncFingerprint.Make(report);
        Assert.Equal(baseValue, SyncFingerprint.Make(report));

        var costChanged = report with { Totals = report.Totals with { Cost = report.Totals.Cost + 0.01 } };
        Assert.NotEqual(baseValue, SyncFingerprint.Make(costChanged));

        var tokensChanged = report with
        {
            Totals = report.Totals with { Tokens = report.Totals.Tokens with { Total = report.Totals.Tokens.Total + 1 } },
        };
        Assert.NotEqual(baseValue, SyncFingerprint.Make(tokensChanged));

        var sessionsChanged = report with { Totals = report.Totals with { Sessions = report.Totals.Sessions + 1 } };
        Assert.NotEqual(baseValue, SyncFingerprint.Make(sessionsChanged));
    }

    [Fact]
    public void TestFingerprintTracksQuotaAndRounds()
    {
        var report = LoadFixture();
        var quota = new Dictionary<string, QuotaWindow>(report.QuotaWindows!)
        {
            ["claude"] = report.QuotaWindows!["claude"] with { WeeklyUsedPercent = 57 },
        };
        var withQuota = report with
        {
            Totals = report.Totals with { Cost = 10 },
            QuotaWindows = quota,
        };
        var baseValue = SyncFingerprint.Make(withQuota);

        var rounded = withQuota with
        {
            QuotaWindows = new Dictionary<string, QuotaWindow>(quota)
            {
                ["claude"] = quota["claude"] with { WeeklyUsedPercent = 57.4 },
            },
        };
        Assert.Equal(baseValue, SyncFingerprint.Make(rounded));

        var changed = withQuota with
        {
            QuotaWindows = new Dictionary<string, QuotaWindow>(quota)
            {
                ["claude"] = quota["claude"] with { WeeklyUsedPercent = 58 },
            },
        };
        Assert.NotEqual(baseValue, SyncFingerprint.Make(changed));

        var costRounded = report with { Totals = report.Totals with { Cost = 10.004 } };
        Assert.Equal(baseValue, SyncFingerprint.Make(costRounded));
    }
}
