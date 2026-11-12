namespace Kanjo.Core;

public readonly record struct TreemapRect(double X, double Y, double Width, double Height)
{
    public static readonly TreemapRect Zero = new(0, 0, 0, 0);

    public double MinX => X;
    public double MinY => Y;
    public double MaxX => X + Width;
    public double MaxY => Y + Height;

    public TreemapRect Inset(double dx, double dy) =>
        new(X + dx, Y + dy, Math.Max(0, Width - 2 * dx), Math.Max(0, Height - 2 * dy));

    public override string ToString() => $"({X:0.###},{Y:0.###} {Width:0.###}×{Height:0.###})";
}

public sealed record TreemapTile<TId>(TId Id, double Value, TreemapRect Rect);

/// <summary>
/// Squarified treemap（Bruls, Huizing, van Wijk 2000）。纯函数，不依赖 UI。
/// 按 value 降序逐行铺排：每一行沿当前剩余矩形的短边排列，只要加入下一个块
/// 不会让这一行里最差的长宽比变得更差就继续加；否则把这一行定下来，剩余矩形缩小后重复。
/// </summary>
public static class Treemap
{
    /// <summary>把 items 铺进 rect。value ≤ 0（或非有限值）的不参与。</summary>
    public static IReadOnlyList<TreemapTile<TId>> Layout<TId>(
        IReadOnlyList<(TId Id, double Value)> items, TreemapRect rect) where TId : notnull
    {
        var positive = items
            .Select((item, index) => (item, index))
            .Where(x => x.item.Value > 0 && double.IsFinite(x.item.Value))
            .OrderByDescending(x => x.item.Value)
            .ThenBy(x => x.index)
            .ToList();
        var values = positive.Select(x => x.item).ToList();
        if (values.Count == 0) return [];

        var total = values.Sum(v => v.Value);
        var area = rect.Width * rect.Height;
        if (area <= 0 || !double.IsFinite(rect.Width) || !double.IsFinite(rect.Height))
        {
            return values.Select(v => new TreemapTile<TId>(v.Id, v.Value, new TreemapRect(rect.X, rect.Y, 0, 0))).ToList();
        }

        var scaled = values.Select(v => (v.Id, v.Value, Area: v.Value / total * area)).ToList();

        var result = new List<TreemapTile<TId>>(scaled.Count);
        var free = rect;
        var start = 0;
        while (start < scaled.Count)
        {
            var side = Math.Min(free.Width, free.Height);

            var end = start + 1;
            var rowArea = scaled[start].Area;
            var rowMax = scaled[start].Area;
            var rowMin = scaled[start].Area;
            var best = Worst(rowArea, rowMax, rowMin, side);
            while (end < scaled.Count)
            {
                var a = scaled[end].Area;
                var s = rowArea + a;
                var mx = Math.Max(rowMax, a);
                var mn = Math.Min(rowMin, a);
                var w = Worst(s, mx, mn, side);
                if (w > best) break;
                best = w;
                rowArea = s;
                rowMax = mx;
                rowMin = mn;
                end++;
            }

            var isLast = end == scaled.Count;
            var row = scaled.GetRange(start, end - start);

            if (free.Width >= free.Height)
            {
                // 竖着放在左侧一列。最后一行吃掉全部剩余宽度，消除浮点误差。
                var colW = isLast ? free.Width : rowArea / free.Height;
                var y = free.MinY;
                for (var k = 0; k < row.Count; k++)
                {
                    var h = k == row.Count - 1 ? free.MaxY - y : row[k].Area / colW;
                    result.Add(new TreemapTile<TId>(row[k].Id, row[k].Value, new TreemapRect(free.MinX, y, colW, h)));
                    y += h;
                }
                free = new TreemapRect(free.MinX + colW, free.MinY, Math.Max(free.Width - colW, 0), free.Height);
            }
            else
            {
                // 横着放在顶部一行。
                var rowH = isLast ? free.Height : rowArea / free.Width;
                var x = free.MinX;
                for (var k = 0; k < row.Count; k++)
                {
                    var w = k == row.Count - 1 ? free.MaxX - x : row[k].Area / rowH;
                    result.Add(new TreemapTile<TId>(row[k].Id, row[k].Value, new TreemapRect(x, free.MinY, w, rowH)));
                    x += w;
                }
                free = new TreemapRect(free.MinX, free.MinY + rowH, free.Width, Math.Max(free.Height - rowH, 0));
            }
            start = end;
        }
        return result;
    }

    /// <summary>一行里最差（最大）的长宽比。</summary>
    private static double Worst(double sum, double max, double min, double side)
    {
        if (!(sum > 0) || !(side > 0) || !(min > 0)) return double.PositiveInfinity;
        var s2 = sum * sum;
        var w2 = side * side;
        return Math.Max(w2 * max / s2, s2 / (w2 * min));
    }

    /// <summary>
    /// 合并小块：占总值比例小于 threshold 的项合并成一组（只有一个时不合并，原样保留）。
    /// value ≤ 0 的项直接丢弃。kept 保持输入顺序。
    /// </summary>
    public static (IReadOnlyList<(TId Id, double Value)> Kept, IReadOnlyList<TId> Merged, double MergedValue) GroupSmall<TId>(
        IReadOnlyList<(TId Id, double Value)> items, double threshold) where TId : notnull
    {
        var positive = items.Where(i => i.Value > 0 && double.IsFinite(i.Value)).ToList();
        var total = positive.Sum(i => i.Value);
        if (!(total > 0)) return ([], [], 0);
        var small = positive.Where(i => i.Value / total < threshold).ToList();
        if (small.Count < 2) return (positive, [], 0);
        var smallIds = small.Select(i => i.Id).ToHashSet();
        return (positive.Where(i => !smallIds.Contains(i.Id)).ToList(), small.Select(i => i.Id).ToList(),
            small.Sum(i => i.Value));
    }
}
