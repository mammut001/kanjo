using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Documents;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.TextFormatting;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>字体与字号档位（对应 Mac 的 SF Pro / Windows 的 Segoe UI Variable）。</summary>
public static class Type
{
    /// <summary>Windows 用 Segoe UI Variable（回退 Segoe UI）；macOS 开发时用系统字体。</summary>
    public static FontFamily Font { get; } = OperatingSystem.IsWindows()
        ? new FontFamily("Segoe UI Variable Text, Segoe UI, Segoe UI Variable, sans-serif")
        : new FontFamily("-apple-system, Helvetica Neue, Segoe UI, sans-serif");

    public static FontFamily Display { get; } = OperatingSystem.IsWindows()
        ? new FontFamily("Segoe UI Variable Display, Segoe UI, sans-serif")
        : new FontFamily("-apple-system, Helvetica Neue, sans-serif");

    public static FontFamily Mono { get; } =
        new(OperatingSystem.IsWindows()
            ? "Cascadia Mono, Consolas, monospace"
            : "SF Mono, Menlo, monospace");

    /// <summary>测量文本宽度（mosaic 的「绝不截断」规则用）。</summary>
    public static double MeasureWidth(string text, double fontSize, FontWeight weight = FontWeight.Normal,
        FontFamily? family = null)
    {
        var typeface = new Typeface(family ?? Font, FontStyle.Normal, weight);
        var layout = new TextLayout(
            text, typeface, fontSize,
            foreground: Brushes.Black,
            textWrapping: TextWrapping.NoWrap,
            maxWidth: double.PositiveInfinity,
            maxHeight: double.PositiveInfinity);
        return Math.Ceiling(layout.WidthIncludingTrailingWhitespace);
    }

    /// <summary>大号金额用圆体（Mac: .rounded）。Avalonia 无圆体，用 Display 字体近似。</summary>
    public static FontFamily Rounded => Display;
}

/// <summary>控件构建的小工具：让视图代码短、可读，字号 / 颜色集中在这里取。</summary>
public static class Ui
{
    public static TextBlock Text(
        string text,
        double size = 12,
        FontWeight? weight = null,
        IBrush? foreground = null,
        bool wrap = false,
        int maxLines = 0,
        bool mono = false,
        FontFamily? family = null)
    {
        var block = new TextBlock
        {
            Text = text,
            FontSize = size,
            FontFamily = family ?? (mono ? Type.Mono : Type.Font),
            FontWeight = weight ?? FontWeight.Normal,
            Foreground = foreground ?? Palette.Foreground,
            TextWrapping = wrap ? TextWrapping.Wrap : TextWrapping.NoWrap,
            // Mac 的行高比 Avalonia 默认紧一些，收紧一点才能对齐参考图的节奏。
            LineHeight = Math.Round(size * 1.2, 1),
        };
        if (maxLines > 0) block.MaxLines = maxLines;
        return block;
    }

    public static TextBlock Secondary(string text, double size = 10.5, int maxLines = 1) =>
        Text(text, size, null, Palette.Secondary, maxLines: maxLines);

    /// <summary>小号全大写标题（SectionTitle：10pt semibold，tracking 0.5）。</summary>
    public static TextBlock SectionTitle(string text)
    {
        var block = Text(text.ToUpperInvariant(), 10, FontWeight.SemiBold, Palette.Secondary);
        block.LetterSpacing = 0.5;
        return block;
    }

    /// <summary>色点。</summary>
    public static Avalonia.Controls.Shapes.Ellipse Dot(string agent, double size = 6) => new()
    {
        Width = size,
        Height = size,
        Fill = Palette.Agent(agent),
        VerticalAlignment = VerticalAlignment.Center,
    };

    public static Border Rounded(double radius, IBrush? fill = null) => new()
    {
        CornerRadius = new CornerRadius(radius),
        Background = fill,
        ClipToBounds = true,
    };

    public static Control Hairline(double leading = 0, double trailing = 0)
    {
        var line = new Border
        {
            Height = 1,
            Background = Palette.Separator,
            Margin = new Thickness(leading, 0, trailing, 0),
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        return line;
    }

    /// <summary>
    /// 可点文字（RowIconButton / 文字按钮）：无底，强调色，悬停变淡底。
    /// </summary>
    public static Clickable LinkButton(string text, Action onClick, double size = 10.5, IBrush? foreground = null) =>
        Clickable.Link(text, onClick, size, foreground);

    /// <summary>图标按钮（26×26，无底，悬停出现圆形淡底）。</summary>
    public static Clickable IconButton(Control glyph, Action onClick, string? tip = null, bool active = false) =>
        Clickable.Icon(glyph, onClick, tip, active);

    /// <summary>
    /// 多列栅格：`Row(left, right)` 用 `*,Auto`；`Columns` 用于「左内容 + 若干右对齐列」。
    /// </summary>
    public static Grid Columns(params (Control? Content, GridLength Width)[] cells)
    {
        var grid = new Grid();
        foreach (var (content, width) in cells)
        {
            grid.ColumnDefinitions.Add(new ColumnDefinition(width));
        }
        for (var i = 0; i < cells.Length; i++)
        {
            if (cells[i].Content is not { } content) continue;
            Grid.SetColumn(content, i);
            grid.Children.Add(content);
        }
        return grid;
    }

    public static Grid Row(Control left, Control? right = null) =>
        Columns((left, new GridLength(1, GridUnitType.Star)), (right, GridLength.Auto));

    public static StackPanel H(double spacing = 6) => new()
    {
        Orientation = Orientation.Horizontal,
        Spacing = spacing,
        VerticalAlignment = VerticalAlignment.Center,
    };

    public static StackPanel V(double spacing = 0) => new()
    {
        Orientation = Orientation.Vertical,
        Spacing = spacing,
    };

    public static Control Spacer() => new Panel { HorizontalAlignment = HorizontalAlignment.Stretch };

    /// <summary>
    /// 主要按钮（borderedProminent 近似）：强调色底、白字。Avalonia 的 Button 依赖模板，
    /// 离屏渲染时模板不实例化 → 用自绘的 Clickable 保证截图里也能看到。
    /// </summary>
    public static Clickable ProminentButton(string text, Action onClick, IBrush? tint = null, double size = 11.5)
    {
        var label = Text(text, size, FontWeight.SemiBold, Brushes.White);
        label.TextAlignment = TextAlignment.Center;
        var body = new Border
        {
            Child = label,
            Background = tint ?? Palette.Accent,
            CornerRadius = new CornerRadius(6),
            Padding = new Thickness(10, 4, 10, 4),
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        return new Clickable(body, onClick, radius: 6, hoverFill: false)
        {
            HorizontalAlignment = HorizontalAlignment.Left,
        };
    }

    /// <summary>次要按钮（bordered 近似）：淡底 + 细描边。</summary>
    public static Clickable BorderedButton(string text, Action onClick, bool enabled = true, double size = 11)
    {
        var label = Text(text, size, FontWeight.Normal, enabled ? Palette.Foreground : Palette.Tertiary);
        label.TextAlignment = TextAlignment.Center;
        var body = new Border
        {
            Child = label,
            Background = Palette.GroupFill,
            BorderBrush = Palette.CardBorder,
            BorderThickness = new Thickness(0.5),
            CornerRadius = new CornerRadius(6),
            Padding = new Thickness(9, 3, 9, 3),
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        var button = new Clickable(body, onClick, radius: 6, hoverFill: enabled)
        {
            HorizontalAlignment = HorizontalAlignment.Left,
            IsEnabled = enabled,
            Opacity = enabled ? 1 : 0.55,
        };
        return button;
    }

    /// <summary>行内小号文字按钮（强调色，10.5pt）。</summary>
    public static Clickable SmallLink(string text, Action onClick, bool enabled = true) =>
        new(Text(text, 10.5, null, enabled ? Palette.Accent : Palette.Tertiary), onClick, radius: 4,
            hoverFill: enabled);

    /// <summary>带 margin 的包装（省一次局部变量）。</summary>
    public static T WithMargin<T>(this T control, double left, double top, double right, double bottom)
        where T : Control
    {
        control.Margin = new Thickness(left, top, right, bottom);
        return control;
    }

    public static T WithMargin<T>(this T control, double horizontal, double vertical) where T : Control =>
        control.WithMargin(horizontal, vertical, horizontal, vertical);
}
