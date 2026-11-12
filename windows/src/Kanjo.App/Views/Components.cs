using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Shapes;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.TextFormatting;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>截图模式：页面交出内部内容（不含滚动容器），由面板按整页高度渲染。</summary>
public interface ISnapshotPage
{
    Control SnapshotBody { get; }
}

/// <summary>
/// 范围选择器（Fluent 胶囊）：All · Today · 7d · 30d · Last week · Since reset · Cycle。
/// 选中项是强调色填充 + 强调色上的文字；不可用的范围是禁用色文字、不可点。
///
/// 360px 的面板里 7 个胶囊一行放不下，硬挤会把「Cycle」切成「Cy」。
/// 所以这里做成**横向滚动的单行**：不显示滚动条（`ScrollBarVisibility.Hidden`），
/// 滚轮 / 触摸板 / 拖动都能挪，每个胶囊都不会被折行或截断。
/// </summary>
public sealed class RangePicker : Border
{
    public RangePicker(string rangeRaw, TimeRange effective, bool resetAvailable, bool cycleAvailable,
        Action<string> onChange)
    {
        Padding = new Thickness(3);
        CornerRadius = new CornerRadius(10);
        Background = Palette.GroupFill;
        BorderBrush = Palette.CardBorder;
        BorderThickness = new Thickness(1);
        HorizontalAlignment = HorizontalAlignment.Stretch;
        VerticalAlignment = VerticalAlignment.Center;

        // 7 个英文胶囊（All/Today/7d/30d/Last week/Since reset/Cycle）在 310px 的可用宽度里
        // 放不下（需要约 314px），所以做成**横向可滚动**的单行：不画滚动条，
        // 每个胶囊保持自然宽度、绝不折行、绝不切词，最后那个可以滚出来。
        var row = new StackPanel { Orientation = Orientation.Horizontal };
        foreach (var range in TimeRanges.All)
        {
            var selected = range == effective;
            var label = Ui.Text(range.ShortLabel(), 11, selected ? FontWeight.SemiBold : FontWeight.Normal,
                selected ? Palette.ContrastOn(Palette.Accent) : Palette.Secondary, maxLines: 1);
            var chip = new Border
            {
                CornerRadius = new CornerRadius(7),
                Padding = new Thickness(5, 4, 5, 4),
                Background = selected ? Palette.Accent : Brushes.Transparent,
                Child = label,
                VerticalAlignment = VerticalAlignment.Center,
            };

            var unavailable = Unavailable(range, resetAvailable, cycleAvailable);
            if (unavailable is not null)
            {
                label.Foreground = Palette.Disabled;
                ToolTip.SetTip(chip, unavailable);
            }
            else
            {
                ToolTip.SetTip(chip, range.LongLabel());
                chip.PointerReleased += (_, _) => onChange(range.RawValue());
                chip.PointerEntered += (_, _) =>
                {
                    if (!selected) chip.Background = Palette.RowHover;
                };
                chip.PointerExited += (_, _) =>
                {
                    if (!selected) chip.Background = Brushes.Transparent;
                };
            }
            row.Children.Add(chip);
        }

        // ScrollViewer 明确 Stretch + 左对齐内容：视口跟父级宽度走（不按内容撑宽），
        // 内容更宽时出现横向滚动（滚动条隐藏，滚轮 / 触摸板 / 拖动都能挪）。
        var scroller = new ScrollViewer
        {
            Content = row,
            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Hidden,
            VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            VerticalAlignment = VerticalAlignment.Stretch,
            HorizontalContentAlignment = HorizontalAlignment.Left,
            VerticalContentAlignment = VerticalAlignment.Center,
            Background = Brushes.Transparent,
            BorderThickness = new Thickness(0),
            Padding = new Thickness(0),
            IsScrollChainingEnabled = false,
            MinWidth = 0,
        };

        // 视口右缘的淡出：内容还有没滚出来的部分时，最后一个胶囊是「渐隐」而不是
        // 「被切掉半个词」。这是横向滚动的标准提示，也满足「不能切在词中间」。
        var fade = new Border
        {
            Width = 18,
            HorizontalAlignment = HorizontalAlignment.Right,
            IsHitTestVisible = false,
            IsVisible = false,
            Background = new LinearGradientBrush
            {
                StartPoint = new RelativePoint(0, 0.5, RelativeUnit.Relative),
                EndPoint = new RelativePoint(1, 0.5, RelativeUnit.Relative),
                GradientStops =
                {
                    new GradientStop(Color.FromArgb(0, 247, 247, 247), 0),
                    new GradientStop(Palette.GroupFillColor, 1),
                },
            },
        };
        void UpdateFade()
        {
            var more = Math.Max(0, scroller.Extent.Width - scroller.Viewport.Width);
            fade.IsVisible = more > 0.5 && scroller.Offset.X < more - 0.5;
        }
        scroller.ScrollChanged += (_, _) => UpdateFade();
        scroller.PropertyChanged += (_, e) =>
        {
            if (e.Property == ScrollViewer.ExtentProperty || e.Property == ScrollViewer.ViewportProperty)
                UpdateFade();
        };

        Child = new Panel { Children = { scroller, fade } };
        MinHeight = 34;
    }

    /// <summary>测试 / 调试用：胶囊那一行的横向滚动条（内容放不下时可滚到最后一个）。</summary>
    public ScrollViewer? PillsScroller => (Child as Panel)?.Children.OfType<ScrollViewer>().FirstOrDefault();

    private static string? Unavailable(TimeRange r, bool resetAvailable, bool cycleAvailable)
    {
        if (r == TimeRange.SinceReset && !resetAvailable) return L10n.Tr("timerange.tooltip.no_reset_info");
        if (r == TimeRange.BillingCycle && !cycleAvailable) return L10n.Tr("timerange.tooltip.no_subscription_info");
        return null;
    }
}

/// <summary>范围说明行：caption 字号、次要色、可折行。</summary>
public sealed class RangeCaptionLine : StackPanel
{
    public RangeCaptionLine(RangeCaptionResult caption)
    {
        Orientation = Orientation.Horizontal;
        Spacing = 4;
        VerticalAlignment = VerticalAlignment.Center;
        Children.Add(Icons.Calendar(10, Palette.Secondary));
        Children.Add(Ui.Text(caption.Text, 12, null, Palette.Secondary, wrap: true));
        if (!string.IsNullOrEmpty(caption.Help)) ToolTip.SetTip(this, caption.Help);
    }
}

/// <summary>
/// 8 周燃烧热力条：每格一周（周一到周日）。
/// 每格按那周各 agent 的 cost 份额纵向分成最多 3 段色带（上到下按 cost 降序，份额 &lt; 10% 的并进最大那段），
/// 段间不留缝；整格深浅按该周花费 / 8 周最大周花费分 5 档（opacity 作用在整格上），0 档是中性底。
/// </summary>
public sealed class HeatStripView : StackPanel
{
    /// <summary>档位 1…4 的不透明度；0 档用中性 8% 底色。</summary>
    private static readonly double[] Opacities = [0, 0.3, 0.52, 0.76, 1];

    public const double DefaultCellWidth = 8;
    public const double DefaultCellHeight = 16;
    public const double DefaultSpacing = 2;

    public HeatStripView(
        IReadOnlyList<WeekCost> weeks,
        string currency = "USD",
        IReadOnlyDictionary<string, string>? agentLabels = null,
        double cellWidth = DefaultCellWidth,
        double cellHeight = DefaultCellHeight,
        double radius = 2,
        double spacing = DefaultSpacing,
        string? idPrefix = null)
    {
        Orientation = Orientation.Horizontal;
        Spacing = spacing;
        HorizontalAlignment = HorizontalAlignment.Right;
        VerticalAlignment = VerticalAlignment.Center;

        var labels = agentLabels ?? new Dictionary<string, string>();
        var peak = weeks.Count == 0 ? 0 : weeks.Max(w => w.Cost);
        for (var i = 0; i < weeks.Count; i++)
        {
            var cell = Cell(weeks[i], HeatStrip.Level(weeks[i].Cost, peak), cellWidth, cellHeight, radius,
                currency, labels);
            if (idPrefix is not null)
            {
                var week = weeks[i];
                var copy = labels;
                HoverLayer.Attach(cell, $"{idPrefix}:{i}",
                    () => HoverCards.AgentRows(HeatStrip.WeekLabel(week.Start), null, week.Cost, week.Tokens,
                        currency, HoverCardRowBuilder.AgentRows(week.RankedWithTokens.Select(t =>
                            (t.Agent, copy.GetValueOrDefault(t.Agent) ?? AgentColors.Label(t.Agent), t.Cost,
                                t.Tokens)))));
            }
            Children.Add(cell);
        }
    }

    /// <summary>整条宽度（行里用来给悬停按钮留位置）。</summary>
    public static double WidthFor(int weeks, double cellWidth = DefaultCellWidth, double spacing = DefaultSpacing) =>
        weeks * cellWidth + Math.Max(weeks - 1, 0) * spacing;

    private static Control Cell(WeekCost week, int level, double width, double height, double radius,
        string currency, IReadOnlyDictionary<string, string> labels)
    {
        var segments = HeatStrip.Segments(week);
        var shape = new HeatStripCell(
            level <= 0 || segments.Count == 0
                ? null
                : segments.Select(s => (Palette.AgentColor(s.Agent), s.Share)).ToList(),
            Opacities[Math.Clamp(level, 0, Opacities.Length - 1)],
            width, height, radius);

        ToolTip.SetTip(shape, TooltipBuilder.WeekTooltip(
            HeatStrip.WeekLabel(week.Start), week.Cost, week.Tokens, week.ByAgent, week.ByAgentTokens,
            labels, currency));
        return shape;
    }
}

/// <summary>
/// 热力条的一格：按 Swift 的 ZStack(alignment: .top) 叠色带 —— 第 i 段矩形高度 = 该段与上方各段份额之和，
/// 从下往上画（后面的盖住前面的），整格最后裁成圆角并按档位透明度绘制。
/// 直接自绘（而不是摆子控件）：Avalonia 的 Panel 里子矩形都铺在顶部，会互相覆盖出错误的颜色。
/// </summary>
public sealed class HeatStripCell : Control
{
    private readonly IReadOnlyList<(Color Color, double Share)>? _bands;
    private readonly double _opacity;
    private readonly double _radius;

    public HeatStripCell(IReadOnlyList<(Color Color, double Share)>? bands, double opacity,
        double width, double height, double radius)
    {
        _bands = bands;
        _opacity = bands is null ? 1 : opacity;
        _radius = radius;
        Width = width;
        Height = height;
    }

    public override void Render(DrawingContext context)
    {
        var width = Bounds.Width;
        var height = Bounds.Height;
        if (width <= 0 || height <= 0) return;

        if (_bands is not { Count: > 0 } bands)
        {
            context.DrawRectangle(Palette.HeatEmpty, null,
                new RoundedRect(new Rect(0, 0, width, height), _radius));
            return;
        }

        // 份额换算成累计高度（第 i 段到顶部的距离），再从下往上把每段的可见区域填满。
        // 颜色提前和面板底色混合（等价于 Swift 的 compositingGroup + opacity）：
        // 自绘时逐块 PushOpacity 会和下面的色带叠加，颜色会明显变暗变脏。
        var background = ((ISolidColorBrush)Palette.PanelBackground).Color;
        var cumulative = 0.0;
        var heights = new double[bands.Count];
        for (var i = 0; i < bands.Count; i++)
        {
            cumulative += bands[i].Share;
            heights[i] = i == bands.Count - 1 ? height : height * cumulative;
        }
        using (context.PushClip(new RoundedRect(new Rect(0, 0, width, height), _radius)))
        {
            for (var i = bands.Count - 1; i >= 0; i--)
            {
                var top = i > 0 ? heights[i - 1] : 0;
                var bottom = heights[i];
                var color = Blend(bands[i].Color, background, _opacity);
                context.DrawRectangle(new SolidColorBrush(color), null,
                    new Rect(0, top, width, Math.Max(bottom - top, 0.5)));
            }
        }
    }

    /// <summary>把颜色按不透明度压到底色上（和 Swift 的 group opacity 结果一致）。</summary>
    private static Color Blend(Color color, Color background, double opacity)
    {
        byte Channel(byte fg, byte bg) =>
            (byte)Math.Clamp(Math.Round(fg * opacity + bg * (1 - opacity)), 0, 255);
        return Color.FromRgb(Channel(color.R, background.R), Channel(color.G, background.G),
            Channel(color.B, background.B));
    }
}

/// <summary>
/// 单行、中部省略的文字（Swift 的 `truncationMode(.middle)`）。Avalonia 的 TextTrimming 只有尾部省略，
/// 所以这里按可用宽度二分出「前缀…后缀」再自绘。
/// </summary>
public sealed class MiddleTruncatedText : Control
{
    private const string Ellipsis = "\u2026";

    private readonly string _text;
    private readonly double _size;
    private readonly IBrush _foreground;
    private readonly FontFamily _family;
    private string? _fitted;
    private double _fittedWidth = -1;

    public MiddleTruncatedText(string text, double size, IBrush? foreground = null,
        FontFamily? family = null, FontWeight? weight = null)
    {
        _text = text;
        _size = size;
        _foreground = foreground ?? Palette.Foreground;
        _family = family ?? Type.Mono;
        FontWeight = weight ?? FontWeight.Normal;
    }

    public FontWeight FontWeight { get; }

    public TextDecorationCollection? TextDecorations { get; set; }

    private double LineHeight => Math.Round(_size * 1.2, 1);

    protected override Size MeasureOverride(Size availableSize)
    {
        var full = Type.MeasureWidth(_text, _size, FontWeight, _family);
        var width = double.IsFinite(availableSize.Width) && availableSize.Width > 0
            ? Math.Min(full, availableSize.Width)
            : full;
        return new Size(width, LineHeight);
    }

    public override void Render(DrawingContext context)
    {
        var width = Bounds.Width;
        if (width <= 0 || _text.Length == 0) return;

        if (_fitted is null || Math.Abs(_fittedWidth - width) > 0.5)
        {
            _fitted = Fit(width);
            _fittedWidth = width;
        }
        if (_fitted.Length == 0) return;

        var layout = new TextLayout(_fitted,
            new Typeface(_family, FontStyle.Normal, FontWeight), _size, _foreground,
            TextAlignment.Left, TextWrapping.NoWrap, TextTrimming.None,
            maxWidth: double.PositiveInfinity, maxHeight: LineHeight);
        using (context.PushTransform(Matrix.CreateTranslation(0,
                   Math.Max((Bounds.Height - layout.Height) / 2, 0))))
        {
            layout.Draw(context, new Point(0, 0));
            if (TextDecorations is { Count: > 0 })
            {
                var pen = new Pen(_foreground, Math.Max(_size / 14, 0.8));
                context.DrawLine(pen, new Point(0, layout.Height * 0.62),
                    new Point(layout.Width, layout.Height * 0.62));
            }
        }
    }

    /// <summary>能塞进 <paramref name="width"/> 的最长「前段…后段」。</summary>
    private string Fit(double width)
    {
        double Measure(string s) => Type.MeasureWidth(s, _size, FontWeight, _family);
        if (Measure(_text) <= width) return _text;

        var best = Ellipsis;
        // 二分保留的总字符数，再按 2:1 分给前段和后段（后缀更重要：路径尾部是文件名/目录名）。
        var lo = 0;
        var hi = _text.Length;
        while (lo <= hi)
        {
            var keep = (lo + hi) / 2;
            var head = Math.Max(keep - keep / 3, 0);
            var tail = keep - head;
            var candidate = _text[..head] + Ellipsis + _text[(_text.Length - tail)..];
            if (Measure(candidate) <= width)
            {
                best = candidate;
                lo = keep + 1;
            }
            else
            {
                hi = keep - 1;
            }
        }
        return best;
    }
}

/// <summary>
/// 总览的马赛克：每个项目一块，面积 = 花费，颜色 = 主力 agent（全饱和）。
/// 布局与合并逻辑在 <see cref="MosaicLayout"/>（Core），这里只负责画。
/// </summary>
public sealed class MosaicView : Panel
{
    public MosaicView(IReadOnlyList<Project> projects, double width, string currency = "USD",
        IReadOnlyDictionary<string, string>? agentLabels = null)
    {
        Width = width;
        Height = MosaicLayout.DefaultHeight;
        ClipToBounds = false;
        _ = agentLabels;

        var tiles = MosaicLayout.Build(projects, width);
        for (var i = 0; i < tiles.Count; i++)
        {
            Children.Add(TileView(tiles[i], currency, i));
        }
    }

    private static Control TileView(MosaicLayout.Tile tile, string currency, int index)
    {
        var baseColor = tile.AgentKey is { } agent
            ? Palette.AgentColor(agent)
            : ((ISolidColorBrush)Palette.Neutral).Color;
        // 标签文字与色块一起决定：必要时把色块朝反方向微调一两个百分点，保证文字 ≥ 4.5:1。
        var ink = Palette.TileInk(baseColor, out var color);

        var shape = new Border
        {
            Width = tile.Rect.Width,
            Height = tile.Rect.Height,
            CornerRadius = new CornerRadius((double)MosaicLayout.CornerRadius),
            Background = new SolidColorBrush(color),
            ClipToBounds = true,
            Margin = new Thickness(tile.Rect.X, tile.Rect.Y, 0, 0),
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Top,
        };

        var label = Label(tile, currency, ink);
        if (label is not null) shape.Child = label;

        ToolTip.SetTip(shape, tile.Tooltip(currency));
        if (tile.Project is { } project)
        {
            var captured = project;
            // 色块可点，但光标仍是箭头（Windows 只在链接上用手型）。
            HoverLayer.Attach(shape, $"overview:tile:{index}",
                () => HoverCards.AgentRows(captured.Name, null, captured.Cost, captured.Tokens.Total, currency,
                    HoverCardRowBuilder.AgentRows(captured.ByAgent.Select(a =>
                        (a.Agent, a.Label, a.Cost, a.Tokens.Total)))));
        }
        return shape;
    }

    /// <summary>
    /// 方块左上角的名字和金额。规则（绝不截断、不出现省略号）：
    /// 宽 ≥ 72 且高 ≥ 40：名字 + 金额；宽 ≥ 72 但高 &lt; 40：只画名字；更小：什么都不画。
    /// 文字颜色按色块亮度逐块选（白或近黑），保证 ≥ 4.5:1 —— 旧的固定 92% 白在小方块上读不出来。
    /// </summary>
    private static Control? Label(MosaicLayout.Tile tile, string currency, Color inkColor)
    {
        var amount = Fmt.Money(tile.Cost, currency);
        var fit = MosaicLayout.FitLabel(
            tile.Names, amount, tile.Rect.Width, tile.Rect.Height,
            s => Type.MeasureWidth(s, 11, FontWeight.SemiBold),
            s => Type.MeasureWidth(s, 10, FontWeight.Normal));
        if (fit.Name is null) return null;

        var ink = new SolidColorBrush(inkColor);

        var box = new StackPanel
        {
            Orientation = Orientation.Vertical,
            Spacing = 1,
            Margin = new Thickness(6, 5, 0, 0),
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Top,
        };
        box.Children.Add(Ui.Text(fit.Name, 12, FontWeight.SemiBold, ink));
        if (fit.ShowAmount)
        {
            box.Children.Add(Ui.Text(amount, 12, FontWeight.Normal, ink));
        }
        return box;
    }
}
