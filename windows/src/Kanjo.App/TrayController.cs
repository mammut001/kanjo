using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Media;
using Avalonia.Threading;
using Kanjo.App.Views;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 托盘（Windows 右下角通知区域）：tooltip 显示金额（`Kanjo · $3,057 · 30d`），图标随状态变化；
/// 左键点击弹出面板（再点一次收起），右键菜单：打开、刷新、设置、退出。
/// 每次刷新完成都重建 tooltip 与图标（出错是红色，成功后恢复）。
/// </summary>
public sealed class TrayController : IDisposable
{
    private readonly AppServices _services;
    private readonly TrayIcon _tray;
    private readonly NativeMenu _menu;
    private PanelWindow? _panel;
    private bool _disposed;

    public TrayController(AppServices services)
    {
        _services = services;

        _menu = new NativeMenu();
        _menu.Items.Add(MenuItem(L10n.Tr("menu.back_to_overview"), () => ShowPanel()));
        _menu.Items.Add(MenuItem(L10n.Tr("menu.refresh_now"), RefreshNow));
        _menu.Items.Add(MenuItem(L10n.Tr("menu.settings"), () => ShowPanel(AppRoute.Settings)));
        _menu.Items.Add(new NativeMenuItemSeparator());
        _menu.Items.Add(MenuItem(L10n.Tr("menu.quit"), Quit));

        _tray = new TrayIcon
        {
            ToolTipText = _services.TrayTooltipText(),
            Icon = TrayIconFactory.Create(_services.TrayStatus),
            Menu = _menu,
            IsVisible = true,
        };
        _tray.Clicked += (_, _) => TogglePanel();
        TrayIcon.SetIcons(Application.Current!, new TrayIcons { _tray });

        _services.Changed += UpdateTray;
        UpdateTray();
    }

    private static NativeMenuItem MenuItem(string header, Action action)
    {
        var item = new NativeMenuItem(header);
        item.Click += (_, _) => action();
        return item;
    }

    /// <summary>每次报告 / 设置变化都更新 tooltip 和图标（错误 → 红色图标，恢复成功 → 普通图标）。</summary>
    private void UpdateTray()
    {
        void Apply()
        {
            if (_disposed) return;
            _tray.ToolTipText = _services.TrayTooltipText();
            _tray.Icon = TrayIconFactory.Create(_services.TrayStatus);
        }
        if (Dispatcher.UIThread.CheckAccess()) Apply();
        else Dispatcher.UIThread.Post(Apply);
    }

    private void TogglePanel()
    {
        if (_panel is { IsVisible: true })
        {
            _panel.Hide();
            return;
        }
        ShowPanel();
    }

    /// <summary>第二个实例启动时调用：把面板弹到最前面。</summary>
    public void ActivateFromSecondLaunch()
    {
        if (Dispatcher.UIThread.CheckAccess()) ShowPanelCore();
        else Dispatcher.UIThread.Post(() => ShowPanelCore());
    }

    private void ShowPanel(AppRoute? route = null) => ShowPanelCore(route);

    private void ShowPanelCore(AppRoute? route = null)
    {
        if (_panel is null)
        {
            _panel = new PanelWindow(_services, route: route);
            _panel.Show();
        }
        else
        {
            if (route is not null) _panel.Panel.Navigate(route);
            _panel.Show();
            _panel.PlaceAboveTray();
            _panel.Activate();
        }
        // Mac 的 MenuPanelView.onAppear → ReportStore.onPanelOpened()（超过 120 秒才刷）。
        // 可能跑 CLI：放后台，别让面板弹出来的第一帧卡住。
        Task.Run(_services.OnPanelOpened);
    }

    /// <summary>右键「Refresh」：用户主动刷新（取消待触发的防抖任务，立刻跑）。</summary>
    private void RefreshNow()
    {
        Task.Run(() =>
        {
            _services.RequestUserRefresh();
            Dispatcher.UIThread.Post(() => _panel?.Panel.Rebuild());
        });
    }

    private static void Quit()
    {
        if (Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.Shutdown();
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _services.Changed -= UpdateTray;
        _tray.IsVisible = false;
        _tray.Dispose();
    }
}
