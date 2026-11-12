using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Platform;
using Avalonia.Media;
using Kanjo.App.Views;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 面板窗口：无边框、不在任务栏显示、失焦自动隐藏。
/// 托盘点击时把它放在托盘图标上方（屏幕右下角）。
///
/// 表面：Windows 11 有 Mica 就用 Mica（窗口背景透明，由系统画材质）；
/// Windows 10 / Server 2022 没有 Mica，退回实色 #F3F3F3 / #202020（<see cref="Palette.BackgroundColor"/>）。
/// 两种情况下内容都是卡片，视觉一致。
/// </summary>
public sealed class PanelWindow : Window
{
    private readonly PanelView _panel;
    private readonly Border _surface;

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
        // Mica 可用时这里会透出系统材质；不可用时它就是退回的实色。
        Background = Brushes.Transparent;

        Width = PanelView.PanelWidth;
        Height = PanelView.PanelHeight;

        _panel = new PanelView(services, route ?? AppRoute.Overview);
        _surface = new Border
        {
            CornerRadius = new CornerRadius(8),
            ClipToBounds = true,
            // 没有 Mica 时（Windows 10 / Server）这一层就是底：实色 + 一圈描边，边界清楚。
            Background = Palette.PanelBackground,
            BorderBrush = Palette.CardBorder,
            BorderThickness = new Thickness(1),
            Child = _panel,
        };
        Content = _surface;

        // 换外观：窗口表面那一层（没有 Mica 时的实色底 + 描边）也是构造时取色的。
        Appearance.Changed += OnAppearanceChanged;
        Closed += (_, _) => Appearance.Changed -= OnAppearanceChanged;

        // 强调色按钮只在活动窗口里是蓝的：面板弹出时算活动窗口，收起 / 失焦算非活动。
        Deactivated += (_, _) =>
        {
            WindowActivation.SetActive(false);
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
        // 面板一出现就是活动窗口（SwiftUI 的 borderedProminent 这时才是蓝的）。
        WindowActivation.SetActive(true);
        _panel.Rebuild();
        if (ShowInTaskbar) return;
        PlaceAboveTray();
        // Windows 11 的 flyout 手感：淡入 + 12px 上滑（「减少动画」时不动）。
        Motion.AnimatePanelIn(_surface);
    }

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);
        // Mica 真的套上了：把不透明的那层底去掉，让系统材质露出来。
        if (change.Property == TopLevel.ActualTransparencyLevelProperty &&
            ActualTransparencyLevel == WindowTransparencyLevel.Mica)
        {
            _surface.Background = Brushes.Transparent;
            _surface.BorderThickness = new Thickness(0);
        }
    }

    /// <summary>外观切换：没有 Mica 时那层实色底 / 描边要换成新色板（Mica 下保持透明）。</summary>
    private void OnAppearanceChanged()
    {
        if (ActualTransparencyLevel == WindowTransparencyLevel.Mica) return;
        _surface.Background = Palette.PanelBackground;
        _surface.BorderBrush = Palette.CardBorder;
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
