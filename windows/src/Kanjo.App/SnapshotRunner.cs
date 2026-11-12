using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Kanjo.App.Views;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// `--snapshot &lt;out.png&gt; [--route overview] [--snapshot-scale 2] [--snapshot-appearance light|dark]`：
/// 用 Avalonia.Headless 把面板离屏渲染成 PNG 然后退出 0。macOS 上也能跑（开发时对图用）。
/// </summary>
public static class SnapshotRunner
{
    public static int Run(string outputPath, string route, double scale, string? appearance)
    {
        var previousRoot = L10n.ResourcesRoot;
        try
        {
            AppSetup.ConfigureHeadless(appearance);

            var services = AppServices.Create(Environment.GetCommandLineArgs());
            services.LoadQuietly();
            // 截图可复现：相对日期与订阅账期倒计时都按报告时间算，而不是墙钟。
            ShortDate.ReferenceNow = services.Now;

            var routeValue = ParseRoute(route);
            // 快照按整页渲染（不裁剪滚动区域），这样截图能看到完整页面。
            var panel = new PanelView(services, routeValue, snapshotMode: true);
            var contentHeight = MeasureHeight(panel, Metrics.PanelWidth);

            var host = new Border
            {
                Width = Metrics.PanelWidth,
                Height = contentHeight,
                Background = Palette.PanelBackground,
                Child = panel,
            };
            host.Measure(new Size(Metrics.PanelWidth, contentHeight));
            host.Arrange(new Rect(0, 0, Metrics.PanelWidth, contentHeight));
            host.UpdateLayout();
            Dispatcher.UIThread.RunJobs();

            var pixelSize = new PixelSize(
                (int)Math.Round(Metrics.PanelWidth * scale),
                (int)Math.Round(contentHeight * scale));
            using var bitmap = new RenderTargetBitmap(pixelSize, new Vector(96 * scale, 96 * scale));
            bitmap.Render(host);

            var dir = Path.GetDirectoryName(Path.GetFullPath(outputPath));
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            bitmap.Save(outputPath);
            Console.WriteLine($"snapshot: {outputPath} ({pixelSize.Width}×{pixelSize.Height}) route={routeValue}");
            return 0;
        }
        finally
        {
            L10n.ResourcesRoot = previousRoot;
            ShortDate.ReferenceNow = null;
        }
    }

    private static double MeasureHeight(Control panel, double width)
    {
        panel.Measure(new Size(width, double.PositiveInfinity));
        var desired = panel.DesiredSize.Height;
        if (!double.IsFinite(desired) || desired <= 0) return Metrics.PanelHeight;
        // 内容比 620 矮时仍按 620 出图（面板固定大小），更高则完整展开。
        return Math.Max(Metrics.PanelHeight, Math.Min(desired, 4000));
    }

    public static Route ParseRoute(string? raw) => raw switch
    {
        null or "" or "overview" => Route.Overview,
        "settings" => Route.Settings,
        "disk" => Route.Disk,
        _ => Route.Overview,
    };

    /// <summary>`--snapshot-scale` 解析（默认 2，和 Mac 版一致；非法值也回落到 2）。</summary>
    public static double ParseScale(string? raw)
    {
        if (raw is null) return 2.0;
        return double.TryParse(raw, System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out var v) && v is > 0 and <= 4
            ? v
            : 2.0;
    }

    public static string? ParseAppearance(string? raw) => raw is "light" or "dark" ? raw : null;
}
