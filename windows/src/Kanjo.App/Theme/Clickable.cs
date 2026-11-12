using Avalonia;
using Avalonia.Animation;
using Avalonia.Animation.Easings;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;
using Avalonia.Styling;

namespace Kanjo.App;

/// <summary>
/// 可点区域：Border + 指针事件（不用 <see cref="Button"/>，因为行本身要自由排版）。
/// 悬停 / 按下各给一层很淡的中性填充，用 90ms 的过渡（≤100ms，Windows 11 的手感）。
/// 光标默认是箭头 —— Windows 只在链接上用小手，列表行 / 按钮都是普通箭头。
/// </summary>
public sealed class Clickable : Border
{
    private readonly Action _onClick;
    private readonly bool _hoverFill;
    private bool _hovered;
    private bool _pressed;

    public Clickable(Control content, Action onClick, string? tip = null, double radius = 6, bool hoverFill = true,
        bool hand = false)
    {
        _onClick = onClick;
        _hoverFill = hoverFill;
        Child = content;
        CornerRadius = new CornerRadius(radius);
        Background = Brushes.Transparent;
        Cursor = hand
            ? new Cursor(StandardCursorType.Hand)
            : new Cursor(StandardCursorType.Arrow);
        if (!string.IsNullOrEmpty(tip)) ToolTip.SetTip(this, tip);

        // 过渡只作用在 Background 上：90ms 的线性淡入，和 WinUI 的悬停一致。
        Transitions = new Transitions
        {
            new BrushTransition
            {
                Property = BackgroundProperty,
                Duration = TimeSpan.FromMilliseconds(Metrics.StateTransitionMilliseconds),
                Easing = new LinearEasing(),
            },
        };

        PointerEntered += (_, _) =>
        {
            _hovered = true;
            UpdateBackground();
        };
        PointerExited += (_, _) =>
        {
            _hovered = false;
            _pressed = false;
            UpdateBackground();
        };
        PointerPressed += (_, e) =>
        {
            if (!IsEnabled) return;
            _pressed = true;
            UpdateBackground();
            e.Handled = true;
        };
        PointerReleased += (_, e) =>
        {
            var wasPressed = _pressed;
            _pressed = false;
            UpdateBackground();
            if (!wasPressed || !IsEnabled) return;
            e.Handled = true;
            _onClick();
        };
    }

    private void UpdateBackground()
    {
        if (!_hoverFill) return;
        Background = _pressed ? Palette.RowPressed : _hovered ? Palette.RowHover : Brushes.Transparent;
    }

    /// <summary>文字链接（强调色 + 手型光标）。</summary>
    public static Clickable Link(string text, Action onClick, double size = Type.BodySize,
        IBrush? foreground = null) =>
        new(Ui.Text(text, size, null, foreground ?? Palette.Link), onClick, radius: 4, hand: true);

    /// <summary>图标按钮（32×32，悬停出现圆角淡底）。</summary>
    public static Clickable Icon(Control glyph, Action onClick, string? tip = null, bool active = false)
    {
        var inner = new Border
        {
            Width = 32,
            Height = 32,
            CornerRadius = new CornerRadius(6),
            Background = active ? Palette.AccentSubtle : Brushes.Transparent,
            Child = new Panel
            {
                Width = 32,
                Height = 32,
                Children = { glyph },
            },
        };
        glyph.HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Center;
        glyph.VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center;

        // 悬停高亮由外层 Clickable 负责（铺满 32×32 的圆角）。
        return new Clickable(inner, onClick, tip, radius: 6);
    }
}
