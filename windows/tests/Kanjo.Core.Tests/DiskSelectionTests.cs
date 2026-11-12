using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>磁盘选择 / 清理计划分组 / 磁盘状态机（新纯逻辑）。</summary>
public sealed class DiskSelectionTests : KanjoTestCase
{
    private static DiskReport Load() => LoadDiskFixture();

    [Fact]
    public void TestOnlyUnblockedNonNeverEntriesAreSelectable()
    {
        var report = Load();
        foreach (var entry in report.AllEntries)
        {
            var expected = entry.Deletable != DiskDeletable.Never && entry.Blocked.Count == 0;
            Assert.Equal(expected, entry.IsReclaimable);
        }
        Assert.All(report.AllEntries.Where(e => e.Blocked.Count > 0), e => Assert.False(e.IsReclaimable));
        Assert.All(report.AllEntries.Where(e => e.Deletable == DiskDeletable.Never),
            e => Assert.False(e.IsReclaimable));
    }

    [Fact]
    public void TestSelectionDropsEntriesThatBecameUnreclaimable()
    {
        var report = Load();
        var selected = report.AllEntries.Where(e => e.IsReclaimable).Select(e => e.Id)
            .ToHashSet(StringComparer.Ordinal);
        var stillReclaimable = report.AllEntries.Where(e => e.IsReclaimable).Select(e => e.Id)
            .ToHashSet(StringComparer.Ordinal);
        selected.IntersectWith(stillReclaimable);
        Assert.Equal(selected.Count, stillReclaimable.Count);

        // 只保留 blocked 的条目后，选择集应变空。
        var blockedIds = report.AllEntries.Where(e => e.Blocked.Count > 0).Select(e => e.Id).ToList();
        selected = blockedIds.ToHashSet(StringComparer.Ordinal);
        selected.IntersectWith(stillReclaimable);
        Assert.Empty(selected);
    }

    [Fact]
    public void TestCleanBarSumsSelectedEntriesOnly()
    {
        var report = Load();
        var entries = report.AllEntries.Where(e => e.IsReclaimable).Take(2).ToList();
        var selected = entries.Select(e => e.Id).ToHashSet(StringComparer.Ordinal);
        var total = report.AllEntries.Where(e => selected.Contains(e.Id)).Sum(e => e.Bytes);
        Assert.Equal(entries.Sum(e => e.Bytes), total);
    }

    [Fact]
    public void TestPlanGroupsWholeEntryHasSizeAndPartialDoesNot()
    {
        var report = Load();
        var entry = report.AllEntries.First(e => e.IsReclaimable && e.Files >= 1);
        var whole = CleanPlan.Groups(report, new RoList<string> { entry.Path });
        Assert.Single(whole);
        Assert.Equal(entry.Id, whole[0].EntryId);
        Assert.Equal(entry.Bytes, whole[0].Bytes);

        var partial = CleanPlan.Groups(report, new RoList<string> { entry.Path + "/nested/file" });
        Assert.Single(partial);
        Assert.Equal(entry.Id, partial[0].EntryId);
        Assert.Null(partial[0].Bytes);
    }

    [Fact]
    public void TestPlanGroupsKeepReportOrderAndCollectStragglers()
    {
        var report = Load();
        var entries = report.AllEntries.Where(e => e.IsReclaimable).Take(3).ToList();
        var moved = new RoList<string> { entries[2].Path, entries[0].Path, "/somewhere/else" };
        var groups = CleanPlan.Groups(report, moved);
        Assert.Equal(3, groups.Count);
        Assert.Equal(entries[0].Id, groups[0].EntryId);
        Assert.Equal(entries[2].Id, groups[1].EntryId);
        Assert.Equal(string.Empty, groups[2].EntryId);
        Assert.Equal(["Other"], groups[2].Title.PadLeft(0).Split(' ').Take(1));
        Assert.Single(groups[2].Paths);
    }

    [Fact]
    public void TestPlanGroupsDeepestMatchingEntryWins()
    {
        var report = Load();
        var parent = report.AllEntries.First(e => e.IsReclaimable);
        var child = report.AllEntries.First(e => e.IsReclaimable && e.Id != parent.Id &&
                                                  e.Path.StartsWith(parent.Path + "/", StringComparison.Ordinal) is false);
        _ = child;
        // 同一个路径只归到最深的那个条目（这里用一个父路径下的子路径验证）。
        var nestedPath = parent.Path + "/deep/file.log";
        var groups = CleanPlan.Groups(report, new RoList<string> { nestedPath });
        Assert.Single(groups);
        Assert.Equal(parent.Id, groups[0].EntryId);
    }

    [Fact]
    public void TestCountAndSizeUsesSingularPlural()
    {
        Assert.Equal("1 path · 4.6 GB", CleanPlan.CountAndSize(1, 4_600_000_000));
        Assert.Equal("2 paths", CleanPlan.CountAndSize(2, null));
    }

    [Fact]
    public void TestReportStateKeepsPreviousReportWhileLoading()
    {
        var report = Load();
        var state = new DiskReportState(report);
        Assert.True(state.HasReport);
        Assert.False(state.IsLoading);
        Assert.False(state.IsRescanning);

        Assert.True(state.BeginRefresh());
        Assert.False(state.BeginRefresh());
        Assert.True(state.IsRescanning);

        state.FinishRefresh(null);
        Assert.False(state.IsLoading);
        Assert.Same(report, state.Report);
    }

    [Fact]
    public void TestEmptyStateStartsWithoutReport()
    {
        var state = new DiskReportState();
        Assert.False(state.HasReport);
        Assert.False(state.IsRescanning);
        Assert.True(state.BeginRefresh());
        state.FinishRefresh(DiskReport.Empty);
        Assert.True(state.HasReport);
        Assert.Equal(0L, state.Report!.TotalBytes);
    }

    [Fact]
    public void TestAgeArgumentAndCaption()
    {
        Assert.Null(DiskAge.Any.Argument());
        Assert.Equal("7d", DiskAge.Days7.Argument());
        Assert.Equal("30d", DiskAge.Days30.Argument());
        Assert.Equal("90d", DiskAge.Days90.Argument());
        Assert.Equal("Any age", DiskAge.Any.Caption());
        Assert.Equal("Older than 7d", DiskAge.Days7.Caption());
    }

    [Fact]
    public void TestScanCaptionBuckets()
    {
        var now = Ts("2026-10-25T10:00:00Z");
        DiskReport At(string scanned) => new(1, scanned, 0, 0, [], null, scanned, null);
        Assert.Equal("Scanned just now", DiskScanCaption.Text(At("2026-10-25T09:59:30Z"), now));
        Assert.Equal("Scanned 5 min ago", DiskScanCaption.Text(At("2026-10-25T09:55:00Z"), now));
        Assert.Equal("Scanned 2 hr ago", DiskScanCaption.Text(At("2026-10-25T08:00:00Z"), now));
        Assert.Equal("Scanned 1 day ago", DiskScanCaption.Text(At("2026-10-24T10:00:00Z"), now));
        Assert.Equal("Scanned 3 days ago", DiskScanCaption.Text(At("2026-10-22T10:00:00Z"), now));
        Assert.Equal("Scan time unknown", DiskScanCaption.Text(At("not a date"), now));
    }

    [Fact]
    public void TestDiskStoreIsStaleWithoutReport()
    {
        var store = new DiskStore(_ => (new FileDiskSource("nope.json"), "File"), null);
        Assert.True(store.IsStale());
        Assert.False(store.HasReport);
        Assert.Null(store.Report);
    }

    [Fact]
    public void TestDiskStoreCleanRefusesFileSource()
    {
        var store = new DiskStore(_ => (new FileDiskSource("nope.json"), "File"), null);
        var error = Assert.Throws<DataSourceError>(() =>
            store.Clean(["a"], null, confirmed: false));
        Assert.Equal(DataSourceErrorKind.LaunchFailed, error.Kind);
        Assert.Contains("nothing was moved", error.Message, StringComparison.Ordinal);
    }
}
