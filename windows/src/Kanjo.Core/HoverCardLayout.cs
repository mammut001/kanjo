namespace Kanjo.Core;

public readonly record struct HoverRect(double X, double Y, double Width, double Height)
{
    public double MinX => X;
    public double MinY => Y;
    public double MaxX => X + Width;
    public double MaxY => Y + Height;
}

public readonly record struct HoverSize(double Width, double Height);

public readonly record struct HoverPoint(double X, double Y);

/// <summary>悬停卡布局纯逻辑：根据锚点矩形、卡片大小、容器大小及安全边距，计算卡片左上角原点。</summary>
public static class HoverCardLayout
{
    public const double DefaultInset = 16;
    public const double DefaultGap = 4;

    /// <summary>计算悬停卡在容器坐标系中的左上角原点。</summary>
    public static HoverPoint Origin(
        HoverRect anchor, HoverSize cardSize, HoverSize container,
        double inset = DefaultInset, double gap = DefaultGap) =>
        Origin(anchor, cardSize, container, inset, inset, gap);

    /// <summary>支持分别指定水平与垂直安全边距的布局计算。</summary>
    public static HoverPoint Origin(
        HoverRect anchor, HoverSize cardSize, HoverSize container,
        double horizontalInset, double verticalInset, double gap = DefaultGap)
    {
        // 水平方向：默认左对齐锚点，并限制在安全边距内
        var minX = horizontalInset;
        var maxX = Math.Max(minX, container.Width - horizontalInset - cardSize.Width);
        var x = Math.Min(Math.Max(anchor.MinX, minX), maxX);

        // 垂直方向：默认置于锚点下方 gap 处
        var yBelow = anchor.MaxY + gap;
        var fitsBelow = yBelow + cardSize.Height <= container.Height - verticalInset;

        // 向上翻转：置于锚点上方 gap 处
        var yAbove = anchor.MinY - gap - cardSize.Height;
        var fitsAbove = yAbove >= verticalInset;

        double y;
        if (fitsBelow)
        {
            y = yBelow;
        }
        else if (fitsAbove)
        {
            y = yAbove;
        }
        else
        {
            // 当上下空间均不足时，尽可能居中/留在安全边距内
            var minY = verticalInset;
            var maxY = Math.Max(minY, container.Height - verticalInset - cardSize.Height);
            y = Math.Min(Math.Max(yBelow, minY), maxY);
        }
        return new HoverPoint(x, y);
    }
}

/// <summary>悬停卡数据行项与构建纯逻辑。</summary>
public sealed record HoverCardRowItem(string Id, string Label, double Cost, long Tokens, double Fraction);

public static class HoverCardRowBuilder
{
    /// <summary>将 agent 列表按花费降序（花费相同时按名称升序）排序，并计算相对最大花费的比例。</summary>
    public static IReadOnlyList<HoverCardRowItem> AgentRows(
        IEnumerable<(string Agent, string Label, double Cost, long Tokens)> agents)
    {
        var sorted = agents
            .Where(a => a.Cost > 0 || a.Tokens > 0)
            .OrderByDescending(a => a.Cost)
            .ThenBy(a => a.Label, StringComparer.Ordinal)
            .ToList();
        var peak = sorted.Count == 0 ? 0 : sorted.Max(a => a.Cost);
        return sorted
            .Select(a => new HoverCardRowItem(a.Agent, a.Label, a.Cost, a.Tokens, peak > 0 ? a.Cost / peak : 0))
            .ToList();
    }

    /// <summary>计算 4 种 token 类型的构成比例（input, output, cacheRead, cacheWrite）。</summary>
    public static IReadOnlyList<(string Id, string LabelKey, long Count, double Fraction)> TokenRows(Tokens tokens)
    {
        var total = Math.Max(tokens.Total, 1);
        (string Id, string LabelKey, long Count)[] items =
        [
            ("input", "project.token.input", tokens.Input),
            ("output", "project.token.output", tokens.Output),
            ("cache_read", "project.token.cache_read", tokens.CacheRead),
            ("cache_write", "project.token.cache_write", tokens.CacheWrite),
        ];
        return items
            .Where(i => i.Count > 0)
            .Select(i => (i.Id, i.LabelKey, i.Count, (double)i.Count / total))
            .ToList();
    }
}
