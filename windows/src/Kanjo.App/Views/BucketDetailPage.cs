using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 桶详情（ProjectDetailView.swift 里的 BucketDetailView）：Unattributed / Excluded。
/// 桶没有 by_day，范围下按会话 started 过滤，金额是这些会话之和。
/// </summary>
public sealed class BucketDetailPage : ScrollViewer, ISnapshotPage
{
    /// <summary>截图模式：交出内容本身（不含滚动容器），由面板按整页高度渲染。</summary>
    public Control SnapshotBody
    {
        get
        {
            var content = Content as Control ?? new Panel();
            Content = null;
            return content;
        }
    }

    public BucketDetailPage(AppServices services, string kind, UsageReport report, Action onBack,
        bool snapshot = false)
    {
        HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled;
        VerticalScrollBarVisibility = snapshot
            ? Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled
            : Avalonia.Controls.Primitives.ScrollBarVisibility.Auto;
        Background = Brushes.Transparent;

        var ctx = new RangeContext(report, services.Settings.GetString(SettingsKeys.TimeRange), services.Now);
        var raw = kind == "excluded" ? report.Buckets.Excluded : report.Buckets.Unattributed;
        var bucket = RangeEngine.Filter(raw, ctx.Spec);
        var currency = report.Currency;

        var header = Ui.V(3);
        header.Children.Add(Ui.Text(
            kind == "excluded" ? L10n.Tr("overview.excluded") : L10n.Tr("overview.unattributed"),
            15, FontWeight.SemiBold));

        var amountRow = Ui.H(4);
        amountRow.Children.Add(Widgets.HeroAmount(Fmt.Money(bucket.Cost, currency), 30));
        if (report.CostNoteDisplayText is { } note)
        {
            var info = Icons.InfoCircle(10, Palette.Secondary);
            info.Margin = new Thickness(0, 4, 0, 0);
            amountRow.Children.Add(info);
            ToolTip.SetTip(info, note);
        }
        header.Children.Add(amountRow);

        var usageText = bucket.FirstActive is null
            ? L10n.Tr("project.no_usage")
            : ShortDate.Range(bucket.FirstActive, bucket.LastActive);
        header.Children.Add(Ui.Text(ProjectSubtitleText.Make(ctx.Range, bucket.Sessions, usageText),
            11, null, Palette.Secondary));

        if (ctx.Caption is { } caption)
        {
            var combined = caption + L10n.Tr("project.bucket.by_session_start");
            var line = new RangeCaptionLine(new RangeCaptionResult(combined, ctx.CaptionHelp));
            line.Margin = new Thickness(0, 1, 0, 0);
            header.Children.Add(line);
        }

        var explanation = Ui.Text(
            SessionAttributionInfo.Explanation(kind == "excluded" ? "excluded" : "none",
                report.Config.DominantThreshold),
            10.5, null, Palette.Secondary, wrap: true);
        explanation.Margin = new Thickness(0, 8, 0, 0);
        header.Children.Add(explanation);
        header.Margin = new Thickness(Metrics.RowInset - Metrics.PagePadding, 0,
            Metrics.RowInset - Metrics.PagePadding, 0);

        var sessions = Chrome.Section(L10n.TrL(null, "project.section.sessions", bucket.SessionsDetail.Count),
            new SessionList(services, bucket.SessionsDetail, report.Config.DominantThreshold, currency),
            padding: Metrics.RowInset);

        Content = DetailPage.Build(L10n.Tr("disk.navigation.overview"), onBack, [header, sessions]);
    }
}

/// <summary>加载页（InitialLoadingView）：转圈 + 「Loading…」，超过 3 秒再补一句首次扫描说明。</summary>
public sealed class LoadingPage : Grid
{
    public LoadingPage(double simulatedSeconds = 0)
    {
        // 内容区至少铺满面板高度减底栏，转圈垂直居中（和 Mac 的 Spacer 一样）。
        MinHeight = Metrics.PanelHeight - 110;
        HorizontalAlignment = HorizontalAlignment.Stretch;

        var box = new StackPanel
        {
            Orientation = Orientation.Vertical,
            Spacing = 12,
            VerticalAlignment = VerticalAlignment.Center,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            Margin = new Thickness(Metrics.PagePadding, 0, Metrics.PagePadding, 0),
        };

        var spinner = new Spinner(16, Palette.Secondary)
        {
            HorizontalAlignment = HorizontalAlignment.Center,
        };
        box.Children.Add(spinner);
        var loading = Ui.Text(L10n.Tr("common.loading"), 11, FontWeight.Medium, Palette.Secondary);
        loading.TextAlignment = TextAlignment.Center;
        box.Children.Add(loading);

        var elapsed = TimeSpan.FromSeconds(Math.Max(0, simulatedSeconds));
        if (FirstScanHint.ShouldShow(false, elapsed))
        {
            var hint = new StackPanel { Orientation = Orientation.Vertical, Spacing = 6 };
            var explanation = Ui.Text(FirstScanHint.Explanation(), 11, null, Palette.Secondary, wrap: true);
            explanation.TextAlignment = TextAlignment.Center;
            hint.Children.Add(explanation);
            var seconds = Ui.Text(FirstScanHint.ElapsedText(elapsed), 10.5, null, Palette.Secondary);
            seconds.TextAlignment = TextAlignment.Center;
            hint.Children.Add(seconds);
            hint.Margin = new Thickness(28, 0, 28, 0);
            box.Children.Add(hint);
        }
        Children.Add(box);
    }
}

/// <summary>
/// 项目行右键菜单 / 悬停按钮用到的动作（ProjectActions.swift）。Windows 上：
/// 终端用 Windows Terminal（`wt -d`），没有就用 PowerShell；Finder 换成资源管理器。
/// </summary>
public static class ProjectActions
{
    /// <summary>第一个仍然存在的路径（主路径优先）。</summary>
    public static string? ExistingPath(Project project) =>
        PathKinds.SplitPaths(project.Paths.ToList()).Primary
            .Concat(PathKinds.SplitPaths(project.Paths.ToList()).Temporary)
            .FirstOrDefault(Directory.Exists);

    /// <summary>复制用的路径：存在的优先，否则第一个主路径。</summary>
    public static string? DisplayPath(Project project)
    {
        if (ExistingPath(project) is { } existing) return existing;
        var split = PathKinds.SplitPaths(project.Paths.ToList());
        return split.Primary.FirstOrDefault() ?? project.Paths.FirstOrDefault();
    }

    /// <summary>打开终端：优先 Windows Terminal（`wt -d &lt;path&gt;`），否则 PowerShell。</summary>
    public static void OpenInTerminal(string path)
    {
        if (OperatingSystem.IsWindows() && WhichOnPath("wt.exe") is not null)
        {
            Launch("wt.exe", ["-d", path]);
            return;
        }
        Launch("powershell.exe", ["-NoExit", "-Command", $"Set-Location -LiteralPath '{path.Replace("'", "''")}'"]);
    }

    /// <summary>在资源管理器里选中该项目路径。</summary>
    public static void ShowInExplorer(string path)
    {
        if (OperatingSystem.IsWindows())
        {
            Launch("explorer.exe", ["/select,", path]);
            return;
        }
        // 开发运行为 macOS：用 open -R 近似（仅用于对图 / 自测）。
        if (OperatingSystem.IsMacOS()) Launch("open", ["-R", path]);
    }

    /// <summary>打开网址（billing 页面 / 部署指南）。</summary>
    public static void OpenUrl(string url)
    {
        try
        {
            var psi = new ProcessStartInfo(url) { UseShellExecute = true };
            Process.Start(psi);
        }
        catch (Exception)
        {
            // 打不开就忽略。
        }
    }

    /// <summary>复制到剪贴板。由面板在构建时注入实现（headless 下没有剪贴板，忽略失败）。</summary>
    public static Action<string>? ClipboardWriter { get; set; }

    public static void Copy(string text)
    {
        try
        {
            ClipboardWriter?.Invoke(text);
        }
        catch (Exception)
        {
            // 没有剪贴板（headless）时忽略。
        }
    }

    private static void Launch(string file, IReadOnlyList<string> args)
    {
        try
        {
            var psi = new ProcessStartInfo(file)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            foreach (var arg in args) psi.ArgumentList.Add(arg);
            Process.Start(psi);
        }
        catch (Exception)
        {
            // 目标程序不存在时静默失败（和 Mac 的 best-effort 一致）。
        }
    }

    private static string? WhichOnPath(string name) => CliRunner.WhichOnPath(name);
}
