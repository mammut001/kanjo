using System.Text.RegularExpressions;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 打包相关的静态检查（不需要 Windows 就能跑）：版本号只有一个来源、图标是多尺寸 .ico、
/// 安装包要用的资源都在仓库里。这些在批次 5 之前从来没有被测过。
/// </summary>
public sealed class PackagingTests : KanjoTestCase
{
    private static string Repo => DefaultPaths.RepoRoot
        ?? throw new InvalidOperationException("repo root unavailable");

    private static string ReadRepoFile(params string[] parts) =>
        File.ReadAllText(Path.Combine([Repo, .. parts]));

    private static string VersionFile => ReadRepoFile("VERSION").Trim();

    /// <summary>发布文件夹里必须有这些文件（build-release 的 verify 步骤和这里保持一致）。</summary>
    [Fact]
    public void TestVersionFileIsSemantic()
    {
        Assert.Matches(@"^\d+\.\d+\.\d+$", VersionFile);
    }

    /// <summary>App 版本 == CLI 版本：两边都从 VERSION 来（csproj 用 MSBuild 读，CLI 是 __init__.py）。</summary>
    [Fact]
    public void TestAppVersionMatchesCliVersion()
    {
        var app = typeof(Kanjo.App.Program).Assembly.GetName().Version;
        Assert.NotNull(app);
        Assert.Equal(VersionFile, $"{app!.Major}.{app.Minor}.{app.Build}");

        var init = ReadRepoFile("cli", "kanjo", "__init__.py");
        var match = Regex.Match(init, "__version__\\s*=\\s*\"([^\"]+)\"");
        Assert.True(match.Success, "cli/kanjo/__init__.py has no __version__");
        Assert.Equal(VersionFile, match.Groups[1].Value);
    }

    /// <summary>应用图标是 16–256 的多尺寸 .ico（Windows 从里面按 DPI 挑一档）。</summary>
    [Theory]
    [InlineData("Kanjo.ico")]
    [InlineData("Tray.ico")]
    [InlineData("TrayError.ico")]
    public void TestIconsAreMultiSize(string name)
    {
        var path = Path.Combine(Repo, "windows", "src", "Kanjo.App", "Assets", name);
        Assert.True(File.Exists(path), path);

        var bytes = File.ReadAllBytes(path);
        Assert.True(bytes.Length > 6);
        // ICO header: reserved=0, type=1, count
        Assert.Equal(0, BitConverter.ToUInt16(bytes, 0));
        Assert.Equal(1, BitConverter.ToUInt16(bytes, 2));
        var count = BitConverter.ToUInt16(bytes, 4);
        Assert.True(count >= 4, $"{name} has only {count} images");

        var sizes = new List<int>();
        for (var i = 0; i < count; i++)
        {
            var width = bytes[6 + i * 16];
            sizes.Add(width == 0 ? 256 : width); // 0 means 256 in the ICO directory
        }
        Assert.Contains(16, sizes);
        Assert.Contains(32, sizes);
        Assert.Contains(256, sizes);
    }

    /// <summary>托盘图标的正常 / 出错两档必须是不同的文件（出错时图标要变红）。</summary>
    [Fact]
    public void TestTrayIconsDiffer()
    {
        var assets = Path.Combine(Repo, "windows", "src", "Kanjo.App", "Assets");
        var normal = File.ReadAllBytes(Path.Combine(assets, "Tray.ico"));
        var error = File.ReadAllBytes(Path.Combine(assets, "TrayError.ico"));
        Assert.NotEqual(normal.Length, error.Length);
        Assert.False(normal.SequenceEqual(error));
    }

    /// <summary>打包脚本要在：macOS（bash）与 Windows（pwsh）各一份，加上冒烟测试。</summary>
    [Fact]
    public void TestReleaseScriptsExist()
    {
        foreach (var script in new[] { "build-release.sh", "build-release.ps1", "smoke.ps1" })
        {
            var path = Path.Combine(Repo, "windows", "scripts", script);
            Assert.True(File.Exists(path), path);
            Assert.True(new FileInfo(path).Length > 0, path);
        }
    }

    /// <summary>
    /// Python 的下载地址和 SHA-256 在两个打包脚本、以及家庭上报安装脚本之间必须一致：
    /// 三处都在装同一份官方 embeddable 包，谁改了版本另外两处就会悄悄不一致。
    /// </summary>
    [Fact]
    public void TestPythonPinsMatchInstallerScript()
    {
        var installer = ReadRepoFile("scripts", "install-family-windows.ps1");
        var ps = ReadRepoFile("windows", "scripts", "build-release.ps1");
        var sh = ReadRepoFile("windows", "scripts", "build-release.sh");
        string[] files = [installer, ps, sh];

        foreach (var hash in new[]
                 {
                     "D34DB37675973785A2A539CD1C8DDE1B6D45665F48C615EF55274B3798BF9FD3",
                     "8D3F33BE9EB810F23C102F08475AF2854E50484B8E4E06275E937BE61CE3D2FB",
                 })
        {
            foreach (var text in files)
            {
                Assert.Contains(hash, text, StringComparison.OrdinalIgnoreCase);
            }
        }

        // Same embeddable version everywhere, and both architectures are handled.
        var versions = files
            .Select(text => Regex.Match(text, @"python-(\d+\.\d+\.\d+)-embed"))
            .ToList();
        Assert.All(versions, m => Assert.True(m.Success, "no python-<version>-embed URL"));
        var distinct = versions.Select(m => m.Groups[1].Value).Distinct().ToList();
        Assert.Single(distinct);
        Assert.Equal("3.12.8", distinct[0]);

        foreach (var text in files)
        {
            Assert.Contains("amd64", text);
            Assert.Contains("arm64", text);
        }
    }
}
