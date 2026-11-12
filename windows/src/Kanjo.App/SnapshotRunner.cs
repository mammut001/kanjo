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
/// 可滚动的页面按整页渲染（不裁剪到 620），和 Mac 的截图行为一致。
/// </summary>
public static class SnapshotRunner
{
    /// <summary>等待数据 / 磁盘报告的上限（和 Mac 一样约 20 秒）。</summary>
    private static readonly TimeSpan LoadTimeout = TimeSpan.FromSeconds(20);

    public static int Run(string outputPath, string route, double scale, string? appearance)
    {
        var previousRoot = L10n.ResourcesRoot;
        try
        {
            AppSetup.ConfigureHeadless(appearance);
            // Mac 的截图是在非活动窗口里截的：borderedProminent 按钮就是灰白的。
            WindowActivation.Reset();

            var services = AppServices.Create(Environment.GetCommandLineArgs());
            services.LoadQuietly();
            // 外观：`--snapshot-appearance light|dark` 是显式覆盖，否则用设置（缺省 Dark）。
            // 必须在建界面之前定好，否则代码里取色的画笔会停在上一套。
            Appearance.Apply(services.Settings);
            // 截图可复现：相对日期与订阅账期倒计时都按报告时间算，而不是墙钟。
            ShortDate.ReferenceNow = services.Now;

            if (DevRoutes.NeedsDisk(route)) LoadDiskReport(services, route);

            var resolved = ResolveRoute(route, services);
            ShortDate.ReferenceNow = services.Now;

            // 快照按整页渲染（不裁剪滚动区域），这样截图能看到完整页面。
            var panel = new PanelView(services, resolved, snapshotMode: true);

            // 必须先挂到窗口（TopLevel）再测量：ToggleSwitch / ComboBox 这类模板控件只有在窗口里
            // 才会套用 ControlTheme，脱离窗口直接 Measure 会抛 KeyNotFoundException（缺模板部件）。
            var host = new Border
            {
                Width = Metrics.PanelWidth,
                Background = Palette.PanelBackground,
                Child = panel,
            };
            var window = new Window
            {
                SystemDecorations = SystemDecorations.None,
                Width = Metrics.PanelWidth,
                Height = Metrics.PanelHeight,
                Content = host,
            };
            window.Show();
            Dispatcher.UIThread.RunJobs();

            // 挂上窗口之后才知道整页多高。
            host.Measure(new Size(Metrics.PanelWidth, double.PositiveInfinity));
            var contentHeight = MeasureHeight(panel, Metrics.PanelWidth);
            window.Height = contentHeight;
            window.UpdateLayout();
            Dispatcher.UIThread.RunJobs();

            Layout();

            // 固定悬停卡要等布局完成后才定位，再来一轮完整布局。
            if (resolved.Anchor is { } anchor)
            {
                panel.PrepareSnapshot(anchor);
                Layout();
                Dispatcher.UIThread.RunJobs();
            }

            void Layout()
            {
                host.Height = contentHeight;
                host.Measure(new Size(Metrics.PanelWidth, contentHeight));
                host.Arrange(new Rect(0, 0, Metrics.PanelWidth, contentHeight));
                window.UpdateLayout();
                Dispatcher.UIThread.RunJobs();
            }

            var pixelSize = new PixelSize(
                (int)Math.Round(Metrics.PanelWidth * scale),
                (int)Math.Round(contentHeight * scale));
            using var bitmap = new RenderTargetBitmap(pixelSize, new Vector(96 * scale, 96 * scale));
            bitmap.Render(host);

            window.Content = null;
            window.Close();

            var dir = Path.GetDirectoryName(Path.GetFullPath(outputPath));
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            bitmap.Save(outputPath);
            Console.WriteLine($"snapshot: {outputPath} ({pixelSize.Width}×{pixelSize.Height}) route={route}");
            return 0;
        }
        finally
        {
            L10n.ResourcesRoot = previousRoot;
            ShortDate.ReferenceNow = null;
            HoverLayer.PinnedId = null;
            // 进程内只出一次图；清掉显式覆盖，免得影响同一进程里的其它渲染。
            Appearance.Override = null;
        }
    }

    private static void LoadDiskReport(AppServices services, string route)
    {
        // 文件来源是同步的；CLI 会起进程，等它完成（最多 20 秒）。
        services.Disk.RefreshBlocking(rescan: false);
        var deadline = DateTime.UtcNow + LoadTimeout;
        while (services.Disk.IsLoading && DateTime.UtcNow < deadline)
        {
            Thread.Sleep(50);
        }
        if (services.Disk.Report is null)
        {
            Console.Error.WriteLine($"disk report unavailable: {services.Disk.Error}");
        }
        _ = route;
    }

    private static AppRoute ResolveRoute(string route, AppServices services)
    {
        if (DevRoutes.IsLoadingRoute(route))
        {
            return DevRoutes.Resolve(route, services.Report) ?? AppRoute.Loading(12);
        }
        if (DevRoutes.Resolve(route, services.Report) is { } resolved) return resolved;
        Console.Error.WriteLine($"route '{route}' not resolved; falling back to overview");
        return AppRoute.Overview;
    }

    private static double MeasureHeight(Control panel, double width)
    {
        panel.Measure(new Size(width, double.PositiveInfinity));
        var desired = panel.DesiredSize.Height;
        if (!double.IsFinite(desired) || desired <= 0) return Metrics.PanelHeight;
        // 内容比 620 矮时仍按 620 出图（面板固定大小），更高则完整展开。
        return Math.Max(Metrics.PanelHeight, Math.Min(desired, 8000));
    }

    public static AppRoute ParseRoute(string? raw, UsageReport? report = null) =>
        DevRoutes.Resolve(raw ?? "overview", report) ?? AppRoute.Overview;

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
