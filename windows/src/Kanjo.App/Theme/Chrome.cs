using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 按比例填充的细条（无底轨）：宽度 = 可用宽度 × <see cref="Fraction"/>，最小 3pt。
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
        // 底轨用卡片描边色（1.5:1 以上，能看见轨道本身）。
        context.DrawRectangle(Palette.CardBorder, null,
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

/// <summary>
/// 卡片与分组的骨架（Windows 11 设置页的版式）：
/// 分组标题（BodyStrong 14、正文色、句首大写）在上，下面是若干张卡片，
/// 卡片之间 4px、分组之间 24px。卡片 = 圆角 8 + 1px 描边 + 16px 内边距。
/// </summary>
public static class Chrome
{
    /// <summary>一张卡片：圆角 8、1px 描边、16px 内边距、白 / 深灰实底。</summary>
    public static Border Card(Control content, double paddingH = Metrics.RowInset,
        double paddingV = Metrics.CardPaddingV)
    {
        return new Border
        {
            Child = content,
            Background = Palette.CardBackground,
            BorderBrush = Palette.CardBorder,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(Metrics.GroupRadius),
            Padding = new Thickness(paddingH, paddingV, paddingH, paddingV),
        };
    }

    /// <summary>没有内边距的卡片（行自己带内边距，用来做整行可点 / 可悬停）。</summary>
    public static Border CardBare(Control content) => new()
    {
        Child = content,
        Background = Palette.CardBackground,
        BorderBrush = Palette.CardBorder,
        BorderThickness = new Thickness(1),
        CornerRadius = new CornerRadius(Metrics.GroupRadius),
        ClipToBounds = true,
    };

    /// <summary>悬停卡外观：实底 + 描边 + 阴影 + 圆角 8。</summary>
    public static Control HoverCardChrome(Control content)
    {
        var card = Card(content, paddingH: 14, paddingV: 12);
        var shadow = new Border
        {
            CornerRadius = new CornerRadius(Metrics.GroupRadius + 1),
            Background = new SolidColorBrush(Colors.Black, Palette.IsDark ? 0.32 : 0.14),
            Margin = new Thickness(1, 3, -1, -1),
            IsHitTestVisible = false,
        };
        var stack = new Panel();
        stack.Children.Add(shadow);
        stack.Children.Add(card);
        return stack;
    }

    /// <summary>
    /// 一个分组：标题 + 一张卡片。`gap` 是卡片间距（默认 4）。
    /// </summary>
    public static Control Section(string title, Control content, Control? trailing = null)
    {
        var titleRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        var label = Ui.SectionTitle(title);
        label.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(label, 0);
        titleRow.Children.Add(label);
        if (trailing is not null)
        {
            trailing.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(trailing, 1);
            titleRow.Children.Add(trailing);
        }
        titleRow.Margin = new Thickness(2, 0, 2, 8);

        var box = new StackPanel { Orientation = Orientation.Vertical };
        box.Children.Add(titleRow);
        box.Children.Add(Card(content));
        return box;
    }

    /// <summary>兼容旧调用点（旧的 `fill` / `padding` 参数已无意义，一律画成卡片）。</summary>
    public static Control LegacySection(string title, Control content, bool fill = true,
        double padding = Metrics.RowInset, Control? trailing = null)
    {
        _ = fill;
        _ = padding;
        return Section(title, content, trailing);
    }
}
