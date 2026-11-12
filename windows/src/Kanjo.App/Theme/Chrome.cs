using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Shapes;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 按比例填充的细条（无底轨）：宽度 = 可用宽度 × <see cref="Fraction"/>，最小 3pt。
/// 对应 Swift 里 `GeometryReader { Capsule().frame(width: geo.size.width * fraction) }`。
/// 自绘（不依赖子元素的测量结果），离屏渲染也稳定。
/// </summary>
public sealed class FractionBar : Control
{
    private readonly IBrush _brush;
    private readonly double _height;

    public FractionBar(IBrush brush, double fraction = 0, double height = 3, double minWidth = 3)
    {
        _brush = brush;
        _height = height;
        MinWidth = minWidth;
        Fraction = fraction;
        Height = height;
        HorizontalAlignment = HorizontalAlignment.Stretch;
    }

    public double Fraction { get; set; }

    protected override Size MeasureOverride(Size availableSize)
    {
        var width = double.IsFinite(availableSize.Width) && availableSize.Width > 0 ? availableSize.Width : 200;
        return new Size(width, _height);
    }

    public override void Render(DrawingContext context)
    {
        var width = Bounds.Width <= 0 ? 200 : Bounds.Width;
        var filled = Math.Max(Math.Min(width * Math.Clamp(Fraction, 0, 1), width), 3);
        context.DrawRectangle(_brush, null,
            new RoundedRect(new Rect(0, 0, filled, _height), _height / 2));
    }
}

/// <summary>细进度条：浅底轨 + 彩色填充（悬停卡里的 QuotaBar）。</summary>
public sealed class QuotaBar : Control
{
    private readonly double _fraction;
    private readonly IBrush _brush;
    private readonly double _height;

    public QuotaBar(double fraction, IBrush color, double height = 4)
    {
        _fraction = Math.Clamp(fraction, 0, 1);
        _brush = color;
        _height = height;
        Height = height;
        HorizontalAlignment = HorizontalAlignment.Stretch;
    }

    protected override Size MeasureOverride(Size availableSize)
    {
        var width = double.IsFinite(availableSize.Width) && availableSize.Width > 0 ? availableSize.Width : 200;
        return new Size(width, _height);
    }

    public override void Render(DrawingContext context)
    {
        var width = Bounds.Width <= 0 ? 200 : Bounds.Width;
        var radius = _height / 2;
        context.DrawRectangle(new SolidColorBrush(Palette.ForegroundColor, 0.08), null,
            new RoundedRect(new Rect(0, 0, width, _height), radius));
        if (_fraction > 0)
        {
            var filled = Math.Max(_height, width * _fraction);
            context.DrawRectangle(_brush, null, new RoundedRect(new Rect(0, 0, filled, _height), radius));
        }
    }
}

/// <summary>转圈（rescanning / 检查中）：一圈淡底 + 一段弧，静态绘制，离屏截图也能看到。</summary>
public sealed class Spinner : Viewbox
{
    public Spinner(double size = 10, IBrush? brush = null)
    {
        Width = size;
        Height = size;
        Stretch = Stretch.Uniform;
        Child = new Avalonia.Controls.Shapes.Path
        {
            Data = Geometry.Parse("M6,1.2 A4.8,4.8 0 1 1 1.2,6"),
            Stroke = brush ?? Palette.Secondary,
            StrokeThickness = 1.6,
            StrokeLineCap = PenLineCap.Round,
        };
    }
}

public static class Chrome
{
    /// <summary>
    /// 悬停卡外观：实底 + 细描边 + 柔和阴影 + 圆角 10（HoverCardChrome）。
    /// 阴影用一层偏移的淡色圆角矩形画（Avalonia 的 BoxShadow 在离屏渲染下会吃掉子元素）。
    /// </summary>
    public static Control HoverCardChrome(Control content)
    {
        var card = new Border
        {
            Child = content,
            Padding = new Thickness(12, 10, 12, 10),
            Margin = new Thickness(0),
            CornerRadius = new CornerRadius(10),
            Background = Palette.CardBackground,
            BorderBrush = Palette.CardBorder,
            BorderThickness = new Thickness(0.5),
        };
        var shadow = new Border
        {
            CornerRadius = new CornerRadius(11),
            Background = new SolidColorBrush(Colors.Black, Palette.IsDark ? 0.32 : 0.14),
            Margin = new Thickness(1, 3, -1, -1),
            IsHitTestVisible = false,
        };
        var stack = new Panel();
        stack.Children.Add(shadow);
        stack.Children.Add(card);
        return stack;
    }

    /// <summary>分组底色卡片（groupedBackground）：淡底 + 圆角 10，没有描边。</summary>
    public static Border Group(Control content, double padding = 10) => new()
    {
        Child = content,
        Padding = new Thickness(padding),
        CornerRadius = new CornerRadius(Metrics.GroupRadius),
        Background = Palette.GroupFill,
    };

    /// <summary>一节的骨架：小号全大写标题（+ 可选右侧内容），下面是内容。`fill=false` 时不加分组底色。</summary>
    public static Control Section(string title, Control content, bool fill = true, double padding = 10,
        Control? trailing = null)
    {
        var box = new StackPanel { Orientation = Orientation.Vertical, Spacing = 6 };
        var header = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"),
        };
        var titleBlock = Kanjo.App.Ui.SectionTitle(title);
        Grid.SetColumn(titleBlock, 0);
        header.Children.Add(titleBlock);
        if (trailing is not null)
        {
            Grid.SetColumn(trailing, 2);
            header.Children.Add(trailing);
        }
        titleBlock.Margin = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 0);
        trailing?.Margin = new Thickness(0, 0, Metrics.RowInset, 0);
        box.Children.Add(header);
        var body = fill ? Group(content, padding) : content;
        box.Children.Add(body);
        return box;
    }
}
