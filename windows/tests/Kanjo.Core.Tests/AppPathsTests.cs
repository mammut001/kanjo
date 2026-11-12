using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 安装 / 数据目录的分离与数据源解析。
///
/// 背景：批次 5 第一版把 Velopack 的 packId 设成 <c>Kanjo</c>，安装根目录就是
/// <c>%LOCALAPPDATA%\Kanjo</c>——Windows 路径不区分大小写，和 CLI 的数据 / 缓存目录
/// <c>%LOCALAPPDATA%\kanjo</c> 是同一个文件夹。先用过 CLI / 家庭上报的机器上 Setup.exe
/// 会报「已安装」，卸载还会删掉账本。这里的测试就是防止再撞一次。
/// </summary>
public sealed class AppPathsTests : KanjoTestCase
{
    /// <summary>安装根目录不能等于任何数据 / 缓存目录（不区分大小写）。</summary>
    [Fact]
    public void TestInstallRootDiffersFromEveryDataDirectory()
    {
        var installRoot = AppPaths.InstallRoot;
        var collisions = AppPaths.DataDirectories()
            .Select(d => Path.Combine(d.Root == "APPDATA" ? AppPaths.AppData() : AppPaths.LocalAppData(), d.Relative))
            .Where(dir => AppPaths.SameDirectory(dir, installRoot))
            .ToList();

        Assert.True(collisions.Count == 0,
            $"install root {installRoot} collides with: {string.Join(", ", collisions)}");
    }

    /// <summary>尤其是 CLI 的数据 / 缓存目录——这是真实撞过的那个。</summary>
    [Fact]
    public void TestInstallRootIsNotTheCliDataDirectory()
    {
        var local = AppPaths.LocalAppData();
        Assert.Equal(Path.Combine(local, "KanjoApp"), AppPaths.InstallRoot);
        Assert.False(AppPaths.SameDirectory(AppPaths.InstallRoot, Path.Combine(local, "kanjo")));
        Assert.False(AppPaths.SameDirectory(AppPaths.InstallRoot, Path.Combine(local, "kanjo", "cache")));
        Assert.False(AppPaths.SameDirectory(AppPaths.InstallRoot, Path.Combine(local, "kanjo", "data")));
        Assert.False(AppPaths.SameDirectory(AppPaths.InstallRoot, Path.Combine(local, "KanjoFamily")));
    }

    /// <summary>packId / 产品名 / 数据目录名的关系：安装根叫 KanjoApp，产品名仍是 Kanjo。</summary>
    [Fact]
    public void TestNames()
    {
        Assert.Equal("KanjoApp", AppPaths.InstallRootName);
        Assert.Equal("Kanjo", AppPaths.ProductName);
        // 数据目录保持原样，老用户（含 PowerShell 上报脚本）的数据不受影响。
        Assert.Equal("Kanjo", AppPaths.SettingsDirectoryName);
        Assert.Equal("kanjo", AppPaths.CliDirectoryName);
        Assert.Equal("KanjoFamily", AppPaths.FamilyInstallDirectoryName);
    }

    /// <summary>大小写不同、末尾分隔符不同都算同一个目录（Windows 语义）。</summary>
    [Fact]
    public void TestSameDirectoryIsCaseInsensitive()
    {
        Assert.True(AppPaths.SameDirectory(@"C:\Users\Me\AppData\Local\Kanjo",
            @"c:\users\me\appdata\local\kanjo"));
        Assert.True(AppPaths.SameDirectory(@"C:\Users\Me\AppData\Local\Kanjo\",
            @"C:\Users\Me\AppData\Local\Kanjo"));
        Assert.False(AppPaths.SameDirectory(@"C:\Users\Me\AppData\Local\Kanjo",
            @"C:\Users\Me\AppData\Local\KanjoApp"));
        Assert.False(AppPaths.SameDirectory(null, @"C:\x"));
        Assert.False(AppPaths.SameDirectory("", ""));
    }

    /// <summary>磁盘报告缓存落在 CLI 的 Local 目录里（文件名不冲突），不是安装目录。</summary>
    [Fact]
    public void TestDiskCacheLivesInCliDirectory()
    {
        var cache = new DiskReportCache();
        Assert.NotNull(cache.FilePath);
        var expected = Path.Combine(AppPaths.LocalAppData(), "kanjo", "disk-report.json");
        Assert.Equal(expected, cache.FilePath);
        Assert.False(AppPaths.SameDirectory(Path.GetDirectoryName(cache.FilePath)!, AppPaths.InstallRoot));
    }
}
