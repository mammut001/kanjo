using Xunit;

namespace Kanjo.Core.Tests;

public sealed class FormattingTests : KanjoTestCase
{
    [Fact]
    public void TestMoney()
    {
        Assert.Equal("$0.00", Fmt.Money(0));
        Assert.Equal("<$0.01", Fmt.Money(0.0013));
        Assert.Equal("<$0.01", Fmt.Money(0.009999));
        Assert.Equal("$0.01", Fmt.Money(0.01));
        Assert.Equal("$12.35", Fmt.Money(12.345));
        Assert.Equal("$1,234.50", Fmt.Money(1234.5));
        Assert.Equal("-$1.50", Fmt.Money(-1.5));
        Assert.Equal("EUR 3.00", Fmt.Money(3, "EUR"));
    }

    [Fact]
    public void TestMenuBarMoney()
    {
        // < 100：两位小数，保留 <$0.01
        Assert.Equal("<$0.01", Fmt.MenuBarMoney(0.004));
        Assert.Equal("$12.35", Fmt.MenuBarMoney(12.345));
        Assert.Equal("$99.99", Fmt.MenuBarMoney(99.99));

        // 100 ..< 10,000：无小数，千分位分组
        Assert.Equal("$100", Fmt.MenuBarMoney(100));
        Assert.Equal("$3,057", Fmt.MenuBarMoney(3056.88));

        // >= 10,000：紧凑 K/M 一位小数，去尾部 .0
        Assert.Equal("$10K", Fmt.MenuBarMoney(9999.6));
        Assert.Equal("$10K", Fmt.MenuBarMoney(10000));
        Assert.Equal("$12.3K", Fmt.MenuBarMoney(12345));
        Assert.Equal("$1.2M", Fmt.MenuBarMoney(1_234_567));

        // 负数：保持前导 -
        Assert.Equal("-<$0.01", Fmt.MenuBarMoney(-0.004));
        Assert.Equal("-$12.35", Fmt.MenuBarMoney(-12.345));
        Assert.Equal("-$3,057", Fmt.MenuBarMoney(-3056.88));
        Assert.Equal("-$12.3K", Fmt.MenuBarMoney(-12345));

        // 非 USD
        Assert.Equal("EUR 12.35", Fmt.MenuBarMoney(12.345, "EUR"));
        Assert.Equal("EUR 3,057", Fmt.MenuBarMoney(3056.88, "EUR"));
        Assert.Equal("EUR 12.3K", Fmt.MenuBarMoney(12345, "EUR"));
        Assert.Equal("-EUR 3,057", Fmt.MenuBarMoney(-3056.88, "EUR"));
    }

    [Fact]
    public void TestMenuBarText()
    {
        // 金额模式：固定窗口有后缀，其余无后缀
        Assert.Equal("$3,057", MenuBarText.Make(3056.88, "USD", TimeRange.All));
        Assert.Equal($"$3,057 · {TimeRange.Today.MenuBarSuffix()}", MenuBarText.Make(3056.88, "USD", TimeRange.Today));
        Assert.Equal($"$3,057 · {TimeRange.Days7.ShortLabel()}", MenuBarText.Make(3056.88, "USD", TimeRange.Days7));
        Assert.Equal($"$3,057 · {TimeRange.Days30.ShortLabel()}", MenuBarText.Make(3056.88, "USD", TimeRange.Days30));
        Assert.Equal("$3,057", MenuBarText.Make(3056.88, "USD", TimeRange.LastWeek));
        Assert.Equal("$3,057", MenuBarText.Make(3056.88, "USD", TimeRange.SinceReset));
        Assert.Equal("$3,057", MenuBarText.Make(3056.88, "USD", TimeRange.BillingCycle));

        // Token 模式：固定窗口有后缀，其余无后缀
        Assert.Equal("23.5B", MenuBarText.Make(23_500_000_000, TimeRange.All));
        Assert.Equal($"23.5B · {TimeRange.Today.MenuBarSuffix()}", MenuBarText.Make(23_500_000_000, TimeRange.Today));
        Assert.Equal($"23.5B · {TimeRange.Days7.ShortLabel()}", MenuBarText.Make(23_500_000_000, TimeRange.Days7));
        Assert.Equal($"23.5B · {TimeRange.Days30.ShortLabel()}", MenuBarText.Make(23_500_000_000, TimeRange.Days30));
        Assert.Equal("23.5B", MenuBarText.Make(23_500_000_000, TimeRange.LastWeek));
        Assert.Equal("23.5B", MenuBarText.Make(23_500_000_000, TimeRange.SinceReset));
        Assert.Equal("23.5B", MenuBarText.Make(23_500_000_000, TimeRange.BillingCycle));

        // 统一模式入口
        Assert.Equal("$100 · today", MenuBarText.Make(MenuBarMode.Cost, 100, 500, "USD", TimeRange.Today));
        Assert.Equal("500 · today", MenuBarText.Make(MenuBarMode.Tokens, 100, 500, "USD", TimeRange.Today));
        Assert.Equal($"$100 · {TimeRange.Days7.ShortLabel()}", MenuBarText.Make(MenuBarMode.Cost, 100, 500, "USD", TimeRange.Days7));
        Assert.Equal($"500 · {TimeRange.Days7.ShortLabel()}", MenuBarText.Make(MenuBarMode.Tokens, 100, 500, "USD", TimeRange.Days7));
    }

    [Fact]
    public void TestTokens()
    {
        Assert.Equal("0", Fmt.Tokens(0));
        Assert.Equal("999", Fmt.Tokens(999));
        Assert.Equal("1.0k", Fmt.Tokens(1000));
        Assert.Equal("12.3k", Fmt.Tokens(12_345));
        Assert.Equal("1.0M", Fmt.Tokens(999_950));
        Assert.Equal("1.0M", Fmt.Tokens(999_960));
        Assert.Equal("4.6M", Fmt.Tokens(4_560_000));
        Assert.Equal("188.0M", Fmt.Tokens(188_000_000));
        Assert.Equal("2.5B", Fmt.Tokens(2_500_000_000));
        Assert.Equal("23.5B", Fmt.Tokens(23_500_000_000));
        Assert.Equal("-12.3k", Fmt.Tokens(-12_345));
    }

    [Fact]
    public void TestTokensZh()
    {
        // < 10,000 plain digits with no grouping
        Assert.Equal("0", Fmt.Tokens(0, "zh-Hans"));
        Assert.Equal("999", Fmt.Tokens(999, "zh-Hans"));
        Assert.Equal("9999", Fmt.Tokens(9999, "zh-Hans"));

        // 10,000 boundary -> 1万
        Assert.Equal("1万", Fmt.Tokens(10_000, "zh-Hans"));
        Assert.Equal("1.2万", Fmt.Tokens(12_345, "zh-Hans"));
        Assert.Equal("101.1万", Fmt.Tokens(1_011_000, "zh-Hans"));

        // >= 1000万 (>= 10,000,000) show no decimal
        Assert.Equal("1000万", Fmt.Tokens(10_000_000, "zh-Hans"));
        Assert.Equal("1365万", Fmt.Tokens(13_647_000, "zh-Hans"));
        Assert.Equal("7514万", Fmt.Tokens(75_137_000, "zh-Hans"));
        Assert.Equal("9999万", Fmt.Tokens(99_994_000, "zh-Hans"));
        // 99,995,000 rounds to 10000万 and rolls over to 1亿
        Assert.Equal("1亿", Fmt.Tokens(99_995_000, "zh-Hans"));
        Assert.Equal("1亿", Fmt.Tokens(99_999_600, "zh-Hans"));

        // 1e8 boundary
        Assert.Equal("1亿", Fmt.Tokens(100_000_000, "zh-Hans"));
        Assert.Equal("1.9亿", Fmt.Tokens(188_000_000, "zh-Hans"));
        Assert.Equal("235亿", Fmt.Tokens(23_500_000_000, "zh-Hans"));
        Assert.Equal("235.4亿", Fmt.Tokens(23_540_000_000, "zh-Hans"));

        // >= 1000亿 (>= 100,000,000,000) show no decimal
        Assert.Equal("1000亿", Fmt.Tokens(100_000_000_000, "zh-Hans"));
        Assert.Equal("1235亿", Fmt.Tokens(123_456_789_000, "zh-Hans"));

        // 1e12 boundary
        Assert.Equal("1万亿", Fmt.Tokens(1_000_000_000_000, "zh-Hans"));
        Assert.Equal("1.2万亿", Fmt.Tokens(1_234_567_890_123, "zh-Hans"));

        // Negative values
        Assert.Equal("-9999", Fmt.Tokens(-9999, "zh-Hans"));
        Assert.Equal("-1.2万", Fmt.Tokens(-12_345, "zh-Hans"));
        Assert.Equal("-1.9亿", Fmt.Tokens(-188_000_000, "zh-Hans"));

        // Matches when language prefix is zh
        Assert.Equal("1.2万", Fmt.Tokens(12_345, "zh"));

        // Automatically follows L10n.CurrentLanguage
        SetLanguage("zh-Hans");
        Assert.Equal("9999", Fmt.Tokens(9999));
        Assert.Equal("1.2万", Fmt.Tokens(12_345));
        Assert.Equal("235亿", Fmt.Tokens(23_500_000_000));
        Assert.Equal("235亿", MenuBarText.Make(23_500_000_000, TimeRange.All));
    }

    [Fact]
    public void TestTokensFr()
    {
        Assert.Equal("0", Fmt.Tokens(0, "fr"));
        Assert.Equal("999", Fmt.Tokens(999, "fr"));
        Assert.Equal("1k", Fmt.Tokens(1000, "fr"));
        Assert.Equal("10k", Fmt.Tokens(9999, "fr"));
        Assert.Equal("10k", Fmt.Tokens(10_000, "fr"));
        Assert.Equal("12,3k", Fmt.Tokens(12_345, "fr"));
        Assert.Equal("1M", Fmt.Tokens(999_950, "fr"));
        Assert.Equal("100M", Fmt.Tokens(99_995_000, "fr"));
        Assert.Equal("100M", Fmt.Tokens(100_000_000, "fr"));
        Assert.Equal("188M", Fmt.Tokens(188_000_000, "fr"));
        Assert.Equal("23,5Md", Fmt.Tokens(23_500_000_000, "fr"));
        Assert.Equal("1000Md", Fmt.Tokens(1_000_000_000_000, "fr"));

        // Negative values
        Assert.Equal("-12,3k", Fmt.Tokens(-12_345, "fr"));
        Assert.Equal("-188M", Fmt.Tokens(-188_000_000, "fr"));

        // Automatically follows L10n.CurrentLanguage
        SetLanguage("fr");
        Assert.Equal("12,3k", Fmt.Tokens(12_345));
        Assert.Equal("188M", Fmt.Tokens(188_000_000));
        Assert.Equal("23,5Md", Fmt.Tokens(23_500_000_000));
        Assert.Equal("23,5Md", MenuBarText.Make(23_500_000_000, TimeRange.All));
    }

    [Fact]
    public void TestPerMonthAndMultiple()
    {
        Assert.Equal("$100/mo", Fmt.PerMonth(100));
        Assert.Equal("$20/mo", Fmt.PerMonth(20));
        Assert.Equal("$19.50/mo", Fmt.PerMonth(19.5));
        Assert.Equal("—", Fmt.PerMonth(null));
        Assert.Equal("15.7×", Fmt.Multiple(15.72));
        Assert.Equal("0.0×", Fmt.Multiple(0));
        Assert.Equal("—", Fmt.Multiple(null));
    }

    [Fact]
    public void TestBytes()
    {
        Assert.Equal("0 B", Fmt.Bytes(0));
        Assert.Equal("999 B", Fmt.Bytes(999));
        Assert.Equal("1.5 KB", Fmt.Bytes(1_500));
        Assert.Equal("626 MB", Fmt.Bytes(626_000_000));
        Assert.Equal("1.1 GB", Fmt.Bytes(1_100_000_000));
        Assert.Equal("11.8 GB", Fmt.Bytes(11_800_000_000));
        Assert.Equal("55.2 GB", Fmt.Bytes(55_200_000_000));
        Assert.Equal("8 GB", Fmt.Bytes(8_000_000_000));
    }

    [Fact]
    public void TestPercent()
    {
        Assert.Equal("100%", Fmt.Percent(1));
        Assert.Equal("60%", Fmt.Percent(0.6));
        Assert.Equal("0.4%", Fmt.Percent(0.004));
    }

    [Fact]
    public void TestDay()
    {
        Assert.Equal("Oct 22, 2026", Fmt.Day("2026-10-22"));
        Assert.Equal("—", Fmt.Day(null));
    }

    [Fact]
    public void TestAttributionExplanationUsesThreshold()
    {
        Assert.Contains("80%", AttributionInfo.Explanation("dominant", 0.8));
        Assert.Contains("Unknown", AttributionInfo.Explanation("weird", 0.8));
    }
}
