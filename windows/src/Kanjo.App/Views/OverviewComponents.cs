using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Shapes;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

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
        double spacing = DefaultSpacing)
    {
        Orientation = Orientation.Horizontal;
        Spacing = spacing;
        HorizontalAlignment = HorizontalAlignment.Right;
        VerticalAlignment = VerticalAlignment.Center;

        var labels = agentLabels ?? new Dictionary<string, string>();
        var peak = weeks.Count == 0 ? 0 : weeks.Max(w => w.Cost);
        for (var i = 0; i < weeks.Count; i++)
        {
            Children.Add(Cell(weeks[i], HeatStrip.Level(weeks[i].Cost, peak), cellWidth, cellHeight, radius,
                currency, labels));
        }
    }

    /// <summary>整条宽度（行里用来给悬停按钮留位置）。</summary>
    public static double WidthFor(int weeks, double cellWidth = DefaultCellWidth, double spacing = DefaultSpacing) =>
        weeks * cellWidth + Math.Max(weeks - 1, 0) * spacing;

    private static Control Cell(WeekCost week, int level, double width, double height, double radius,
        string currency, IReadOnlyDictionary<string, string> labels)
    {
        var shape = new Border
        {
            Width = width,
            Height = height,
            CornerRadius = new CornerRadius(radius),
            ClipToBounds = true,
            Background = Palette.HeatEmpty,
        };

        var segments = HeatStrip.Segments(week);
        if (level > 0 && segments.Count > 0)
        {
            // 从下往上叠：每段高度 = 它和它上面各段的份额之和，顶端对齐。
            // 互相覆盖而不是并排，避免小数高度在段间漏出缝。
            var stack = new Panel { Width = width, Height = height, ClipToBounds = true };
            var cumulative = new double[segments.Count];
            var running = 0.0;
            for (var i = 0; i < segments.Count; i++)
            {
                running += segments[i].Share;
                cumulative[i] = running;
            }
            for (var i = segments.Count - 1; i >= 0; i--)
            {
                var h = i == segments.Count - 1 ? height : height * cumulative[i];
                var band = new Rectangle
                {
                    Fill = Palette.Agent(segments[i].Agent),
                    Width = width,
                    Height = h,
                    HorizontalAlignment = HorizontalAlignment.Left,
                    VerticalAlignment = VerticalAlignment.Top,
                };
                stack.Children.Add(band);
            }
            stack.Opacity = Opacities[Math.Clamp(level, 0, Opacities.Length - 1)];
            shape.Child = stack;
        }

        ToolTip.SetTip(shape, TooltipBuilder.WeekTooltip(
            HeatStrip.WeekLabel(week.Start), week.Cost, week.Tokens, week.ByAgent, week.ByAgentTokens,
            labels, currency));
        return shape;
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

        foreach (var tile in MosaicLayout.Build(projects, width))
        {
            Children.Add(TileView(tile, currency));
        }
    }

    private static Control TileView(MosaicLayout.Tile tile, string currency)
    {
        var color = tile.AgentKey is { } agent
            ? Palette.AgentColor(agent)
            : ((ISolidColorBrush)Palette.Neutral).Color;

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

        var label = Label(tile, currency);
        if (label is not null) shape.Child = label;

        ToolTip.SetTip(shape, tile.Tooltip(currency));
        return shape;
    }

    /// <summary>
    /// 方块左上角的名字和金额。规则（绝不截断、不出现省略号）：
    /// 宽 ≥ 72 且高 ≥ 40：名字 + 金额；宽 ≥ 72 但高 &lt; 40：只画名字；更小：什么都不画。
    /// </summary>
    private static Control? Label(MosaicLayout.Tile tile, string currency)
    {
        var amount = Fmt.Money(tile.Cost, currency);
        var fit = MosaicLayout.FitLabel(
            tile.Names, amount, tile.Rect.Width, tile.Rect.Height,
            s => Type.MeasureWidth(s, 11, FontWeight.SemiBold),
            s => Type.MeasureWidth(s, 10, FontWeight.Normal, Type.Mono));
        if (fit.Name is null) return null;

        var box = new StackPanel
        {
            Orientation = Orientation.Vertical,
            Spacing = 1,
            Margin = new Thickness(6, 5, 0, 0),
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Top,
        };
        box.Children.Add(Ui.Text(fit.Name, 11, FontWeight.SemiBold, Palette.OnTile));
        if (fit.ShowAmount)
        {
            box.Children.Add(Ui.Text(amount, 10, FontWeight.Normal, Palette.OnTile, mono: true));
        }
        return box;
    }
}
