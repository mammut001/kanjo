using Avalonia;
using Avalonia.Controls;
using Kanjo.App.Views;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 面板窗口：无边框、不在任务栏显示、失焦自动隐藏。
/// 托盘点击时把它放在托盘图标上方（屏幕右下角）。
/// </summary>
public sealed class PanelWindow : Window
{
    private readonly PanelView _panel;

    public PanelWindow(AppServices services, bool taskbar = false, AppRoute? route = null)
    {
        SystemDecorations = SystemDecorations.None;
        CanResize = false;
        ShowInTaskbar = taskbar;
        Topmost = !taskbar;
        WindowStartupLocation = WindowStartupLocation.Manual;
        TransparencyLevelHint =
        [
            WindowTransparencyLevel.Mica, WindowTransparencyLevel.Blur, WindowTransparencyLevel.None,
        ];
        Background = Palette.PanelBackground;
        Width = PanelView.PanelWidth;
        Height = PanelView.PanelHeight;

        _panel = new PanelView(services, route ?? AppRoute.Overview);
        Content = new Border
        {
            CornerRadius = new CornerRadius(12),
            ClipToBounds = true,
            Background = Palette.PanelBackground,
            Child = _panel,
        };

        // 点到别处自动收起（和 Mac 的菜单栏弹出面板一致）。
        Deactivated += (_, _) =>
        {
            if (!taskbar) Hide();
        };

        ProjectActions.ClipboardWriter = text => Clipboard?.SetTextAsync(text);
        KeyDown += (_, e) =>
        {
            if (_panel.FindDiskPage()?.HandleKey(e.Key) == true) e.Handled = true;
        };
    }

    public PanelView Panel => _panel;

    protected override void OnOpened(EventArgs e)
    {
        base.OnOpened(e);
        if (ShowInTaskbar) return;
        PlaceAboveTray();
    }

    /// <summary>放在工作区右下角（托盘上方），像 macOS 从菜单栏弹出。</summary>
    public void PlaceAboveTray()
    {
        var screen = Screens.ScreenFromWindow(this) ?? Screens.Primary;
        if (screen is null) return;
        var work = screen.WorkingArea;
        var scaling = screen.Scaling <= 0 ? 1 : screen.Scaling;
        var width = (int)(Width * scaling);
        var height = (int)(Height * scaling);
        var x = work.X + work.Width - width - (int)(12 * scaling);
        var y = work.Y + work.Height - height - (int)(12 * scaling);
        Position = new PixelPoint(Math.Max(work.X, x), Math.Max(work.Y, y));
    }
}
