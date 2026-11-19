using Avalonia.Media;
using Kanjo.App;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>分享图能离屏画出一张非空的 2 倍 PNG。不把图写进仓库。</summary>
public sealed class ShareImageRenderTests : KanjoTestCase
{
    [Fact]
    public void TestShareViewRendersNonEmptyBitmap()
    {
        OnUi(() =>
        {
            // 底栏按钮的两个字形也要能解析，否则只有命令行钩子是绿的。
            _ = Icons.Photo(14, Brushes.White);
            _ = Icons.Check(14, Brushes.White);

            var summary = ShareSummary.Build(LoadFixture(), "all", Ts("2026-01-01T00:00:00Z"));
            var image = ShareImageRunner.Render(summary);
            Assert.NotNull(image);
            Assert.Equal(1280, image.Width);
            Assert.True(image.Height >= 400, $"share image height = {image.Height}");
            Assert.True(image.Png.Length > 32);
            Assert.Equal(0x89, image.Png[0]);
            Assert.Equal((byte)'P', image.Png[1]);
            Assert.Equal((byte)'N', image.Png[2]);
            Assert.Equal((byte)'G', image.Png[3]);
            Assert.Equal(image.Width * image.Height * 4, image.Bgra.Length);
            Assert.Contains(image.Bgra, pixel => pixel != 0);

            Assert.False(ShareClipboard.TrySetPng([], 0, 0, [], IntPtr.Zero));
            if (!OperatingSystem.IsWindows())
            {
                Assert.False(ShareClipboard.TrySetPng(image.Png, image.Width, image.Height, image.Bgra, IntPtr.Zero));
            }
        });
    }
}
