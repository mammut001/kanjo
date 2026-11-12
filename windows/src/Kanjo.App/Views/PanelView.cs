using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 面板外壳：360×620，圆角、无标题栏。内容区按路由切换，顶部可能有一条警告 / 错误横幅，
/// 底部一条玻璃条：刷新按钮 + 「Updated HH:MM」+ 右侧磁盘 / 设置 / 退出。
/// </summary>
public sealed class PanelView : Grid
{
    public const double PanelWidth = Metrics.PanelWidth;
    public const double PanelHeight = Metrics.PanelHeight;

    private readonly AppServices _services;
    private readonly Border _contentHost;
    private readonly Clickable _refreshButton;
    private readonly TextBlock _statusText;
    private readonly StackPanel _banners;
    private readonly HoverLayer _hover = new();

    public AppRoute Route { get; private set; }

    /// <summary>截图模式：内容不滚动、按整页高度展开。</summary>
    public bool SnapshotMode { get; }

    public PanelView(AppServices services, AppRoute route, bool snapshotMode = false)
    {
        _services = services;
        Route = route;
        SnapshotMode = snapshotMode;
        Width = PanelWidth;
        if (!snapshotMode) Height = PanelHeight;
        RowDefinitions = snapshotMode ? new RowDefinitions("Auto,Auto,Auto") : new RowDefinitions("Auto,*,Auto");
        ClipToBounds = !snapshotMode;
        Background = Palette.PanelBackground;

        _statusText = Ui.Text("", 11, null, Palette.Secondary);
        _statusText.VerticalAlignment = VerticalAlignment.Center;

        _refreshButton = Ui.IconButton(Icons.Refresh(12, Palette.Secondary), () =>
        {
            // 刷新可能跑 CLI（几秒），放后台线程；用户主动刷新（取消待触发的防抖任务）。
            Task.Run(() =>
            {
                if (Route.Kind == AppRouteKind.Disk) _services.Disk.Refresh(rescan: true);
                else _services.RequestUserRefresh();
                _services.NotifyChanged();
            });
        }, L10n.Tr("menu.refresh_now"));

        _banners = Ui.V(6);
        _banners.Margin = new Thickness(10, 10, 10, 2);
        _banners.IsVisible = false;
        Grid.SetRow(_banners, 0);
        Children.Add(_banners);

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

        Grid.SetRow(_hover, 0);
        Grid.SetRowSpan(_hover, 3);
        Children.Add(_hover);
        HoverLayer.Current = _hover;

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

    public void Navigate(AppRoute route)
    {
        Route = route;
        _hover.Hide();
        Rebuild();
    }

    public void Rebuild()
    {
        if (!Avalonia.Threading.Dispatcher.UIThread.CheckAccess())
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(Rebuild);
            return;
        }

        RebuildBanners();
        HoverLayer.PinnedId = Route.Anchor;

        var content = BuildContent();
        _contentHost.Child = null;
        _contentHost.Child = content;

        _refreshButton.Opacity = _services.IsLoading || _services.Disk.IsLoading ? 0.45 : 1;
        // 状态文字：正常运行时是真实时钟；--snapshot 时固定在报告时间（截图可复现，见 README）。
        if (Route.Kind == AppRouteKind.Disk)
        {
            _statusText.Text = _services.Disk.IsLoading
                ? L10n.Tr("menu.refreshing")
                : _services.Disk.LastRefresh is not null
                    ? L10n.TrL(null, "menu.updated_at", ShortDate.Clock(_services.Now))
                    : L10n.Tr("menu.not_refreshed_yet");
            ToolTip.SetTip(_statusText, _services.Disk.SourceDescription);
        }
        else
        {
            _statusText.Text = _services.IsLoading
                ? L10n.Tr("menu.refreshing")
                : _services.LastRefresh is not null
                    ? L10n.TrL(null, "menu.updated_at", ShortDate.Clock(_services.Now))
                    : L10n.Tr("menu.not_refreshed_yet");
            ToolTip.SetTip(_statusText, _services.DescribeSource());
        }

        // 固定悬停卡（截图用）：内容建好后按 id 显示。
        if (HoverLayer.PinnedId is { } pinned && pinned.Contains(":hover:", StringComparison.Ordinal))
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(() =>
            {
                UpdateLayout();
                _hover.ShowRegistered(pinned);
            }, Avalonia.Threading.DispatcherPriority.Loaded);
        }
    }

    private Control BuildContent()
    {
        var content = BuildPage();
        _page = content as ISnapshotPage;
        // 截图模式：滚动页交出内部内容，按整页高度渲染（和 Mac 的 TALL 截图一致）。
        if (SnapshotMode && content is ISnapshotPage snapshotPage) return snapshotPage.SnapshotBody;
        return content;
    }

    private Control BuildPage()
    {
        switch (Route.Kind)
        {
            case AppRouteKind.Loading:
                return new LoadingPage(Route.LoadingSeconds);
            case AppRouteKind.Disk:
                return new DiskPage(_services, expandAll: Route.Anchor == RouteAnchors.DiskExpanded,
                    snapshot: SnapshotMode,
                    onBack: () => Navigate(AppRoute.Overview),
                    onSettings: () => Navigate(AppRoute.Settings));
            case AppRouteKind.Settings:
                return new SettingsPage(_services, Route.Anchor, Route.EditingAgent, snapshot: SnapshotMode,
                    onBack: () =>
                    {
                        _services.ApplySettings();
                        Navigate(AppRoute.Overview);
                    });
            case AppRouteKind.Project:
                if (_services.Report?.Projects.FirstOrDefault(p => p.Id == Route.ProjectId) is { } project)
                {
                    return new ProjectDetailPage(_services, project, Route.ProjectIndex, Route.Anchor,
                        () => Navigate(AppRoute.Overview), snapshot: SnapshotMode,
                        openLocations: Route.Anchor == RouteAnchors.ProjectLocationsOpen);
                }
                return MissingPage(L10n.Tr("menu.project_missing"));
            case AppRouteKind.Bucket:
                if (_services.Report is { } report)
                {
                    return new BucketDetailPage(_services, Route.Bucket ?? "unattributed", report,
                        () => Navigate(AppRoute.Overview), snapshot: SnapshotMode);
                }
                return new OverviewPage(_services, Route.Anchor, SnapshotMode);
            default:
                return new OverviewPage(_services, Route.Anchor, SnapshotMode);
        }
    }

    private Control MissingPage(string text)
    {
        var box = Ui.V(8);
        box.Margin = new Thickness(Metrics.PagePadding, 16, Metrics.PagePadding, 0);
        box.Children.Add(Ui.Text(text, 12, null, Palette.Secondary));
        box.Children.Add(Widgets.BackButton(L10n.Tr("menu.back_to_overview"),
            () => Navigate(AppRoute.Overview)));
        return box;
    }

    private void RebuildBanners()
    {
        _banners.Children.Clear();
        _banners.IsVisible = false;
        if (Route.Kind is AppRouteKind.Loading or AppRouteKind.Disk) return;

        var list = new List<Control>();
        if (_services.Report is { } report && report.IsNewerSchema)
        {
            list.Add(Widgets.StatusBlock(false,
            [
                Ui.Text(L10n.TrL(null, "menu.schema_warning", report.SchemaVersion,
                    Contract.SupportedSchemaVersion), 10.5, FontWeight.Medium, Palette.WarnInk, wrap: true),
            ]));
        }
        if (_services.Report is not null && _services.Error is { } error)
        {
            list.Add(Widgets.StatusBlock(true,
            [
                Ui.Text(L10n.Tr("menu.refresh_failed_banner"), 10.5, FontWeight.SemiBold, Palette.Bad),
                Ui.Text(error, 10.5, null, Palette.Bad, wrap: true),
            ]));
        }
        if (list.Count == 0) return;
        foreach (var control in list) _banners.Children.Add(control);
        _banners.IsVisible = true;
    }

    /// <summary>底栏：一条玻璃条，里面是无底的图标按钮。</summary>
    private Control BuildFooter()
    {
        var bar = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto,Auto,Auto") };

        var left = Ui.H(2);
        left.Children.Add(_refreshButton);
        left.Children.Add(_statusText);
        left.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(left, 0);
        bar.Children.Add(left);

        Control IconCell(Control glyph, Action onClick, string tip, bool active, int column)
        {
            var button = Ui.IconButton(glyph, onClick, tip, active);
            button.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(button, column);
            return button;
        }

        bar.Children.Add(IconCell(
            Icons.Disk(12, Route.Kind == AppRouteKind.Disk ? Palette.Accent : Palette.Secondary),
            ToggleDisk, L10n.Tr("menu.disk"), Route.Kind == AppRouteKind.Disk, 2));
        bar.Children.Add(IconCell(Icons.Gear(12, Palette.Secondary), ToggleSettings,
            L10n.Tr("menu.settings"), false, 3));
        bar.Children.Add(IconCell(Icons.Power(12, Palette.Secondary), Quit, L10n.Tr("menu.quit"), false, 4));

        return new Border
        {
            Child = bar,
            CornerRadius = new CornerRadius(12),
            Background = Palette.GroupFill,
            Padding = new Thickness(5, 1, 5, 1),
            Margin = new Thickness(8, 4, 8, 8),
        };
    }

    /// <summary>磁盘图标：从磁盘页回到总览，其它情况进磁盘页（设置页切走时先应用设置）。</summary>
    private void ToggleDisk()
    {
        var wasSettings = Route.Kind == AppRouteKind.Settings;
        Navigate(Route.Kind == AppRouteKind.Disk ? AppRoute.Overview : AppRoute.Disk);
        if (wasSettings) _services.ApplySettings();
    }

    /// <summary>设置图标：在设置页时回到总览并应用设置，其它情况进设置页。</summary>
    private void ToggleSettings()
    {
        var goingBack = Route.Kind == AppRouteKind.Settings;
        Navigate(goingBack ? AppRoute.Overview : AppRoute.Settings);
        if (goingBack) _services.ApplySettings();
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

    /// <summary>截图用：内容建好后不依赖事件，直接重排并定位固定悬停卡。</summary>
    public void PrepareSnapshot(string? anchor)
    {
        HoverLayer.PinnedId = anchor;
        UpdateLayout();
        _contentHost.UpdateLayout();
        if (anchor is null) return;
        PinHover(anchor);
        UpdateLayout();
        _hover.UpdateLayout();
    }

    /// <summary>当前面板的悬停层（截图 / 测试用）。</summary>
    public HoverLayer Hover => _hover;

    /// <summary>当前的磁盘页（键盘 Esc / Enter 转发用）。</summary>
    public DiskPage? FindDiskPage() => _contentHost.Child as DiskPage;

    /// <summary>把 `--route` 里的固定悬停卡显示出来（截图用）。</summary>
    public void PinHover(string anchor)
    {
        HoverLayer.PinnedId = anchor;
        _contentHost.UpdateLayout();
        UpdateLayout();
        if (_page is ProjectDetailPage project)
        {
            project.PinHover(anchor);
            return;
        }
        _hover.ShowRegistered(anchor);
    }

    private ISnapshotPage? _page;
}
