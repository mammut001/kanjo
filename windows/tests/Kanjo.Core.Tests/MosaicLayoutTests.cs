using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 马赛克布局固定值：把 sample.json 的 8 个项目铺进 360×160，块位置必须和 Mac 一致
/// （HabitGarden 在 meterkit 正下方同一列；weather-cli 在右上；old-blog + dotfiles 合并成「+2 more」）。
/// 期望值由 `ui/Sources/KanjoCore/Treemap.swift` 的算法逐行推得（同一套 squarified 规则，见 TreemapTests）。
/// </summary>
public sealed class MosaicLayoutTests : KanjoTestCase
{
    private static IReadOnlyList<Project> Sample() => LoadFixture().Projects;

    private static Dictionary<string, MosaicLayout.Tile> ByName(double width = 360) =>
        MosaicLayout.Build(Sample(), width).ToDictionary(t => t.Project?.Name ?? "+more", StringComparer.Ordinal);

    /// <summary>外缘与容器齐平：铺满 360 宽、160 高（间隙在最外圈各占 1pt）。</summary>
    [Fact]
    public void TestSampleTilesUseFullPanelWidth()
    {
        var tiles = MosaicLayout.Build(Sample(), 360);
        var left = tiles.Min(t => t.Rect.X);
        var right = tiles.Max(t => t.Rect.MaxX);
        // 外扩 gap/2 铺、再内缩 gap/2：左边缘 = 0（gap/2 - gap/2），右边缘 = 360。
        Assert.Equal(0, left, 6);
        Assert.Equal(360, right, 6);
        Assert.Equal(0, tiles.Min(t => t.Rect.Y), 6);
        Assert.Equal(MosaicLayout.DefaultHeight, tiles.Max(t => t.Rect.MaxY), 6);
    }

    /// <summary>sample.json 的 8 个项目：6 块 + 1 个「+2 more」（old-blog、dotfiles 合并）。</summary>
    [Fact]
    public void TestSampleTileOrderAndMerge()
    {
        var tiles = MosaicLayout.Build(Sample(), 360);
        Assert.Equal(
            ["PocketTimer", "meterkit", "HabitGarden", "weather-cli", "infra-scripts", "rust-playground", "+more"],
            tiles.Select(t => t.Project?.Name ?? "+more").ToArray());
        var more = tiles[^1];
        Assert.False(more.IsProject);
        Assert.Equal(["old-blog", "dotfiles"], more.Merged.Select(p => p.Name).ToArray());
        Assert.Equal(1.9839, more.Cost, 4);
        Assert.Null(more.AgentKey); // 合并块用中性灰
    }

    /// <summary>
    /// 固定矩形（360×160，gap 2）。Mac 的列结构：PocketTimer 占左列；中列上 meterkit 下 HabitGarden；
    /// 右列上 weather-cli、中 infra-scripts、下 rust-playground + 「+2 more」。
    /// </summary>
    [Fact]
    public void TestSampleTileRectsMatchMac()
    {
        var t = ByName();

        // 左列：整高的 PocketTimer。
        AssertRect(t["PocketTimer"].Rect, 0, 0, 190.62, 160);

        // 中列：meterkit 在上，HabitGarden 正下方（同一 x、同一宽）。
        var meter = t["meterkit"].Rect;
        var habit = t["HabitGarden"].Rect;
        AssertRect(meter, 192.62, 0, 108.37, 97.02);
        AssertRect(habit, 192.62, 99.02, 108.37, 60.98);
        Assert.Equal(meter.X, habit.X, 6);
        Assert.Equal(meter.MaxX, habit.MaxX, 6);
        Assert.Equal(meter.MaxY + MosaicLayout.Gap, habit.Y, 6);

        // 右列：weather-cli → infra-scripts → rust-playground → +more，从上往下堆叠，x 与宽都一致。
        var weather = t["weather-cli"].Rect;
        var infra = t["infra-scripts"].Rect;
        var rust = t["rust-playground"].Rect;
        var more = t["+more"].Rect;
        AssertRect(weather, 302.98, 0, 57.02, 92.96);
        AssertRect(infra, 302.98, 94.96, 57.02, 39.34);
        AssertRect(rust, 302.98, 136.3, 39.81, 23.7);
        AssertRect(more, 344.79, 136.3, 15.21, 23.7);
        Assert.Equal(weather.X, infra.X, 6);
        Assert.Equal(weather.X, rust.X, 6);
        Assert.Equal(weather.MaxY + MosaicLayout.Gap, infra.Y, 6);
        Assert.Equal(infra.MaxY + MosaicLayout.Gap, rust.Y, 6);
        Assert.Equal(rust.Y, more.Y, 6);
        Assert.Equal(360, more.MaxX, 6);
    }

    /// <summary>不重叠、不越界，而且合起来铺满整块（只留 gap 的缝）。</summary>
    [Fact]
    public void TestSampleTilesFillAreaWithoutOverlap()
    {
        const double width = 360;
        var tiles = MosaicLayout.Build(Sample(), width);
        foreach (var t in tiles)
        {
            Assert.True(t.Rect.X >= 0 && t.Rect.Y >= 0, t.Id);
            Assert.True(t.Rect.MaxX <= width + 1e-6 && t.Rect.MaxY <= MosaicLayout.DefaultHeight + 1e-6, t.Id);
        }
        for (var i = 0; i < tiles.Count; i++)
        {
            for (var j = i + 1; j < tiles.Count; j++)
            {
                var a = tiles[i].Rect;
                var b = tiles[j].Rect;
                var w = Math.Max(0, Math.Min(a.MaxX, b.MaxX) - Math.Max(a.X, b.X));
                var h = Math.Max(0, Math.Min(a.MaxY, b.MaxY) - Math.Max(a.Y, b.Y));
                Assert.True(w * h < 1e-6, $"{tiles[i].Id} overlaps {tiles[j].Id}");
            }
        }

        // 覆盖率：内缩 gap/2 之后每块各少一圈 1pt 的边，总面积略小于 360×160。
        var covered = tiles.Sum(t => t.Rect.Width * t.Rect.Height);
        var full = width * MosaicLayout.DefaultHeight;
        Assert.True(covered > full * 0.9, $"covered {covered} of {full}");
        Assert.True(covered < full);

        // 面积与价值大致成正比（内缩 gap/2 会让小块偏小，误差放宽到 20%）。
        var total = tiles.Sum(t => t.Cost);
        foreach (var t in tiles)
        {
            var expected = t.Cost / total * (width + MosaicLayout.Gap) * (MosaicLayout.DefaultHeight + MosaicLayout.Gap);
            Assert.True(Math.Abs(t.Rect.Width * t.Rect.Height - expected) < expected * 0.22,
                $"{t.Id}: {t.Rect.Width * t.Rect.Height} vs {expected}");
        }
    }

    /// <summary>方块上的文字：宽 ≥ 72 且高 ≥ 40 画名字 + 金额；更小只画名字或不画。</summary>
    [Fact]
    public void TestLabelFitting()
    {
        // 名字 6pt/字符，金额 6pt/字符；"+2 more" 用一个更宽的字符宽度来逼出短写。
        static double Narrow(string s) => s.Length * 6.0;
        static double Wide(string s) => s.Length * 10.0;
        var names = new[] { "PocketTimer" }; // 11 字符 → 66pt

        var big = MosaicLayout.FitLabel(names, "$139.98", 200, 100, Narrow, Narrow);
        Assert.Equal("PocketTimer", big.Name);
        Assert.True(big.ShowAmount);

        // 高度不足 40：只画名字
        var shortTile = MosaicLayout.FitLabel(names, "$139.98", 200, 30, Narrow, Narrow);
        Assert.Equal("PocketTimer", shortTile.Name);
        Assert.False(shortTile.ShowAmount);

        // 宽度不足 72 或高度不足 20：什么都不画
        Assert.Null(MosaicLayout.FitLabel(names, "$139.98", 60, 100, Narrow, Narrow).Name);
        Assert.Null(MosaicLayout.FitLabel(names, "$139.98", 200, 18, Narrow, Narrow).Name);

        // 名字放不下：整块不画（绝不截断）
        Assert.Null(MosaicLayout.FitLabel(["a-very-long-project-name"], "$1.00", 80, 60, Narrow, Narrow).Name);

        // 「+N more」先试长写，放不下再试短写
        var more = MosaicLayout.FitLabel(["+2 more", "+2"], "$1.98", 80, 60, Wide, Wide);
        Assert.Equal("+2", more.Name);
    }

    private static void AssertRect(TreemapRect rect, double x, double y, double width, double height)
    {
        Assert.Equal(x, rect.X, 1);
        Assert.Equal(y, rect.Y, 1);
        Assert.Equal(width, rect.Width, 1);
        Assert.Equal(height, rect.Height, 1);
    }
}
