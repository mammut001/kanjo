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
/// 面板外壳：360×620，圆角、无标题栏。批次 1 只实现概览页；其它路由显示占位。
/// 底部一条玻璃条：刷新按钮 + 更新时间 + 磁盘 / 设置 / 退出。
/// </summary>
public sealed class PanelView : Grid
{
    public const double PanelWidth = Metrics.PanelWidth;
    public const double PanelHeight = Metrics.PanelHeight;

    private readonly AppServices _services;
    private readonly Border _contentHost;
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

        _contentHost = new Border
        {
            Background = Brushes.Transparent,
            ClipToBounds = true,
            Margin = new Thickness(0),
        };
        Grid.SetRow(_contentHost, 1);
        Children.Add(_contentHost);

        var footer = BuildFooter();
        Grid.SetRow(footer, 2);
        Children.Add(footer);

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
                _ => new PlaceholderView(_services, Route),
            };
        }
        _statusText.Text = SnapshotMode
            // 截图要可复现：不写墙钟时间，用数据源描述代替。
            ? _services.DescribeSource()
            : _services.IsLoading
                ? L10n.Tr("menu.refreshing")
                : _services.LastRefresh is { } t
                    ? L10n.TrL(null, "menu.updated_at", ShortDate.Clock(t))
                    : L10n.Tr("menu.not_refreshed_yet");
    }

    private Control BuildFooter()
    {
        var bar = Ui.H(2);
        bar.Margin = new Thickness(5, 3, 5, 3);

        var refresh = FooterIcon(Icons.Refresh(12, Palette.Secondary), L10n.Tr("menu.refresh_now"), () =>
        {
            // 刷新可能跑 CLI（几秒），放后台线程，回来后通知 UI。
            Task.Run(() =>
            {
                _services.Refresh();
                _services.NotifyChanged();
            });
        });
        bar.Children.Add(refresh);
        bar.Children.Add(_statusText);
        bar.Children.Add(new Panel { HorizontalAlignment = HorizontalAlignment.Stretch });
        bar.Children.Add(FooterIcon(Icons.Disk(12, Palette.Secondary), L10n.Tr("menu.disk"), () => Navigate(Route.Disk)));
        bar.Children.Add(FooterIcon(Icons.Gear(12, Palette.Secondary), L10n.Tr("menu.settings"), () => Navigate(Route.Settings)));
        bar.Children.Add(FooterIcon(Icons.Power(12, Palette.Secondary), L10n.Tr("menu.quit"), () =>
        {
            if (Application.Current?.ApplicationLifetime is Avalonia.Controls.ApplicationLifetimes.IClassicDesktopStyleApplicationLifetime desktop)
            {
                desktop.Shutdown();
            }
        }));

        var glass = new Border
        {
            Child = bar,
            CornerRadius = new CornerRadius(12),
            Background = Palette.GroupFill,
            Margin = new Thickness(8, 4, 8, 8),
        };
        return glass;
    }

    private void Navigate(Route route)
    {
        Route = route;
        Rebuild();
    }

    private static Control FooterIcon(Control glyph, string tip, Action onClick)
    {
        var button = new Button
        {
            Content = glyph,
            Width = 26,
            Height = 26,
            Padding = new Thickness(0),
            Background = Brushes.Transparent,
            BorderThickness = new Thickness(0),
            HorizontalContentAlignment = HorizontalAlignment.Center,
            VerticalContentAlignment = VerticalAlignment.Center,
            Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Hand),
        };
        button.Click += (_, _) => onClick();
        ToolTip.SetTip(button, tip);
        return button;
    }
}

/// <summary>批次 1 的占位页：项目详情 / 桶页 / 磁盘 / 设置留到批次 2。</summary>
public sealed class PlaceholderView : Border
{
    public PlaceholderView(AppServices services, Route route)
    {
        Padding = new Thickness(Metrics.PagePadding, 20, Metrics.PagePadding, 0);

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
        Child = box;
    }
}
