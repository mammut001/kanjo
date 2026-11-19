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
            var window = new Window { Content = view, SizeToContent = SizeToContent.WidthAndHeight };
            window.Show();
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
    public void TestClipboardRejectsBadInput()
    {
        Assert.False(ShareClipboard.TrySetPng([], 0, 0, [], IntPtr.Zero));
        if (!OperatingSystem.IsWindows())
        {
            Assert.False(ShareClipboard.TrySetPng([0x89, 0x50], 1, 1, [0, 0, 0, 0], IntPtr.Zero));
        }
    }
}
