using Xunit;

namespace Kanjo.Core.Tests;

public sealed class TreemapTests : KanjoTestCase
{
    private static readonly TreemapRect Bounds = new(10, 20, 352, 150);
    private const double Eps = 1e-6;

    private static List<(string Id, double Value)> Sample() =>
    [
        ("a", 1198), ("b", 1035), ("c", 422), ("d", 237), ("e", 226), ("f", 162),
        ("g", 152), ("h", 149), ("i", 96), ("j", 72), ("k", 35), ("l", 25), ("zero", 0), ("neg", -3),
    ];

    [Fact]
    public void TestAreaSumEqualsBounds()
    {
        var tiles = Treemap.Layout(Sample(), Bounds);
        var sum = tiles.Sum(t => t.Rect.Width * t.Rect.Height);
        Assert.Equal(Bounds.Width * Bounds.Height, sum, 6);
    }

    [Fact]
    public void TestAreasProportionalToValues()
    {
        var tiles = Treemap.Layout(Sample(), Bounds);
        var total = tiles.Sum(t => t.Value);
        foreach (var t in tiles)
        {
            var expected = t.Value / total * (Bounds.Width * Bounds.Height);
            Assert.Equal(expected, t.Rect.Width * t.Rect.Height, 6);
        }
    }

    [Fact]
    public void TestNonPositiveValuesExcludedAndSortedDescending()
    {
        var tiles = Treemap.Layout(Sample(), Bounds);
        Assert.Equal(12, tiles.Count);
        Assert.DoesNotContain(tiles, t => t.Id is "zero" or "neg");
        var values = tiles.Select(t => t.Value).ToArray();
        Assert.Equal(values.OrderByDescending(v => v).ToArray(), values);
    }

    [Fact]
    public void TestTilesInsideBounds()
    {
        foreach (var t in Treemap.Layout(Sample(), Bounds))
        {
            Assert.True(t.Rect.MinX >= Bounds.MinX - Eps, t.Id);
            Assert.True(t.Rect.MinY >= Bounds.MinY - Eps, t.Id);
            Assert.True(t.Rect.MaxX <= Bounds.MaxX + Eps, t.Id);
            Assert.True(t.Rect.MaxY <= Bounds.MaxY + Eps, t.Id);
            Assert.True(t.Rect.Width > 0, t.Id);
            Assert.True(t.Rect.Height > 0, t.Id);
        }
    }

    [Fact]
    public void TestTilesDoNotOverlap()
    {
        var tiles = Treemap.Layout(Sample(), Bounds);
        for (var i = 0; i < tiles.Count; i++)
        {
            for (var j = i + 1; j < tiles.Count; j++)
            {
                var a = tiles[i].Rect;
                var b = tiles[j].Rect;
                var overlapW = Math.Max(0, Math.Min(a.MaxX, b.MaxX) - Math.Max(a.MinX, b.MinX));
                var overlapH = Math.Max(0, Math.Min(a.MaxY, b.MaxY) - Math.Max(a.MinY, b.MinY));
                Assert.True(overlapW * overlapH < 1e-6, $"{tiles[i].Id} overlaps {tiles[j].Id}");
            }
        }
    }

    [Fact]
    public void TestSingleItemFillsBounds()
    {
        var tiles = Treemap.Layout([("only", 5.0)], Bounds);
        Assert.Single(tiles);
        Assert.Equal(Bounds, tiles[0].Rect);
    }

    [Fact]
    public void TestEmptyAndAllNonPositiveInput()
    {
        Assert.Empty(Treemap.Layout(Array.Empty<(string, double)>(), Bounds));
        Assert.Empty(Treemap.Layout([("a", 0.0), ("b", -1.0)], Bounds));
    }

    [Fact]
    public void TestZeroSizedBoundsDoesNotCrash()
    {
        var tiles = Treemap.Layout([("a", 1.0), ("b", 2.0)], TreemapRect.Zero);
        Assert.Equal(2, tiles.Count);
        Assert.All(tiles, t => Assert.Equal(new TreemapRect(t.Rect.X, t.Rect.Y, 0, 0), t.Rect));
    }

    [Fact]
    public void TestEqualValuesAreReasonablySquare()
    {
        var items = Enumerable.Range(0, 4).Select(i => (Id: $"{i}", Value: 1.0)).ToList();
        var tiles = Treemap.Layout(items, new TreemapRect(0, 0, 100, 100));
        foreach (var t in tiles)
        {
            Assert.Equal(50, t.Rect.Width, 6);
            Assert.Equal(50, t.Rect.Height, 6);
        }
    }

    [Fact]
    public void TestGroupSmall()
    {
        var g = Treemap.GroupSmall(
            [("big", 90.0), ("mid", 8.6), ("s1", 1.0), ("s2", 0.4), ("z", 0.0)], 0.015);
        Assert.Equal(["big", "mid"], g.Kept.Select(k => k.Id).ToArray());
        Assert.Equal(["s1", "s2"], g.Merged.ToArray());
        Assert.Equal(1.4, g.MergedValue, 9);
    }

    [Fact]
    public void TestGroupSmallKeepsLoneSmallItem()
    {
        var g = Treemap.GroupSmall([("big", 99.0), ("s1", 1.0)], 0.015);
        Assert.Equal(["big", "s1"], g.Kept.Select(k => k.Id).ToArray());
        Assert.Empty(g.Merged);
        Assert.Equal(0, g.MergedValue);
    }

    [Fact]
    public void TestGroupSmallEmpty()
    {
        var g = Treemap.GroupSmall(Array.Empty<(string, double)>(), 0.015);
        Assert.Empty(g.Kept);
        Assert.Empty(g.Merged);
    }
}
