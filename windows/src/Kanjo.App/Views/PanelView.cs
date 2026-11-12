using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

public enum Route
{
    Overview,
    Project,
    Bucket,
    Disk,
    Settings,
}

/// <summary>
/// 面板外壳：360×620，圆角、无标题栏。
/// 批次 1 只实现概览页；磁盘 / 设置是占位页（可导航、可退出）。
/// 底部一条玻璃条：刷新按钮 + 「Updated HH:MM」+ 右侧磁盘 / 设置 / 退出（对应 Mac 的 footer）。
/// </summary>
public sealed class PanelView : Grid
{
    public const double PanelWidth = Metrics.PanelWidth;
    public const double PanelHeight = Metrics.PanelHeight;

    private readonly AppServices _services;
    private readonly Border _contentHost;
    private readonly Clickable _refreshButton;
    private readonly TextBlock _statusText;

    public Route Route { get; private set; }

    /// <summary>截图模式：内容不滚动、按整页高度展开。</summary>
    public bool SnapshotMode { get; }

    public PanelView(AppServices services, Route route = Route.Overview, bool snapshotMode = false)
    {
        _services = services;
        Route = route;
        SnapshotMode = snapshotMode;
        Width = PanelWidth;
        // 快照模式不固定高度：内容多高就多高（整页截图）。
        if (!snapshotMode) Height = PanelHeight;
        RowDefinitions = snapshotMode ? new RowDefinitions("Auto,Auto,Auto") : new RowDefinitions("Auto,*,Auto");
        ClipToBounds = !snapshotMode;
        Background = Palette.PanelBackground;

        _statusText = Ui.Text("", 11, null, Palette.Secondary);

        _refreshButton = Ui.IconButton(Icons.Refresh(12, Palette.Secondary), () =>
        {
            // 刷新可能跑 CLI（几秒），放后台线程，回来后通知 UI。
            Task.Run(() =>
            {
                _services.Refresh();
                _services.NotifyChanged();
            });
        }, L10n.Tr("menu.refresh_now"));

        _contentHost = new Border
        {
            Background = Brushes.Transparent,
            ClipToBounds = true,
        };
        Grid.SetRow(_contentHost, 1);
        Children.Add(_contentHost);

        var footer = BuildFooter();
        Grid.SetRow(footer, 2);
        Children.Add(footer);

        _services.NavigateRequested += Navigate;
        Rebuild();
        _services.Changed += OnChanged;
    }

    private void OnChanged()
    {
        if (!Avalonia.Threading.Dispatcher.UIThread.CheckAccess())
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(Rebuild);
            return;
        }
        Rebuild();
    }

    public void Navigate(Route route)
    {
        Route = route;
        Rebuild();
    }

    public void Rebuild()
    {
        if (!Avalonia.Threading.Dispatcher.UIThread.CheckAccess())
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(Rebuild);
            return;
        }

        if (SnapshotMode && Route == Route.Overview)
        {
            _contentHost.Child = null;
            _contentHost.Child = OverviewView.BuildContent(_services);
        }
        else
        {
            _contentHost.Child = Route switch
            {
                Route.Overview => new OverviewView(_services),
                _ => new PlaceholderView(Route),
            };
        }

        _refreshButton.Opacity = _services.IsLoading ? 0.45 : 1;
        // 状态文字：正常运行时是真实时钟；--snapshot 时固定在报告时间，保证图片可复现。
        // 数据源说明只放在悬停提示里（和 Mac 一致）。
        _statusText.Text = _services.IsLoading
            ? L10n.Tr("menu.refreshing")
            : L10n.TrL(null, "menu.updated_at", ShortDate.Clock(_services.Now));
        ToolTip.SetTip(_statusText, _services.DescribeSource());
    }

    /// <summary>底栏：一条玻璃条，里面是无底的图标按钮。</summary>
    private Control BuildFooter()
    {
        var bar = Ui.H(2);
        bar.Margin = new Thickness(5, 3, 5, 3);
        bar.Children.Add(_refreshButton);
        bar.Children.Add(_statusText);
        bar.Children.Add(Ui.Spacer());
        bar.Children.Add(Ui.IconButton(Icons.Disk(12, Palette.Secondary), () => Navigate(Route.Disk),
            L10n.Tr("menu.disk"), active: Route == Route.Disk));
        bar.Children.Add(Ui.IconButton(Icons.Gear(12, Palette.Secondary), () => Navigate(Route.Settings),
            L10n.Tr("menu.settings"), active: Route == Route.Settings));
        bar.Children.Add(Ui.IconButton(Icons.Power(12, Palette.Secondary), Quit, L10n.Tr("menu.quit")));

        return new Border
        {
            Child = bar,
            CornerRadius = new CornerRadius(12),
            Background = Palette.GroupFill,
            Margin = new Thickness(8, 4, 8, 8),
        };
    }

    private static void Quit()
    {
        if (Application.Current?.ApplicationLifetime
            is Avalonia.Controls.ApplicationLifetimes.IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.Shutdown();
        }
        else
        {
            Environment.Exit(0);
        }
    }
}

/// <summary>批次 1 的占位页：项目详情 / 桶页 / 磁盘 / 设置留到批次 2。</summary>
public sealed class PlaceholderView : Border
{
    public PlaceholderView(Route route)
    {
        Padding = new Thickness(Metrics.PagePadding, 16, Metrics.PagePadding, 0);
        var box = Ui.V(8);
        var title = route switch
        {
            Route.Disk => L10n.Tr("menu.disk"),
            Route.Settings => L10n.Tr("menu.settings"),
            Route.Project => L10n.Tr("menu.back_to_overview"),
            _ => L10n.Tr("overview.total_cost"),
        };
        box.Children.Add(Ui.Text(title, 14, FontWeight.SemiBold));
        box.Children.Add(Ui.Text(L10n.Tr("menu.project_missing"), 11, null, Palette.Secondary, wrap: true));
        box.Children.Add(Ui.Text(L10n.Tr("overview.no_usage"), 11, null, Palette.Tertiary, wrap: true));
        Child = box;
    }
}
