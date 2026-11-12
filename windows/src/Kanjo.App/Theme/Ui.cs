using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.TextFormatting;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>字号 / 字重档位（对应 Mac 的 SF Pro 12 / 10.5 / 9.5 等）。</summary>
public static class Type
{
    public static FontFamily Font { get; } =
        new("Inter, -apple-system, Segoe UI, Helvetica Neue, PingFang SC, Microsoft YaHei, sans-serif");

    public static FontFamily Mono { get; } =
        new("Cascadia Mono, SF Mono, Menlo, Consolas, monospace");

    public static double Size(double size) => size;

    /// <summary>测量文本宽度（mosaic 的「绝不截断」规则用）。</summary>
    public static double MeasureWidth(string text, double fontSize, FontWeight weight = FontWeight.Normal)
    {
        var typeface = new Typeface(Font, FontStyle.Normal, weight);
        var layout = new TextLayout(
            text, typeface, fontSize,
            foreground: Brushes.Black,
            textWrapping: TextWrapping.NoWrap,
            maxWidth: double.PositiveInfinity,
            maxHeight: double.PositiveInfinity);
        return Math.Ceiling(layout.WidthIncludingTrailingWhitespace);
    }
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
        bool mono = false)
    {
        var block = new TextBlock
        {
            Text = text,
            FontSize = size,
            FontFamily = mono ? Type.Mono : Type.Font,
            FontWeight = weight ?? FontWeight.Normal,
            Foreground = foreground ?? Palette.Foreground,
            TextWrapping = wrap ? TextWrapping.Wrap : TextWrapping.NoWrap,
        };
        if (maxLines > 0) block.MaxLines = maxLines;
        return block;
    }

    public static TextBlock Secondary(string text, double size = 10.5, int maxLines = 1) =>
        Text(text, size, null, Palette.Secondary, maxLines: maxLines);

    /// <summary>小号全大写标题。</summary>
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
        VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center,
    };

    public static Border Rounded(double radius, IBrush? fill = null) => new()
    {
        CornerRadius = new CornerRadius(radius),
        Background = fill,
        ClipToBounds = true,
    };

    public static Control Spacer(double width = 0, double height = 0) => new Border { Width = width, Height = height };

    public static Control Hairline(double inset = Metrics.RowInset, double trailing = 0)
    {
        var line = new Border
        {
            Height = 1,
            Background = Palette.Separator,
            Margin = new Thickness(inset, 0, trailing, 0),
        };
        return line;
    }

    public static Button PlainButton(Control content, Action onClick, string? tip = null)
    {
        var button = new Button
        {
            Content = content,
            Background = Brushes.Transparent,
            BorderThickness = new Thickness(0),
            Padding = new Thickness(0),
            HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Left,
            VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center,
            Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Hand),
        };
        button.Click += (_, _) => onClick();
        if (!string.IsNullOrEmpty(tip)) ToolTip.SetTip(button, tip);
        return button;
    }

    /// <summary>一行：左内容 + 右侧数值（右对齐）。</summary>
    public static Grid Row(Control left, Control? right = null, double spacing = 8)
    {
        var grid = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions(right is null ? "*" : "*,Auto"),
        };
        if (right is not null)
        {
            Grid.SetColumn(right, 1);
            right.Margin = new Thickness(spacing, 0, 0, 0);
        }
        grid.Children.Add(left);
        if (right is not null) grid.Children.Add(right);
        return grid;
    }

    public static StackPanel H(double spacing = 6) => new()
    {
        Orientation = Avalonia.Layout.Orientation.Horizontal,
        Spacing = spacing,
        VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center,
    };

    public static StackPanel V(double spacing = 0) => new()
    {
        Orientation = Avalonia.Layout.Orientation.Vertical,
        Spacing = spacing,
    };
}
