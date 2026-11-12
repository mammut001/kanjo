using System.Text;

namespace Kanjo.Core;

/// <summary>
/// 总览的马赛克布局（Mosaic.swift 的纯逻辑部分）：每个项目一块，面积 = 花费，颜色 = 主力 agent。
/// 小于总面积 1.5% 的项目合并成一块灰色「+N more」。
/// 先在外扩 gap/2 的矩形里铺，再把每块内缩 gap/2：块间距 = gap，外缘与容器齐平。
/// </summary>
public static class MosaicLayout
{
    public const double DefaultHeight = 160;
    public const double Gap = 2;
    public const double MergeThreshold = 0.015;
    public const uint CornerRadius = 4;

    /// <summary>「+N more」合并块的 id（不会和真实项目 id 冲突）。</summary>
    public const string MoreId = "\u0000more";

    public sealed record Tile(string Id, Project? Project, IReadOnlyList<Project> Merged, double Cost, TreemapRect Rect)
    {
        public bool IsProject => Project is not null;

        /// <summary>方块上的名字，从长到短；放不下长的就试短的。</summary>
        public IReadOnlyList<string> Names => Project is { } p
            ? [p.Name]
            : [L10n.TrL(null, "mosaic.more.format", Merged.Count), $"+{Merged.Count}"];

        /// <summary>主力 agent 的颜色 key；合并块用中性色（null）。</summary>
        public string? AgentKey => Project is { } p ? DominantAgent.Of(p.ByAgent)?.Agent : null;

        public string Tooltip(string currency = "USD") => Project is { } p
            ? TooltipBuilder.ProjectTileTooltip(p.Name, p.Cost, p.Tokens.Total, p.ByAgent, currency)
            : TooltipBuilder.MergedTileTooltip(Merged, currency);
    }

    public static IReadOnlyList<Tile> Build(IReadOnlyList<Project> projects, double width, double height = DefaultHeight)
    {
        var byId = new Dictionary<string, Project>(StringComparer.Ordinal);
        foreach (var p in projects)
        {
            byId.TryAdd(p.Id, p);
        }

        var grouped = Treemap.GroupSmall(projects.Select(p => (p.Id, p.Cost)).ToList(), MergeThreshold);
        var items = grouped.Kept.ToList();
        if (grouped.Merged.Count > 0) items.Add((MoreId, grouped.MergedValue));

        var half = Gap / 2;
        var bounds = new TreemapRect(-half, -half, width + half * 2, height + half * 2);
        var result = new List<Tile>();
        foreach (var tile in Treemap.Layout(items, bounds))
        {
            var rect = tile.Rect.Inset(half, half);
            if (rect.Width <= 0.5 || rect.Height <= 0.5) continue;

            if (tile.Id == MoreId)
            {
                var merged = grouped.Merged
                    .Select(id => byId.GetValueOrDefault(id))
                    .Where(p => p is not null)
                    .Select(p => p!)
                    .ToList();
                result.Add(new Tile(tile.Id, null, merged, tile.Value, rect));
                continue;
            }
            if (!byId.TryGetValue(tile.Id, out var project)) continue;
            result.Add(new Tile(tile.Id, project, [], tile.Value, rect));
        }
        return result;
    }

    /// <summary>
    /// 方块标签的适配规则（绝不截断、不出现省略号）：
    /// 宽 ≥ 72 且高 ≥ 40 画名字 + 金额；宽 ≥ 72 但高 &lt; 40 只画名字；更小什么都不画。
    /// </summary>
    public static (string? Name, bool ShowAmount) FitLabel(
        IReadOnlyList<string> names, string amount, double width, double height,
        Func<string, double> measureName, Func<string, double> measureAmount)
    {
        const double minWidth = 72;
        const double fullHeight = 40;
        const double padX = 6;
        if (width < minWidth || height < 20) return (null, false);
        var avail = width - padX * 2;
        foreach (var name in names)
        {
            if (measureName(name) <= avail)
            {
                var showAmount = height >= fullHeight && measureAmount(amount) <= avail;
                return (name, showAmount);
            }
        }
        return (null, false);
    }
}
