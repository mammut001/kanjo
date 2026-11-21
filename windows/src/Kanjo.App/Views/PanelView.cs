using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 面板外壳：360×620，圆角、无标题栏。内容区按路由切换，顶部可能有一条警告 / 错误横幅，
/// 底部一条玻璃条：刷新按钮 + 「Updated HH:MM」+ 右侧分享图 / 磁盘 / 设置 / 退出。
/// </summary>
public sealed class PanelView : Grid
{
    public const double PanelWidth = Metrics.PanelWidth;
    public const double PanelHeight = Metrics.PanelHeight;

    private readonly AppServices _services;
    private readonly Border _contentHost;
    // 底栏里的两个控件随外观重建（图标的取色是构造时的），所以不是 readonly。
    private Clickable _refreshButton = null!;
    private TextBlock _statusText = null!;
    private Clickable? _shareButton;
    private Panel? _shareGlyphs;
    private DispatcherTimer? _shareTimer;
    private int _shareEpoch;
    private readonly StackPanel _banners;
    private readonly HoverLayer _hover = new();
    private Border? _footer;

    public AppRoute Route { get; private set; }

    /// <summary>当前内容页实例（测试用来确认数据刷新没有把整页换掉）。</summary>
    public object? CurrentPage => _page;

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

        _footer = BuildFooter();
        Grid.SetRow(_footer, 2);
        Children.Add(_footer);

        Grid.SetRow(_hover, 0);
        Grid.SetRowSpan(_hover, 3);
        Children.Add(_hover);
        HoverLayer.Current = _hover;

        _services.NavigateRequested += Navigate;
        // 换外观：代码里所有画笔都是构造时取值的（卡片底 / 文字 / 描边 / 禁用态），
        // 所以这里把整块面板重建一次，而不是指望它们自己跟着变。
        // 弱引用订阅：面板会被丢弃重建，静态事件不能让旧面板活着。
        Appearance.Watch(this, p => p.OnAppearanceChanged());
        // 磁盘扫描只改底栏，不走 Changed，否则总览 / 设置会被整页拆掉。
        _services.Disk.Changed += OnDiskChanged;
        DetachedFromVisualTree += (_, _) => Detach();
        Rebuild();
        _services.Changed += OnChanged;
        // 更新状态（检查中 / 下载进度 / 已下载）只重建顶部横幅，不重建整页：
        // 否则下载进度每跳一次，设置页的滚动位置就被清零。
        _services.UpdatesChanged += RebuildBannersThreadSafe;
    }

    /// <summary>更新状态变了：只重建横幅（切到 UI 线程，和 <see cref="OnChanged"/> 一样的规则）。</summary>
    private void RebuildBannersThreadSafe()
    {
        if (Avalonia.Threading.Dispatcher.UIThread.CheckAccess())
        {
            RebuildBanners();
            return;
        }
        Avalonia.Threading.Dispatcher.UIThread.Post(RebuildBanners);
    }

    /// <summary>外观切换后重建外壳 + 页面（色板已由 <see cref="Appearance"/> 切好）。</summary>
    internal void OnAppearanceChanged()
    {
        void Apply()
        {
            Background = Palette.PanelBackground;

            // 底栏自己的背景 / 描边 / 图标颜色也是构造时取的，跟着换一份。
            // 重建后要保证悬停层仍在最上面（它跨三行画悬停卡）。
            if (_footer is not null) Children.Remove(_footer);
            Children.Remove(_hover);
            _footer = BuildFooter();
            Grid.SetRow(_footer, 2);
            Children.Add(_footer);
            Children.Add(_hover);

            // 内容区里的页面同样是构造时取色，整页重建一次。
            _hover.Hide();
            Rebuild();
        }

        if (Avalonia.Threading.Dispatcher.UIThread.CheckAccess()) Apply();
        else Avalonia.Threading.Dispatcher.UIThread.Post(Apply);
    }

    private void OnChanged() => RefreshContent();

    /// <summary>
    /// 数据变了（报告 / 设置）但路由没变：能原地更新的页面原地更新，不换实例。
    /// 磁盘页不看用量报告，只更新横幅和底栏（选中项、清理预览、清理结果都在页面实例上）；
    /// 设置页用自己的 Rebuild（保留滚动位置、正在输入的令牌、「Show N more」）；
    /// 其它滚动页重新构造，但回到原来的滚动位置。
    /// </summary>
    public void RefreshContent()
    {
        if (!Avalonia.Threading.Dispatcher.UIThread.CheckAccess())
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(RefreshContent);
            return;
        }
        if (!SnapshotMode)
        {
            switch (_page)
            {
                case DiskPage when Route.Kind == AppRouteKind.Disk:
                    RebuildBanners();
                    UpdateChrome();
                    return;
                case SettingsPage settings when Route.Kind == AppRouteKind.Settings:
                    RebuildBanners();
                    settings.Rebuild();
                    UpdateChrome();
                    return;
                case ScrollPage page when _restoreOverviewOffset is null && page.VerticalOffset > 0:
                    _restoreOverviewOffset = page.VerticalOffset;
                    break;
            }
        }
        Rebuild();
    }

    public void Navigate(AppRoute route)
    {
        // 返回总览时恢复上次的滚动位置（Windows 11 的返回行为）；其它跳转从顶部开始。
        if (route.Kind == AppRouteKind.Overview && _overviewOffset is { } offset && Route.Kind != AppRouteKind.Overview)
        {
            _restoreOverviewOffset = offset;
        }
        if (Route.Kind == AppRouteKind.Overview && _page is ScrollPage current) _overviewOffset = current.VerticalOffset;

        Route = route;
        _hover.Hide();
        // 只有真的换页才播放过渡；同一页因为数据变化重建时不动（否则每次刷新都闪一下）。
        _animateNextRebuild = true;
        Rebuild();
    }

    /// <summary>下一次重建要不要播放页面过渡（只有导航时播放）。</summary>
    private bool _animateNextRebuild;

    /// <summary>总览页上次的滚动位置（返回时恢复）。</summary>
    private double? _overviewOffset;
    private double? _restoreOverviewOffset;

    public void Rebuild()
    {
        if (!Avalonia.Threading.Dispatcher.UIThread.CheckAccess())
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(Rebuild);
            return;
        }

        RebuildBanners();
        HoverLayer.PinnedId = Route.Anchor;

        var animate = _animateNextRebuild;
        _animateNextRebuild = false;
        var content = BuildContent();
        _contentHost.Child = null;
        if (animate) Motion.SwapContent(_contentHost, content);
        else _contentHost.Child = content;

        UpdateChrome();

        // 底栏不随路由重建，分享按钮的显隐在这里切（总览 / 项目 / 桶，且已经有报告）。
        if (_shareButton is not null) _shareButton.IsVisible = ShareButtonVisible();

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
        _page = content;
        // 截图模式：滚动页交出内部内容，按整页高度渲染（和 Mac 的 TALL 截图一致）。
        if (SnapshotMode && content is ISnapshotPage snapshotPage) return snapshotPage.SnapshotBody;
        // 返回总览 / 同一页因数据刷新重建：等这一页布局完成后把滚动位置放回去（动画不会改变最终位置）。
        if (content is ScrollPage page && _restoreOverviewOffset is { } restore)
        {
            _restoreOverviewOffset = null;
            page.RestoreOffsetLater(restore);
        }
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
        box.Children.Add(Ui.Text(text, 14, null, Palette.Secondary));
        box.Children.Add(Widgets.BackButton(L10n.Tr("menu.back_to_overview"),
            () => Navigate(AppRoute.Overview)));
        return box;
    }

    private void RebuildBanners()
    {
        _banners.Children.Clear();
        _banners.IsVisible = false;
        if (Route.Kind is AppRouteKind.Loading) return;

        var list = new List<Control>();
        // 更新横幅在最上面：用户一打开面板就能看到「重启即可更新」。
        var updates = _services.Updates;
        if (UpdateBanner.ShouldShow(updates.Status, updates.DismissedVersion))
        {
            list.Add(UpdateBannerView.Make(updates, RestartToUpdate, updates.DismissBanner));
        }
        if (_services.Report is { } report && report.IsNewerSchema)
        {
            list.Add(Widgets.StatusBlock(false,
            [
                Ui.Text(L10n.TrL(null, "menu.schema_warning", report.SchemaVersion,
                    Contract.SupportedSchemaVersion), 12, FontWeight.Medium, Palette.WarnInk, wrap: true),
            ]));
        }
        if (_services.Report is not null && _services.Error is { } error)
        {
            list.Add(Widgets.StatusBlock(true,
            [
                Ui.Text(L10n.Tr("menu.refresh_failed_banner"), 12, FontWeight.SemiBold, Palette.Bad),
                Ui.Text(error, 12, null, Palette.Bad, wrap: true),
            ]));
        }
        if (list.Count == 0) return;
        foreach (var control in list) _banners.Children.Add(control);
        _banners.IsVisible = true;
    }

    /// <summary>横幅里的「Restart to update」：走和托盘菜单同一条 <see cref="UpdateService.RestartToUpdate"/>。</summary>
    private void RestartToUpdate() => _services.Updates.RestartToUpdate();

    /// <summary>底栏：一条玻璃条，里面是无底的图标按钮。</summary>
    /// <summary>底栏（Windows 11 的命令栏）：左边刷新 + 「Updated HH:MM」，右边分享图 / 磁盘 / 设置 / 退出。</summary>
    private Border BuildFooter()
    {
        // 外观重建会换掉按钮宿主。停掉上一轮的勾，避免把勾画进新的底栏。
        _shareEpoch++;
        _shareTimer?.Stop();
        _shareTimer = null;

        var bar = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto,Auto,Auto,Auto") };

        // 底栏的图标 / 文字都按当前外观取色，所以每次构建都重新造（外观切换时会重建底栏）。
        _refreshButton = Ui.IconButton(Icons.Refresh(12, Palette.Secondary), () =>
        {
            // 刷新可能跑 CLI（几秒），放后台线程；用户主动刷新（取消待触发的防抖任务）。
            // 刷新自己会发 Changed / Disk.Changed，这里不再额外通知，否则整页多重建一次。
            Task.Run(() =>
            {
                if (Route.Kind == AppRouteKind.Disk) _services.Disk.Refresh(rescan: true);
                else _services.RequestUserRefresh();
            });
        }, L10n.Tr("menu.refresh_now"));
        _statusText = Ui.Text("", 12, null, Palette.Secondary);
        _statusText.VerticalAlignment = VerticalAlignment.Center;

        var left = Ui.H(4);
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

        _shareGlyphs = new Panel { Width = 32, Height = 32 };
        SetShareGlyph(false);
        var shareInner = new Border
        {
            Width = 32,
            Height = 32,
            CornerRadius = new CornerRadius(6),
            Background = Brushes.Transparent,
            Child = _shareGlyphs,
        };
        _shareButton = new Clickable(shareInner, CopyUsageImage, L10n.Tr("menu.copy_usage_image"), radius: 6);
        _shareButton.VerticalAlignment = VerticalAlignment.Center;
        _shareButton.IsVisible = ShareButtonVisible();
        Grid.SetColumn(_shareButton, 2);
        bar.Children.Add(_shareButton);

        bar.Children.Add(IconCell(
            Icons.Disk(14, Route.Kind == AppRouteKind.Disk ? Palette.Link : Palette.Secondary),
            ToggleDisk, L10n.Tr("menu.disk"), Route.Kind == AppRouteKind.Disk, 3));
        bar.Children.Add(IconCell(
            Icons.Gear(14, Route.Kind == AppRouteKind.Settings ? Palette.Link : Palette.Secondary),
            ToggleSettings, L10n.Tr("menu.settings"), Route.Kind == AppRouteKind.Settings, 4));
        bar.Children.Add(IconCell(Icons.Power(14, Palette.Secondary), Quit, L10n.Tr("menu.quit"), false, 5));

        return new Border
        {
            Child = bar,
            BorderBrush = Palette.CardBorder,
            BorderThickness = new Thickness(0, 1, 0, 0),
            Background = Palette.CardBackground,
            Padding = new Thickness(10, 4, 8, 4),
        };
    }

    /// <summary>总览、项目、桶有报告时才显示。磁盘 / 设置 / 加载中不显示。</summary>
    private bool ShareButtonVisible() =>
        _services.Report is not null &&
        Route.Kind is AppRouteKind.Overview or AppRouteKind.Project or AppRouteKind.Bucket;

    /// <summary>用当前时间范围和隐藏项目出一张分享图，放上剪贴板。成功后勾停留约 1.5 秒。</summary>
    private void CopyUsageImage()
    {
        if (_services.Report is not { } report) return;
        ShareRender? image;
        try
        {
            var hidden = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.HiddenProjects, ""));
            var summary = ShareSummary.Build(
                report,
                _services.Settings.GetString(SettingsKeys.TimeRange),
                _services.Now,
                hidden);
            image = ShareImageRunner.Render(summary);
        }
        catch (Exception e)
        {
            Trace.WriteLine($"kanjo: share image failed: {e.Message}");
            return;
        }

        var owner = TopLevel.GetTopLevel(this)?.TryGetPlatformHandle()?.Handle ?? IntPtr.Zero;
        if (image is null || !ShareClipboard.TrySetPng(image.Png, image.Width, image.Height, image.Bgra, owner)) return;

        var epoch = _shareEpoch;
        SetShareGlyph(true);
        _shareTimer?.Stop();
        _shareTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(1500) };
        _shareTimer.Tick += (_, _) =>
        {
            _shareTimer?.Stop();
            if (epoch != _shareEpoch) return;
            SetShareGlyph(false);
        };
        _shareTimer.Start();
    }

    private void SetShareGlyph(bool copied)
    {
        if (_shareGlyphs is null) return;
        _shareGlyphs.Children.Clear();
        var glyph = copied ? Icons.Check(14, Palette.Secondary) : Icons.Photo(14, Palette.Secondary);
        glyph.HorizontalAlignment = HorizontalAlignment.Center;
        glyph.VerticalAlignment = VerticalAlignment.Center;
        _shareGlyphs.Children.Add(glyph);
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

    /// <summary>面板离开视觉树：退订全部事件，关掉的窗口不能再被刷新拽起来重建。</summary>
    private void Detach()
    {
        Appearance.Unwatch(this);
        _services.Changed -= OnChanged;
        _services.UpdatesChanged -= RebuildBannersThreadSafe;
        _services.NavigateRequested -= Navigate;
        _services.Disk.Changed -= OnDiskChanged;
    }

    /// <summary>磁盘扫描只改底栏（按钮透明度、状态文字），不重建内容页。</summary>
    private void OnDiskChanged()
    {
        if (!Avalonia.Threading.Dispatcher.UIThread.CheckAccess())
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(UpdateChrome);
            return;
        }
        UpdateChrome();
    }

    /// <summary>状态文字：正常运行时是真实时钟；--snapshot 时固定在报告时间（截图可复现，见 README）。</summary>
    private void UpdateChrome()
    {
        _refreshButton.Opacity = _services.IsLoading || _services.Disk.IsLoading ? 0.45 : 1;
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

    private object? _page;
}
