using Xunit;

namespace Kanjo.Core.Tests;

public sealed class TrayTooltipTests : KanjoTestCase
{
    [Fact]
    public void TestTooltipIncludesAmountAndRangeSuffix()
    {
        Assert.Equal("Kanjo · $3,057",
            TrayTooltip.Build(true, false, true, MenuBarMode.Cost, 3056.88, 1_000, "USD", TimeRange.All));
        Assert.Equal("Kanjo · $3,057 · 30d",
            TrayTooltip.Build(true, false, true, MenuBarMode.Cost, 3056.88, 1_000, "USD", TimeRange.Days30));
        Assert.Equal("Kanjo · 23.5B · 30d",
            TrayTooltip.Build(true, false, true, MenuBarMode.Tokens, 3056.88, 23_500_000_000, "USD", TimeRange.Days30));
        Assert.Equal("Kanjo · $3,057",
            TrayTooltip.Build(true, false, true, MenuBarMode.Cost, 3056.88, 1_000, "USD", TimeRange.SinceReset));
    }

    [Fact]
    public void TestTooltipWithoutAmount()
    {
        Assert.Equal("Kanjo", TrayTooltip.Build(true, false, false, MenuBarMode.Cost, 3056.88, 1_000, "USD", TimeRange.All));
        Assert.Equal("Kanjo", TrayTooltip.Build(false, false, true, MenuBarMode.Cost, 0, 0, "USD", TimeRange.All));
    }

    [Fact]
    public void TestErrorStateShowsPlaceholder()
    {
        Assert.Equal("Kanjo · $—", TrayTooltip.Build(false, true, true, MenuBarMode.Cost, 0, 0, "USD", TimeRange.All));
        Assert.Equal("Kanjo · —", TrayTooltip.Build(false, true, true, MenuBarMode.Tokens, 0, 0, "USD", TimeRange.All));
        Assert.Equal("Kanjo", TrayTooltip.Build(false, true, false, MenuBarMode.Cost, 0, 0, "USD", TimeRange.All));
        // 出错但还有旧数据：仍显示金额
        Assert.Equal("Kanjo · $12.34", TrayTooltip.Build(true, true, true, MenuBarMode.Cost, 12.34, 10, "USD", TimeRange.All));
    }

    [Fact]
    public void TestStatus()
    {
        Assert.Equal(TrayStatus.Loading, TrayTooltip.Status(false, false));
        Assert.Equal(TrayStatus.Normal, TrayTooltip.Status(true, false));
        Assert.Equal(TrayStatus.Error, TrayTooltip.Status(false, true));
        Assert.Equal(TrayStatus.Error, TrayTooltip.Status(true, true));
    }
}
