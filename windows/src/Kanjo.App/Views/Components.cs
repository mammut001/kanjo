using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Shapes;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>截图模式：页面交出内部内容（不含滚动容器），由面板按整页高度渲染。</summary>
public interface ISnapshotPage
{
    Control SnapshotBody { get; }
}

/// <summary>
/// 紧凑的分段控件（自绘胶囊）：All · Today · 7d · 30d · Last week · Since reset · Cycle。
/// 「Since reset」不可用时画成三级色、不可点；「Cycle」同理。
/// </summary>
public sealed class RangePicker : Border
{
    public RangePicker(string rangeRaw, TimeRange effective, bool resetAvailable, bool cycleAvailable,
        Action<string> onChange)
    {
        Padding = new Thickness(1.5);
        CornerRadius = new CornerRadius(12);
        Background = new SolidColorBrush(Palette.ForegroundColor, 0.06);
        HorizontalAlignment = HorizontalAlignment.Right;
        VerticalAlignment = VerticalAlignment.Center;

        var row = new StackPanel { Orientation = Orientation.Horizontal };
        foreach (var range in TimeRanges.All)
        {
            var selected = range == effective;
            var label = Ui.Text(range.ShortLabel(), 9.5, selected ? FontWeight.SemiBold : FontWeight.Normal,
                selected ? Palette.Foreground : Palette.Secondary);
            var chip = new Border
            {
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(4, 2.5, 4, 2.5),
                Background = selected ? new SolidColorBrush(Palette.ForegroundColor, 0.13) : Brushes.Transparent,
                Child = label,
                Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Hand),
            };

            var unavailable = Unavailable(range, resetAvailable, cycleAvailable);
            if (unavailable is not null)
            {
                label.Foreground = Palette.Tertiary;
                ToolTip.SetTip(chip, unavailable);
            }
            else
            {
                ToolTip.SetTip(chip, range.LongLabel());
                chip.PointerReleased += (_, _) => onChange(range.RawValue());
                chip.PointerEntered += (_, _) => chip.Background = Palette.RowHover;
                chip.PointerExited += (_, _) =>
                {
                    chip.Background = selected
                        ? new SolidColorBrush(Palette.ForegroundColor, 0.13)
                        : Brushes.Transparent;
                };
            }
            row.Children.Add(chip);
        }
        Child = row;
    }

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
        Children.Add(Ui.Text(caption.Text, 10.5, null, Palette.Secondary, wrap: true));
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
        _ = agentLabels;

        var tiles = MosaicLayout.Build(projects, width);
        for (var i = 0; i < tiles.Count; i++)
        {
            Children.Add(TileView(tiles[i], currency, i));
        }
    }

    private static Control TileView(MosaicLayout.Tile tile, string currency, int index)
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
        if (tile.Project is { } project)
        {
            var captured = project;
            shape.Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Hand);
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
    /// </summary>
    private static Control? Label(MosaicLayout.Tile tile, string currency)
    {
        var amount = Fmt.Money(tile.Cost, currency);
        var fit = MosaicLayout.FitLabel(
            tile.Names, amount, tile.Rect.Width, tile.Rect.Height,
            s => Type.MeasureWidth(s, 11, FontWeight.SemiBold),
            s => Type.MeasureWidth(s, 10, FontWeight.Normal));
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
            box.Children.Add(Ui.Text(amount, 10, FontWeight.Normal, Palette.OnTile));
        }
        return box;
    }
}
