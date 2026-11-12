using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Threading;
using Kanjo.App.Views;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 托盘（Windows 右下角通知区域）：tooltip 显示金额（`Kanjo · $3,057 · 30d`），图标随状态变化；
/// 左键点击弹出面板（再点一次收起），右键菜单：打开、刷新、设置、退出。
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
        _menu.Items.Add(MenuItem(L10n.Tr("menu.refresh_now"), () => RefreshNow()));
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

    private void UpdateTray()
    {
        void Apply()
        {
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

    private void ShowPanel(AppRoute? route = null)
    {
        if (_panel is null)
        {
            _panel = new PanelWindow(_services, route: route);
            _panel.Show();
            return;
        }
        _panel.Show();
        _panel.PlaceAboveTray();
        _panel.Activate();
    }

    private void RefreshNow()
    {
        Task.Run(() =>
        {
            _services.Refresh();
            Dispatcher.UIThread.Post(() => _panel?.Panel.Rebuild());
        });
    }

    private static void Quit()
    {
        if (Application.Current?.ApplicationLifetime is Avalonia.Controls.ApplicationLifetimes.IClassicDesktopStyleApplicationLifetime desktop)
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
