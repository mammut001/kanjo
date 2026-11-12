using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Shapes;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 8 周燃烧热力条：每格一周（周一到周日）。每格按那周各 agent 的 cost 份额纵向分成最多 3 段色带
/// （上到下按 cost 降序，份额 &lt; 10% 的并进最大那段），段间不留缝；整格深浅按该周花费 / 8 周最大周花费分 5 档。
/// </summary>
public sealed class HeatStripView : Panel
{
    /// <summary>档位 1…4 的不透明度；0 档用中性 8% 底色。</summary>
    private static readonly double[] Opacities = [0, 0.3, 0.52, 0.76, 1];

    public HeatStripView(
        IReadOnlyList<WeekCost> weeks,
        double cellWidth = 8,
        double cellHeight = 16,
        double radius = 2,
        double spacing = 2)
    {
        var peak = weeks.Count == 0 ? 0 : weeks.Max(w => w.Cost);
        var strip = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = spacing,
            VerticalAlignment = VerticalAlignment.Center,
        };
        foreach (var week in weeks)
        {
            strip.Children.Add(Cell(week, HeatStrip.Level(week.Cost, peak), cellWidth, cellHeight, radius));
        }
        Children.Add(strip);
        Width = weeks.Count * cellWidth + Math.Max(weeks.Count - 1, 0) * spacing;
        Height = cellHeight;
        ClipToBounds = true;
    }

    private static Control Cell(WeekCost week, int level, double width, double height, double radius)
    {
        var shape = Ui.Rounded(radius, level == 0 ? Palette.HeatEmpty : Palette.Neutral);
        shape.Width = width;
        shape.Height = height;

        var segments = HeatStrip.Segments(week);
        if (level == 0 || segments.Count == 0) return shape;

        var opacity = Opacities[Math.Clamp(level, 0, Opacities.Length - 1)];
        var stack = new StackPanel { Orientation = Orientation.Vertical };
        foreach (var (agent, share) in segments)
        {
            var brush = Palette.Agent(agent);
            var band = new Border
            {
                Background = new SolidColorBrush(((ISolidColorBrush)brush).Color, opacity),
                Height = Math.Max(0, height * share),
            };
            stack.Children.Add(band);
        }
        shape.Child = stack;
        return shape;
    }
}

/// <summary>
/// 总览的马赛克：每个项目一块，面积 = 花费，颜色 = 主力 agent（全饱和）。
/// 小于总面积 1.5% 的项目合并成一块灰色「+N more」。圆角 4、间距 2、不描边。
/// </summary>
public sealed class MosaicView : Panel
{
    public const double Height_ = 160;
    private const double Gap = 2;
    private const double MergeThreshold = 0.015;
    private const string MoreId = "\u0000more";

    public sealed record Tile(string Id, Project? Project, IReadOnlyList<Project> Merged, double Cost, Rect Rect);

    public MosaicView(IReadOnlyList<Project> projects, double width)
    {
        Width = width;
        Height = Height_;
        ClipToBounds = false;
        foreach (var tile in Tiles(projects, new Size(width, Height_)))
        {
            Children.Add(TileView(tile));
        }
    }

    public static IReadOnlyList<Tile> Tiles(IReadOnlyList<Project> projects, Size size)
    {
        var byId = new Dictionary<string, Project>(StringComparer.Ordinal);
        foreach (var p in projects)
        {
            byId.TryAdd(p.Id, p);
        }
        var grouped = Treemap.GroupSmall(projects.Select(p => (p.Id, p.Cost)).ToList(), MergeThreshold);
        var items = grouped.Kept.ToList();
        if (grouped.Merged.Count > 0) items.Add((MoreId, grouped.MergedValue));

        // 先在外扩 gap/2 的矩形里铺，再把每块内缩 gap/2：块间距 = gap，外缘与容器齐平。
        var half = Gap / 2;
        var bounds = new TreemapRect(-half, -half, size.Width + half * 2, size.Height + half * 2);
        var result = new List<Tile>();
        foreach (var t in Treemap.Layout(items, bounds))
        {
            var rect = t.Rect.Inset(half, half);
            if (rect.Width <= 0.5 || rect.Height <= 0.5) continue;
            if (t.Id == MoreId)
            {
                var merged = grouped.Merged.Select(id => byId.GetValueOrDefault(id)).Where(p => p is not null)
                    .Select(p => p!).ToList();
                result.Add(new Tile(t.Id, null, merged, t.Value, new Rect(rect.X, rect.Y, rect.Width, rect.Height)));
                continue;
            }
            if (!byId.TryGetValue(t.Id, out var project)) continue;
            result.Add(new Tile(t.Id, project, [], t.Value, new Rect(rect.X, rect.Y, rect.Width, rect.Height)));
        }
        return result;
    }

    private static Control TileView(Tile tile)
    {
        var color = tile.Project is { } p
            ? Palette.AgentColor(DominantAgent.Of(p.ByAgent)?.Agent ?? "unknown")
            : ((ISolidColorBrush)Palette.Neutral).Color;
        var shape = Ui.Rounded(4, new SolidColorBrush(color));
        shape.Width = tile.Rect.Width;
        shape.Height = tile.Rect.Height;
        shape.Margin = new Thickness(tile.Rect.X, tile.Rect.Y, 0, 0);
        shape.HorizontalAlignment = HorizontalAlignment.Left;
        shape.VerticalAlignment = VerticalAlignment.Top;

        var label = new MosaicLabel(tile);
        if (label.HasContent)
        {
            shape.Child = label;
            shape.ClipToBounds = true;
        }
        var tip = tile.Project is { } project
            ? TooltipBuilder.ProjectTileTooltip(project.Name, project.Cost, project.Tokens.Total, project.ByAgent)
            : TooltipBuilder.MergedTileTooltip(tile.Merged);
        ToolTip.SetTip(shape, tip);
        return shape;
    }

    /// <summary>
    /// 方块左上角的名字和金额。规则（绝不截断、不出现省略号）：
    /// - 宽 ≥ 72 且高 ≥ 40：名字 + 金额（金额放不下就只画名字）；
    /// - 宽 ≥ 72 但高 &lt; 40：只画名字一行；
    /// - 更小：什么都不画。
    /// </summary>
    private sealed class MosaicLabel : StackPanel
    {
        private const double TileMinWidth = 72;
        private const double TileFullHeight = 40;
        private const double PadX = 6;
        private const double PadTop = 5;

        public bool HasContent { get; }

        public MosaicLabel(Tile tile)
        {
            Orientation = Orientation.Vertical;
            Spacing = 1;
            Margin = new Thickness(PadX, PadTop, 0, 0);
            HorizontalAlignment = HorizontalAlignment.Left;
            VerticalAlignment = VerticalAlignment.Top;

            var names = tile.Project is { } p
                ? new[] { p.Name }
                : new[] { L10n.TrL(null, "mosaic.more.format", tile.Merged.Count), $"+{tile.Merged.Count}" };
            var amount = Fmt.Money(tile.Cost);
            var fit = Fit(names, amount, tile.Rect.Width, tile.Rect.Height);
            if (fit.Name is { } name)
            {
                Children.Add(Ui.Text(name, 11, FontWeight.SemiBold, Palette.OnTile));
                HasContent = true;
            }
            if (fit.Amount)
            {
                Children.Add(Ui.Text(amount, 10, FontWeight.Normal, Palette.OnTile));
            }
        }

        private static (string? Name, bool Amount) Fit(string[] names, string amount, double width, double height)
        {
            if (width < TileMinWidth || height < 20) return (null, false);
            var avail = width - PadX * 2;
            string? chosen = null;
            foreach (var name in names)
            {
                if (Type.MeasureWidth(name, 11, FontWeight.SemiBold) <= avail)
                {
                    chosen = name;
                    break;
                }
            }
            if (chosen is null) return (null, false);
            var showAmount = height >= TileFullHeight && Type.MeasureWidth(amount, 10) <= avail;
            return (chosen, showAmount);
        }
    }
}
