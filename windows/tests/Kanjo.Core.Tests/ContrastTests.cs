using Avalonia.Media;
using Kanjo.App;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// WCAG 2.1 对比度断言：把 <see cref="Palette"/> 里定义过的每一对「文字 / 表面」都算一遍。
///
/// 门槛（任务要求）：
/// - primary 文字 ≥ 12:1（卡片上和背景上都算）
/// - secondary / tertiary / caption 文字 ≥ 4.5:1（卡片上和背景上都算）
/// - disabled 文字、禁用控件描边 ≥ 3:1
/// - 卡片描边、分割线 ≥ 1.5:1（相对卡片）
/// - 强调色上的文字 ≥ 4.5:1
///
/// 这些数字不是「差不多就行」：旧版用 alpha 叠在灰底上（0.26 alpha 的前景色 ≈ 1.9:1），
/// 用户报的「Apply / Reset / Edit 和占位符几乎看不见」就是它。
/// </summary>
public sealed class ContrastTests : KanjoTestCase
{
    private static void AssertBoth(Action<bool> body)
    {
        Palette.IsDark = false;
        body(false);
        Palette.IsDark = true;
        body(true);
        Palette.IsDark = false;
    }

    [Fact]
    public void TestPrimaryTextMeetsTwelveToOne()
    {
        AssertBoth(_ =>
        {
            Assert.True(Palette.Contrast(Palette.ForegroundColor, Palette.CardColor) >= 12,
                $"primary on card = {Palette.Contrast(Palette.ForegroundColor, Palette.CardColor):F2}");
            Assert.True(Palette.Contrast(Palette.ForegroundColor, Palette.BackgroundColor) >= 12,
                $"primary on background = {Palette.Contrast(Palette.ForegroundColor, Palette.BackgroundColor):F2}");
        });
    }

    [Fact]
    public void TestSecondaryTextMeetsFourPointFive()
    {
        AssertBoth(_ =>
        {
            Assert.True(Palette.Contrast(Palette.SecondaryColor, Palette.CardColor) >= 4.5,
                $"secondary on card = {Palette.Contrast(Palette.SecondaryColor, Palette.CardColor):F2}");
            Assert.True(Palette.Contrast(Palette.SecondaryColor, Palette.BackgroundColor) >= 4.5,
                $"secondary on background = {Palette.Contrast(Palette.SecondaryColor, Palette.BackgroundColor):F2}");
        });
    }

    [Fact]
    public void TestTertiaryAndCaptionTextMeetsFourPointFive()
    {
        AssertBoth(_ =>
        {
            Assert.True(Palette.Contrast(Palette.TertiaryColor, Palette.CardColor) >= 4.5,
                $"tertiary on card = {Palette.Contrast(Palette.TertiaryColor, Palette.CardColor):F2}");
            Assert.True(Palette.Contrast(Palette.TertiaryColor, Palette.BackgroundColor) >= 4.5,
                $"tertiary on background = {Palette.Contrast(Palette.TertiaryColor, Palette.BackgroundColor):F2}");
            // Muted 和 Tertiary 同色（旧版更淡的一档已经并进来）。
            Assert.Equal(Palette.TertiaryColor, Palette.MutedColor);
        });
    }

    [Fact]
    public void TestDisabledTextAndStrokeMeetThreeToOne()
    {
        AssertBoth(_ =>
        {
            Assert.True(Palette.Contrast(Palette.DisabledColor, Palette.CardColor) >= 3,
                $"disabled on card = {Palette.Contrast(Palette.DisabledColor, Palette.CardColor):F2}");
            Assert.True(Palette.Contrast(Palette.DisabledColor, Palette.BackgroundColor) >= 3,
                $"disabled on background = {Palette.Contrast(Palette.DisabledColor, Palette.BackgroundColor):F2}");
            // 禁用的控件描边也用这个色，相对卡片同样 ≥ 3:1。
            Assert.True(Palette.Contrast(Palette.DisabledColor, Palette.CardColor) >= 3);
        });
    }

    [Fact]
    public void TestStrokesAndDividersMeetOnePointFive()
    {
        AssertBoth(_ =>
        {
            var stroke = Palette.Contrast(Palette.CardStrokeColor, Palette.CardColor);
            Assert.True(stroke >= 1.5, $"card stroke on card = {stroke:F2}");
            var separator = Palette.Contrast(Palette.CardStrokeColor, Palette.CardColor);
            Assert.True(separator >= 1.5, $"separator on card = {separator:F2}");
            // 卡片本身对背景要能看出边界（WinUI 的 layer 差，1.1:1 上下即可）。
            var card = Palette.Contrast(Palette.CardColor, Palette.BackgroundColor);
            Assert.True(card >= 1.05, $"card on background = {card:F2}");
        });
    }

    [Fact]
    public void TestAccentTextOnAccentMeetsFourPointFive()
    {
        AssertBoth(_ =>
        {
            // 按钮底色用的是 AccentFillColor（系统强调色必要时微调过），文字是 OnAccentColor。
            var onAccent = Palette.Contrast(Palette.OnAccentColor, Palette.AccentFillColor);
            Assert.True(onAccent >= 4.5, $"on-accent = {onAccent:F2}");
            // 系统强调色（headless 回 #0078D7）也要靠微调过线。
            Assert.True(Palette.Contrast(Palette.LinkColor, Palette.CardColor) >= 4.5,
                $"link on card = {Palette.Contrast(Palette.LinkColor, Palette.CardColor):F2}");
            Assert.True(Palette.Contrast(Palette.LinkColor, Palette.BackgroundColor) >= 4.5,
                $"link on background = {Palette.Contrast(Palette.LinkColor, Palette.BackgroundColor):F2}");
        });
    }

    [Fact]
    public void TestLinkTextMeetsFourPointFiveOnBothSurfaces()
    {
        AssertBoth(_ =>
        {
            var onCard = Palette.Contrast(Palette.LinkColor, Palette.CardColor);
            var onBackground = Palette.Contrast(Palette.LinkColor, Palette.BackgroundColor);
            Assert.True(onCard >= 4.5, $"accent on card = {onCard:F2}");
            Assert.True(onBackground >= 4.5, $"accent on background = {onBackground:F2}");
        });
    }

    [Fact]
    public void TestStatusTextMeetsFourPointFive()
    {
        AssertBoth(_ =>
        {
            foreach (var (name, color) in new (string, Color)[]
                     {
                         ("good", Palette.GoodColor), ("bad", Palette.BadColor),
                         ("warn", Palette.WarnInkColor),
                     })
            {
                var onCard = Palette.Contrast(color, Palette.CardColor);
                Assert.True(onCard >= 4.5, $"{name} on card = {onCard:F2}");
                var onBackground = Palette.Contrast(color, Palette.BackgroundColor);
                Assert.True(onBackground >= 4.5, $"{name} on background = {onBackground:F2}");
            }
        });
    }

    [Fact]
    public void TestInfoBarTextMeetsFourPointFiveOnItsFill()
    {
        AssertBoth(_ =>
        {
            var fill = Palette.InfoBarFillColor;
            var ink = Palette.WarnInkColor;
            var ratio = Palette.Contrast(ink, fill);
            Assert.True(ratio >= 4.5, $"warn ink on infobar fill = {ratio:F2}");
            var stroke = Palette.Contrast(Palette.InfoBarStrokeColor, fill);
            Assert.True(stroke >= 1.5, $"infobar stroke = {stroke:F2}");
        });
    }

    /// <summary>
    /// 马赛克色块上的标签文字：每个 agent 色（明 / 暗两套）都必须在白与近黑之间挑到一个 ≥ 4.5:1 的组合，
    /// 必要时色块被微调（<see cref="Palette.TileInk(Color, out Color)"/> 的第二个返回值）。
    /// </summary>
    [Fact]
    public void TestEveryAgentTileLabelMeetsFourPointFive()
    {
        foreach (var dark in new[] { false, true })
        {
            Palette.IsDark = dark;
            foreach (var agent in AgentColors.All.Keys)
            {
                var tile = Palette.AgentColor(agent);
                var ink = Palette.TileInk(tile, out var adjusted);
                var ratio = Palette.Contrast(ink, adjusted);
                Assert.True(ratio >= 4.5,
                    $"tile label for {agent} (dark={dark}) = {ratio:F2}");
                // 微调幅度必须很小，色相才不会被破坏（实测最大 3%）。
                var delta = Math.Abs(adjusted.R - tile.R) + Math.Abs(adjusted.G - tile.G) +
                            Math.Abs(adjusted.B - tile.B);
                Assert.True(delta <= 40, $"tile for {agent} shifted too far: {tile} -> {adjusted}");
            }
        }
        Palette.IsDark = false;
    }

    /// <summary>Token 构成条的三个借用色 / 图表色只是图形，不承载文字，但仍要能和白卡区分开。</summary>
    [Fact]
    public void TestChartColorsAreVisibleOnCard()
    {
        AssertBoth(_ =>
        {
            foreach (var (name, color) in new (string, Color)[]
                     {
                         ("input", Palette.TokenInputColor), ("output", Palette.TokenOutputColor),
                         ("cache_read", Palette.TokenCacheReadColor),
                         ("cache_write", Palette.TokenCacheWriteColor),
                         ("chart", Palette.ChartBarColor),
                     })
            {
                var ratio = Palette.Contrast(color, Palette.CardColor);
                Assert.True(ratio >= 1.5, $"{name} on card = {ratio:F2}");
            }
        });
    }

    /// <summary>WCAG 公式自身的自检：黑白是 21:1，同色是 1:1。</summary>
    [Fact]
    public void TestContrastFormula()
    {
        Assert.Equal(21.0, Palette.Contrast(Colors.Black, Colors.White), 1);
        Assert.Equal(1.0, Palette.Contrast(Colors.White, Colors.White), 3);
        // 中灰 #767676 对白 ≈ 4.54:1（WCAG 里的经典「刚好过 AA」的灰）。
        Assert.Equal(4.54, Palette.Contrast(Color.FromRgb(0x76, 0x76, 0x76), Colors.White), 1);
        // 相对亮度：白 = 1，黑 = 0。
        Assert.Equal(1.0, Palette.Luminance(Colors.White), 3);
        Assert.Equal(0.0, Palette.Luminance(Colors.Black), 3);
    }
}
