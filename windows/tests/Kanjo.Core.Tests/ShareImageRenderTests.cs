using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.VisualTree;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 分享卡在测试宿主里能排版：640 宽、有标题 / 总额 / 页脚链接。单测会话用的是 headless 绘图桩，
/// 位图编码是空操作，所以 PNG 本身用 <c>--share-image</c> 命令行钩子验证（那条路径用 Skia）。
/// </summary>
public sealed class ShareImageRenderTests : KanjoTestCase
{
    [Fact]
    public void TestShareViewLaysOutAtCardWidth()
    {
        OnUi(() =>
        {
            // 底栏按钮的两个字形也要能解析。
            _ = Icons.Photo(14, Brushes.White);
            _ = Icons.Check(14, Brushes.White);

            var summary = ShareSummary.Build(LoadFixture(), "all", Ts("2026-01-01T00:00:00Z"));
            var view = new ShareImageView(summary);
            var window = TestWindows.ShowSizedToContent(view);
            try
            {
                view.Measure(Size.Infinity);
                view.Arrange(new Rect(view.DesiredSize));
                Assert.Equal(ShareImageView.CardWidth, view.Bounds.Width);
                Assert.True(view.Bounds.Height >= 300, $"share card height = {view.Bounds.Height}");

                var texts = view.GetVisualDescendants().OfType<TextBlock>().Select(t => t.Text ?? "").ToList();
                Assert.Contains("Kanjo", texts);
                Assert.Contains("github.com/mammut001/kanjo", texts);
                Assert.Contains(Fmt.Money(summary.Totals.Cost, summary.Currency), texts);
            }
            finally
            {
                window.Close();
            }
        });
    }

    [Fact]
    public void LongAgentRowsStayInsideCard()
    {
        OnUi(() =>
        {
            var summary = ShareSummary.Build(LoadFixture(), "all", Ts("2026-10-23T02:00:00Z"));
            var template = summary.AgentRows[0];
            var rows = Enumerable.Range(0, 29).Select(i => template with
            {
                Agent = $"agent{i}", Label = new string('W', 80), Tokens = 9_900_000_000,
                Cost = 1_234_567.89, Multiplier = null,
            }).ToList();
            var view = new ShareImageView(summary with { AgentRows = rows });
            var window = TestWindows.ShowSizedToContent(view);
            try
            {
                view.Measure(Size.Infinity);
                view.Arrange(new Rect(view.DesiredSize));
                var texts = view.GetVisualDescendants().OfType<TextBlock>().ToList();
                Assert.Contains(texts, t => t.Text == L10n.Tr("share.more_agents", 22));
                foreach (var text in texts.Where(t => t.Text == Fmt.Money(1_234_567.89, summary.Currency)))
                {
                    var point = text.TranslatePoint(new Point(0, 0), view)!.Value;
                    Assert.True(point.X >= 0 && point.X + text.Bounds.Width <= ShareImageView.CardWidth);
                }
                Assert.Contains(texts, t => t.Text == new string('W', 80) && t.TextTrimming == TextTrimming.CharacterEllipsis);
            }
            finally { window.Close(); }
        });
    }

    [Fact]
    public void LongRangeCaptionWrapsBeforeTotals()
    {
        OnUi(() =>
        {
            var summary = ShareSummary.Build(LoadFixture(), "billingCycle", Ts("2026-10-23T02:00:00Z"));
            var view = new ShareImageView(summary);
            var window = TestWindows.ShowSizedToContent(view);
            try
            {
                view.Measure(Size.Infinity);
                view.Arrange(new Rect(view.DesiredSize));
                var caption = view.GetVisualDescendants().OfType<TextBlock>().Single(t => t.Text == summary.RangeLabel);
                var amount = view.GetVisualDescendants().OfType<TextBlock>().First(t => t.Text == Fmt.Money(summary.Totals.Cost, summary.Currency));
                var captionOrigin = caption.TranslatePoint(new Point(0, 0), view)!.Value;
                var amountOrigin = amount.TranslatePoint(new Point(0, 0), view)!.Value;
                Assert.Equal(TextWrapping.Wrap, caption.TextWrapping);
                Assert.True(captionOrigin.X + caption.Bounds.Width <= amountOrigin.X);
            }
            finally { window.Close(); }
        });
    }

    [Fact]
    public void EmptyShareExplainsBothSections()
    {
        OnUi(() =>
        {
            var summary = ShareSummary.Build(LoadFixture(), "all") with { AgentRows = [], MosaicProjects = [] };
            var view = new ShareImageView(summary);
            var window = TestWindows.ShowSizedToContent(view);
            try
            {
                var texts = view.GetVisualDescendants().OfType<TextBlock>().Select(t => t.Text).ToList();
                Assert.Contains(L10n.Tr("overview.projects.no_usage_range"), texts);
                Assert.Contains(L10n.Tr("agents.empty"), texts);
            }
            finally { window.Close(); }
        });
    }

    [Fact]
    public void TestClipboardRejectsBadInput()
    {
        Assert.False(ShareClipboard.TrySetPng([], 0, 0, [], IntPtr.Zero));
        if (!OperatingSystem.IsWindows())
        {
            Assert.False(ShareClipboard.TrySetPng([0x89, 0x50], 1, 1, [0, 0, 0, 0], IntPtr.Zero));
        }
    }
}
