using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 可点区域：Border + 指针事件。不用 <see cref="Button"/>，因为它依赖控件模板，
/// 在离屏（headless 截图）渲染、没有 TopLevel 的情况下模板不会被实例化 → 整块看不见。
/// 悬停时给一层很淡的底色，和 Mac 的 .plain / IconButtonStyle 观感一致。
/// </summary>
public sealed class Clickable : Border
{
    private readonly Action _onClick;
    private readonly bool _hoverFill;
    private bool _hovered;
    private bool _pressed;

    public Clickable(Control content, Action onClick, string? tip = null, double radius = 6, bool hoverFill = true)
    {
        _onClick = onClick;
        _hoverFill = hoverFill;
        Child = content;
        CornerRadius = new CornerRadius(radius);
        Background = Brushes.Transparent;
        Cursor = new Cursor(StandardCursorType.Hand);
        if (!string.IsNullOrEmpty(tip)) ToolTip.SetTip(this, tip);

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
            _pressed = true;
            UpdateBackground();
            e.Handled = true;
        };
        PointerReleased += (_, e) =>
        {
            var wasPressed = _pressed;
            _pressed = false;
            UpdateBackground();
            if (!wasPressed) return;
            e.Handled = true;
            _onClick();
        };
    }

    private void UpdateBackground() =>
        Background = _hoverFill && (_hovered || _pressed) ? Palette.RowHover : Brushes.Transparent;

    /// <summary>文字按钮（强调色，无底）。</summary>
    public static Clickable Link(string text, Action onClick, double size = 10.5, IBrush? foreground = null) =>
        new(Ui.Text(text, size, null, foreground ?? Palette.Accent), onClick, radius: 4);

    /// <summary>图标按钮（26×26，悬停出现圆形淡底）。</summary>
    public static Clickable Icon(Control glyph, Action onClick, string? tip = null, bool active = false)
    {
        var inner = new Border
        {
            Width = 26,
            Height = 26,
            CornerRadius = new CornerRadius(13),
            Background = active ? Palette.RowHover : Brushes.Transparent,
            Child = new Panel
            {
                Width = 26,
                Height = 26,
                Children = { glyph },
            },
        };
        glyph.HorizontalAlignment = HorizontalAlignment.Center;
        glyph.VerticalAlignment = VerticalAlignment.Center;

        // 悬停高亮由外层 Clickable 负责（铺满 26×26 的圆角）。
        return new Clickable(inner, onClick, tip, radius: 13);
    }
}
