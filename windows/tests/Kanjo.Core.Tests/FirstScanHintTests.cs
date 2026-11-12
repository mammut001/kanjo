using Xunit;

namespace Kanjo.Core.Tests;

public sealed class FirstScanHintTests : KanjoTestCase
{
    [Fact]
    public void TestNoReportUnderThresholdReturnsFalse()
    {
        Assert.False(FirstScanHint.ShouldShow(false, 0.0));
        Assert.False(FirstScanHint.ShouldShow(false, 1.0));
        Assert.False(FirstScanHint.ShouldShow(false, 2.5));
        Assert.False(FirstScanHint.ShouldShow(false, 2.999));
        Assert.False(FirstScanHint.ShouldShow((UsageReport?)null, 2.999));
    }

    [Fact]
    public void TestNoReportAtOrAboveThresholdReturnsTrue()
    {
        Assert.True(FirstScanHint.ShouldShow(false, 3.0));
        Assert.True(FirstScanHint.ShouldShow(false, 3.001));
        Assert.True(FirstScanHint.ShouldShow(false, 5.0));
        Assert.True(FirstScanHint.ShouldShow(false, 12.0));
        Assert.True(FirstScanHint.ShouldShow(false, 30.0));
        Assert.True(FirstScanHint.ShouldShow((UsageReport?)null, 3.0));
        Assert.True(FirstScanHint.ShouldShow((UsageReport?)null, 12.0));
    }

    [Fact]
    public void TestReportPresentReturnsFalseRegardlessOfElapsed()
    {
        foreach (var elapsed in new[] { 0.0, 2.9, 3.0, 12.0, 30.0, 100.0 })
        {
            Assert.False(FirstScanHint.ShouldShow(true, elapsed));
        }
    }

    [Fact]
    public void TestReportOptionalOverload()
    {
        var report = LoadFixture();
        Assert.True(FirstScanHint.ShouldShow((UsageReport?)null, 3.0));
        Assert.False(FirstScanHint.ShouldShow((UsageReport?)null, 2.9));
        Assert.False(FirstScanHint.ShouldShow(report, 3.0));
        Assert.False(FirstScanHint.ShouldShow(report, 30.0));
    }

    [Fact]
    public void TestNegativeElapsedReturnsFalse()
    {
        Assert.False(FirstScanHint.ShouldShow(false, -0.5));
        Assert.False(FirstScanHint.ShouldShow(false, -5.0));
    }

    [Fact]
    public void TestAliasesAndAlternativeSignatures()
    {
        Assert.True(FirstScanHint.ShouldShowHint(false, TimeSpan.FromSeconds(3)));
        Assert.False(FirstScanHint.ShouldShowHint(true, TimeSpan.FromSeconds(3)));
        Assert.True(FirstScanHint.ShouldShow(false, TimeSpan.FromSeconds(3)));
        Assert.False(FirstScanHint.ShouldShow(true, TimeSpan.FromSeconds(3)));
    }

    [Fact]
    public void TestExplanationLocalization()
    {
        Assert.Equal(
            "首次运行要读取所有 AI 工具的日志，大约需要半分钟；之后每次刷新只要几秒。",
            FirstScanHint.Explanation("zh-Hans"));
        Assert.Equal(
            "First run reads every AI tool's logs and takes about half a minute; later refreshes take a few seconds.",
            FirstScanHint.Explanation("en"));
        Assert.Equal(
            "Le premier lancement lit les journaux de tous les outils IA (environ 30 s) ; ensuite, quelques secondes.",
            FirstScanHint.Explanation("fr"));
    }

    [Fact]
    public void TestElapsedFormatting()
    {
        Assert.Equal("已用 12 秒", FirstScanHint.ElapsedText(12, "zh-Hans"));
        Assert.Equal("12 s elapsed", FirstScanHint.ElapsedText(12, "en"));
        Assert.Equal("12 s écoulées", FirstScanHint.ElapsedText(12, "fr"));

        Assert.Equal("已用 3 秒", FirstScanHint.ElapsedText(3, "zh-Hans"));
        Assert.Equal("3 s elapsed", FirstScanHint.ElapsedText(3, "en"));
        Assert.Equal("3 s écoulées", FirstScanHint.ElapsedText(3, "fr"));

        Assert.Equal("12 s elapsed", FirstScanHint.ElapsedText(TimeSpan.FromSeconds(12.8), "en"));
        Assert.Equal("已用 12 秒", FirstScanHint.ElapsedText(TimeSpan.FromSeconds(12.8), "zh-Hans"));
        Assert.Equal("12 s écoulées", FirstScanHint.ElapsedText(TimeSpan.FromSeconds(12.8), "fr"));
    }
}
