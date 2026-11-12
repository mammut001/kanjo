using Xunit;

namespace Kanjo.Core.Tests;

public sealed class PathKindsTests : KanjoTestCase
{
    private const string Home = "/Users/me";

    [Fact]
    public void TestTemporaryPaths()
    {
        string[] temps =
        [
            "/tmp/foo",
            "/tmp",
            "/private/tmp/claude-501/-Users-me-proj/abc/scratchpad/x",
            "/var/folders/xy/T/build",
            "/private/var/folders/xy/T/build",
            "~/.gemini/antigravity-cli/brain/123/scratch/watch-ui",
            "/Users/me/.gemini/antigravity-cli/brain/123",
            "~/.gemini/antigravity/brain/123/scratch/watch-ui",
            "/Users/me/.gemini/antigravity/brain/123",
            "~/.claude/projects/foo",
            "/Users/me/.codex/worktrees/a1b2/proj",
            "/Users/me/work/scratchpad",
            "/Users/me/work/scratch/thing",
            "/Users/me/proj/.worktrees/feature",
            "/Volumes/ext/worktrees/proj",
        ];
        foreach (var p in temps) Assert.True(PathKinds.IsTemporaryPath(p, Home), p);
    }

    [Fact]
    public void TestPrimaryPaths()
    {
        string[] primaries =
        [
            "/Users/me/Documents/GitHub/FocusApp",
            "/Users/me/Documents/GitHub/FocusApp-fixes-146",
            "~/code/proj",
            "/Users/me/orca/workspaces/FocusApp/mako",
            "/Users/me/tmp/proj",         // 不是 /tmp/ 前缀
            "/Users/me/.geminix/proj",    // 不是 ~/.gemini/
            "/Users/other/.claude/proj",  // 别人的 home
            "/Users/me/scratchpads/proj", // 分量必须完全相等
            "/Users/me/my-scratch/proj",
            "/Users/me/worktrees-old/proj",
        ];
        foreach (var p in primaries) Assert.False(PathKinds.IsTemporaryPath(p, Home), p);
    }

    [Fact]
    public void TestSplitPathsPreservesOrder()
    {
        string[] input =
        [
            "/tmp/a",
            "/Users/me/p1",
            "/Users/me/x/scratchpad/b",
            "/Users/me/p2",
            "~/.codex/c",
            "/Users/me/p3",
        ];
        var (primary, temporary) = PathKinds.SplitPaths(input, Home);
        Assert.Equal(["/Users/me/p1", "/Users/me/p2", "/Users/me/p3"], primary.ToArray());
        Assert.Equal(["/tmp/a", "/Users/me/x/scratchpad/b", "~/.codex/c"], temporary.ToArray());
        Assert.Empty(PathKinds.SplitPaths([], Home).Primary);
    }

    [Fact]
    public void TestWindowsTempDirsAreTemporary()
    {
        // Windows 上 %TEMP% / %LOCALAPPDATA%\Temp 都要算临时目录。
        var temp = Environment.GetEnvironmentVariable("TEMP") ?? Path.GetTempPath();
        Assert.True(PathKinds.IsTemporaryPath(Path.Combine(temp, "build-123")));
        var local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if (!string.IsNullOrEmpty(local))
        {
            Assert.True(PathKinds.IsTemporaryPath(Path.Combine(local, "Temp", "x")));
            Assert.False(PathKinds.IsTemporaryPath(Path.Combine(local, "Kanjo", "settings.json")));
        }
        // Windows 盘符路径的 worktrees 分量同样算临时
        Assert.True(PathKinds.IsTemporaryPath(@"C:\Users\me\proj\.worktrees\feature"));
        Assert.False(PathKinds.IsTemporaryPath(@"C:\Users\me\Documents\GitHub\FocusApp"));
    }
}
