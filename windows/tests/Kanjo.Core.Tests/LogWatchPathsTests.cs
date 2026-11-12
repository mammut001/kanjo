using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 监听哪些目录（Mac <c>ReportStore.setupWatcher</c> 的准入规则 + CLI `paths --json` 的展平）。
/// </summary>
public sealed class LogWatchPathsTests : KanjoTestCase
{
    [Fact]
    public void TestOnlyCliSourceWithoutOverrideWatches()
    {
        Assert.True(LogWatchPaths.ShouldWatch(false, SourceKind.Cli));
        Assert.False(LogWatchPaths.ShouldWatch(true, SourceKind.Cli));
        Assert.False(LogWatchPaths.ShouldWatch(false, SourceKind.File));
        Assert.False(LogWatchPaths.ShouldWatch(true, SourceKind.File));
    }

    [Fact]
    public void TestFlattenDeduplicatesAcrossAgents()
    {
        var map = new Dictionary<string, IReadOnlyList<string>>(StringComparer.Ordinal)
        {
            ["claude"] = [@"C:\Users\x\.claude\projects", @"C:\Users\x\.claude"],
            ["codex"] = [@"C:\Users\x\.codex", @"C:\Users\x\.claude"],
            ["grok"] = [],
            ["qwen"] = [@"c:\users\x\.CLAUDE"], // Windows 路径不区分大小写：算重复
            ["empty"] = [""],
        };

        var paths = LogWatchPaths.Flatten(map);

        Assert.Equal([@"C:\Users\x\.claude\projects", @"C:\Users\x\.claude", @"C:\Users\x\.codex"], paths);
    }

    [Fact]
    public void TestFlattenHandlesMissingMap()
    {
        Assert.Empty(LogWatchPaths.Flatten(null));
        Assert.Empty(LogWatchPaths.Flatten(new Dictionary<string, IReadOnlyList<string>>()));
    }

    [Fact]
    public void TestExistingFiltersMissingDirectories()
    {
        var dir = TempDir();
        var paths = new[] { dir, Path.Combine(dir, "nope"), "" };
        Assert.Equal([dir], LogWatchPaths.Existing(paths));
    }
}
