using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Documents;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.TextFormatting;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 字号档位（Windows 11 的 type ramp）：Title 28 / Subtitle 20 / BodyStrong 14 / Body 14 / Caption 12。
/// 字体在 Windows 上是 Segoe UI Variable（回退 Segoe UI），macOS 上（开发 / 截图）用系统字体。
/// </summary>
public static class Type
{
    public static FontFamily Font { get; } = OperatingSystem.IsWindows()
        ? new FontFamily("Segoe UI Variable Text, Segoe UI, Segoe UI Variable, sans-serif")
        : new FontFamily("-apple-system, Segoe UI, Helvetica Neue, sans-serif");

    public static FontFamily Display { get; } = OperatingSystem.IsWindows()
        ? new FontFamily("Segoe UI Variable Display, Segoe UI, sans-serif")
        : new FontFamily("-apple-system, Segoe UI, Helvetica Neue, sans-serif");

    public static FontFamily Mono { get; } =
        new(OperatingSystem.IsWindows()
            ? "Cascadia Mono, Consolas, monospace"
            : "SF Mono, Menlo, Consolas, monospace");

    // 档位常量：视图里只写 Role，不写数字。
    public const double TitleSize = 28;
    public const double SubtitleSize = 20;
    public const double BodyStrongSize = 14;
    public const double BodySize = 14;
    public const double CaptionSize = 12;

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

    /// <summary>大号金额用 Display 字体（Windows 11 的数字标题感）。</summary>
    public static FontFamily Rounded => Display;
}

/// <summary>控件构建的小工具：让视图代码短、可读，字号 / 颜色集中在这里取。</summary>
public static class Ui
{
    public static TextBlock Text(
        string text,
        double size = Type.BodySize,
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
            // Segoe UI Variable 的行高比默认紧一点，收紧到 1.35 倍才像 Windows 11。
            LineHeight = Math.Round(size * 1.35, 1),
        };
        if (maxLines > 0) block.MaxLines = maxLines;
        return block;
    }

    /// <summary>页面标题（Title 28 semibold）。</summary>
    public static TextBlock Title(string text, double size = Type.TitleSize) =>
        Text(text, size, FontWeight.SemiBold, family: Type.Display);

    /// <summary>次级标题（Subtitle 20 semibold）。</summary>
    public static TextBlock Subtitle(string text) =>
        Text(text, Type.SubtitleSize, FontWeight.SemiBold, family: Type.Display);

    /// <summary>分组标题（BodyStrong 14 semibold、正文色、句首大写）——替代旧的全大写灰标题。</summary>
    public static TextBlock SectionTitle(string text) =>
        Text(text, Type.BodyStrongSize, FontWeight.SemiBold);

    /// <summary>次要文字（Caption 12）。</summary>
    public static TextBlock Secondary(string text, double size = Type.CaptionSize, int maxLines = 1) =>
        Text(text, size, null, Palette.Secondary, maxLines: maxLines);

    /// <summary>说明 / 脚注（Caption 12、三级色，可折行）。</summary>
    public static TextBlock Caption(string text, int maxLines = 0) =>
        Text(text, Type.CaptionSize, null, Palette.Tertiary, wrap: maxLines == 0, maxLines: maxLines);

    /// <summary>色点。</summary>
    public static Avalonia.Controls.Shapes.Ellipse Dot(string agent, double size = 8) => new()
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

    /// <summary>1px 分割线（卡片描边色，看得见）。</summary>
    public static Control Hairline(double leading = 0, double trailing = 0) => new Border
    {
        Height = 1,
        Background = Palette.Separator,
        Margin = new Thickness(leading, 0, trailing, 0),
        HorizontalAlignment = HorizontalAlignment.Stretch,
    };

    /// <summary>可点文字（链接）：强调色 + 手型光标（只有链接给手型）。</summary>
    public static Clickable LinkButton(string text, Action onClick, double size = Type.BodySize,
        IBrush? foreground = null) =>
        Clickable.Link(text, onClick, size, foreground);

    /// <summary>图标按钮（32×32，悬停出现圆角淡底）。</summary>
    public static Clickable IconButton(Control glyph, Action onClick, string? tip = null, bool active = false) =>
        Clickable.Icon(glyph, onClick, tip, active);

    /// <summary>
    /// 多列栅格：`Row(left, right)` 用 `*,Auto`；`Columns` 用于「左内容 + 若干右对齐列」。
    /// </summary>
    public static Grid Columns(params (Control? Content, GridLength Width)[] cells)
    {
        var grid = new Grid();
        foreach (var (_, width) in cells)
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
    /// 主按钮：Fluent 的 Accent Button（强调色底 + 强调色上的正文色）。
    /// 用真正的 <see cref="Button"/>，WinUI 主题自带悬停 / 按下三态；
    /// 禁用态换成静态的灰按钮（Fluent 的禁用强调按钮几乎看不见）。
    /// </summary>
    public static Control AccentButton(string text, Action onClick, bool enabled = true,
        double size = Type.BodySize)
    {
        if (!enabled) return DisabledButton(text, size);
        var button = new Button
        {
            Content = text,
            FontSize = size,
            FontWeight = FontWeight.SemiBold,
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Center,
            // WinUI 的强调按钮：背景 / 前景 / 边框都由主题的 accent 资源决定，
            // 这里显式绑定我们的强调色，保证系统强调色 / 深色主题下都对。
            Background = Palette.Accent,
            Foreground = Palette.OnAccent,
            BorderBrush = Palette.Accent,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(4),
            Padding = new Thickness(16, 6, 16, 6),
            MinHeight = 32,
        };
        button.Click += (_, _) => onClick();
        return button;
    }

    /// <summary>
    /// 标准按钮：Fluent 的 Standard Button（浅底 + 1px 描边）。
    /// 禁用态不用 Fluent 模板自己的样子：那是 #CCCCCC 底 + 75% 透明字（约 2.7:1，用户报的
    /// 「Apply / Reset 几乎看不见」就是它）。这里直接画一个静态的禁用外观，对比度由 Palette 保证。
    /// </summary>
    public static Control StandardButton(string text, Action onClick, bool enabled = true,
        double size = Type.BodySize)
    {
        if (!enabled) return DisabledButton(text, size);

        var button = new Button
        {
            Content = text,
            FontSize = size,
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Center,
            Background = Palette.ControlFill,
            Foreground = Palette.Foreground,
            BorderBrush = new SolidColorBrush(Palette.CardStrokeColor),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(4),
            Padding = new Thickness(14, 6, 14, 6),
            MinHeight = 32,
        };
        button.Click += (_, _) => onClick();
        return button;
    }

    /// <summary>禁用按钮的静态外观（浅底 + 3:1 以上的灰字与灰描边，不可点）。</summary>
    public static Border DisabledButton(string text, double size = Type.BodySize)
    {
        var label = Text(text, size, null, Palette.Disabled);
        label.TextAlignment = TextAlignment.Center;
        label.VerticalAlignment = VerticalAlignment.Center;
        return new Border
        {
            Child = label,
            Background = Palette.DisabledFill,
            BorderBrush = Palette.DisabledStroke,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(4),
            Padding = new Thickness(14, 6, 14, 6),
            MinHeight = 32,
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Center,
            IsEnabled = false,
        };
    }

    /// <summary>兼容旧调用点：主要按钮。</summary>
    public static Control ProminentButton(string text, Action onClick, double size = Type.BodySize) =>
        AccentButton(text, onClick, size: size);

    public static Control ProminentButton(string text, Action onClick, bool enabled, IBrush? tint = null,
        double size = Type.BodySize)
    {
        if (!enabled) return DisabledButton(text, size);
        if (tint is null) return AccentButton(text, onClick, size: size);
        var button = (Button)AccentButton(text, onClick, size: size);
        button.Background = tint;
        button.BorderBrush = tint;
        button.Foreground = Palette.ContrastOn(tint);
        return button;
    }

    /// <summary>兼容旧调用点：次要按钮。</summary>
    public static Control BorderedButton(string text, Action onClick, bool enabled = true,
        double size = Type.BodySize) => StandardButton(text, onClick, enabled, size);

    /// <summary>行内小号文字按钮（链接着色，11pt ≈ Caption）。</summary>
    public static Clickable SmallLink(string text, Action onClick, bool enabled = true) =>
        new(Text(text, 11, null, enabled ? Palette.Link : Palette.Disabled), onClick, radius: 4,
            hoverFill: enabled, hand: enabled);

    /// <summary>输入框 + 输入框本身（Fluent TextBox，占位符走 Watermark）。</summary>
    public sealed record TextInput(TextBox Box, Grid Root);

    /// <summary>
    /// Fluent 输入框（WinUI 的 TextBox）：圆角 4、1px 描边。
    /// 占位符自己画：主题自带的 Watermark 用的是极淡的 tertiary 色（白卡上约 1.9:1，用户报了
    /// 「占位符看不见」），这里换成 Palette.Secondary 的实色，对比度 6.6:1。
    /// </summary>
    public static TextInput TextField(string? text, string? placeholder, bool mono = false,
        double? width = null, bool password = false)
    {
        var box = new TextBox
        {
            Text = text ?? "",
            FontSize = Type.CaptionSize,
            MinHeight = 32,
            Padding = new Thickness(10, 5, 10, 5),
            FontFamily = mono ? Type.Mono : Type.Font,
            CornerRadius = new CornerRadius(4),
            Background = Palette.ControlFill,
            BorderBrush = new SolidColorBrush(Palette.CardStrokeColor),
            BorderThickness = new Thickness(1),
            VerticalContentAlignment = VerticalAlignment.Center,
        };
        if (password) box.PasswordChar = '•';
        if (width is { } w) box.Width = w;

        var root = new Grid();
        root.Children.Add(box);
        if (string.IsNullOrEmpty(placeholder)) return new TextInput(box, root);

        var hint = Text(placeholder, Type.CaptionSize, null, Palette.Secondary, maxLines: 1, mono: mono);
        // 左缘和 TextBox 里的正文对齐（10 内边距 + 1 描边）。
        hint.Margin = new Thickness(11, 0, 11, 0);
        hint.VerticalAlignment = VerticalAlignment.Center;
        hint.IsHitTestVisible = false;
        hint.IsVisible = string.IsNullOrEmpty(box.Text);
        box.TextChanged += (_, _) => hint.IsVisible = string.IsNullOrEmpty(box.Text);
        root.Children.Add(hint);
        return new TextInput(box, root);
    }

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
