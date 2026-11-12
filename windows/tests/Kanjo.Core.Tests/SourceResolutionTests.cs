using Kanjo.App;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 数据源解析（Mac 的 <c>ReportStore.init</c> / <c>makeSource</c>）：
/// 找得到 CLI 就默认走 CLI，示例数据只在「文件来源 + 路径留空」时出现。
///
/// 安装版曾经默认成「文件」来源，于是面板显示的是 sample.json（$275.99 / PocketTimer…）
/// 而不是这台机器的真实数据。
/// </summary>
public sealed class SourceResolutionTests : KanjoTestCase
{
    [Fact]
    public void TestExplicitSettingWins()
    {
        Assert.Equal(SourceKind.File, SourceResolution.Resolve("file"));
        Assert.Equal(SourceKind.Cli, SourceResolution.Resolve("cli"));
    }

    [Fact]
    public void TestUnknownSettingFallsBackToDefault()
    {
        // 空的 / 坏的值都按「默认来源」处理，而不是写死成文件。
        Assert.Equal(SourceResolution.DefaultKind(), SourceResolution.Resolve(null));
        Assert.Equal(SourceResolution.DefaultKind(), SourceResolution.Resolve(""));
        Assert.Equal(SourceResolution.DefaultKind(), SourceResolution.Resolve("garbage"));
    }

    /// <summary>仓库里就有 cli/（测试是 Debug 构建），所以默认来源必须是 CLI。</summary>
    [Fact]
    public void TestDefaultIsCliWhenACliDirectoryExists()
    {
        Assert.True(DefaultPaths.CliDirectoryExists);
        Assert.Equal(SourceKind.Cli, SourceResolution.DefaultKind());
        Assert.Equal(SourceKind.Cli, SourceResolution.Resolve(null));
    }

    /// <summary>没存设置时不会悄悄显示示例数据（安装版的真实场景）。</summary>
    [Fact]
    public void TestSampleDataIsNeverTheDefaultWhenCliExists()
    {
        Assert.False(SourceResolution.UsesSampleData(null, null));
        Assert.False(SourceResolution.UsesSampleData(null, ""));
    }

    /// <summary>示例数据只在文件来源 + 路径留空时用（Mac 的 settings.file_note）。</summary>
    [Fact]
    public void TestSampleDataOnlyForEmptyFilePath()
    {
        Assert.True(SourceResolution.UsesSampleData("file", null));
        Assert.True(SourceResolution.UsesSampleData("file", "   "));
        Assert.False(SourceResolution.UsesSampleData("file", "/tmp/usage.json"));
        Assert.False(SourceResolution.UsesSampleData("cli", null));
        Assert.False(SourceResolution.UsesSampleData("cli", ""));
    }

    [Fact]
    public void TestFileFor()
    {
        Assert.Equal(DefaultPaths.SampleFixture, SourceResolution.FileFor(null));
        Assert.Equal(DefaultPaths.SampleFixture, SourceResolution.FileFor("  "));
        var path = Path.Combine(TempDir(), "usage.json");
        Assert.Equal(path, SourceResolution.FileFor(path));
    }

    /// <summary>
    /// 安装版的真实布局：&lt;appdir&gt;\python\python.exe + &lt;appdir&gt;\cli。
    /// 默认命令必须是这条（设置页的占位符 = 实际执行的命令）。
    /// </summary>
    [Fact]
    public void TestDefaultCommandUsesBundledPythonWhenPresent()
    {
        if (DefaultPaths.BundledPython is { } bundled)
        {
            Assert.StartsWith(bundled.Contains(' ') ? $"\"{bundled}\"" : bundled,
                DefaultPaths.DefaultCliCommand, StringComparison.Ordinal);
        }
        Assert.EndsWith("-m kanjo export", DefaultPaths.DefaultCliCommand, StringComparison.Ordinal);
        Assert.Equal(DefaultPaths.DefaultCliCommand, CliRunner.DefaultCliCommand);
    }

    /// <summary>
    /// AppServices 的默认来源与设置页一致（两处以前用不同的回退规则，正是这个不一致让
    /// 设置页写着「CLI」、面板显示的却是示例数据）。
    /// </summary>
    [Fact]
    public void TestAppServicesDefaultsToCli()
    {
        var settings = AppSettings.InMemory();
        settings.Set(SettingsKeys.AppLanguage, "en");
        var services = new AppServices(settings, [], TempDir());
        Assert.StartsWith("Command:", services.DescribeSource());
        Assert.DoesNotContain("sample.json", services.DescribeSource());
    }

    [Fact]
    public void TestAppServicesFileSourceDescribesSample()
    {
        var settings = AppSettings.InMemory();
        settings.Set(SettingsKeys.AppLanguage, "en");
        settings.Set(SettingsKeys.SourceKind, "file");
        var services = new AppServices(settings, [], TempDir());
        Assert.Equal($"File: {DefaultPaths.SampleFixture}", services.DescribeSource());
    }

    /// <summary>`--print-source` 的输出能解析成 key=value，且报的是 CLI + 包里的目录。</summary>
    [Fact]
    public void TestPrintSourceDiagnostics()
    {
        var output = new StringWriter();
        var code = SourceDiagnostics.Print(output, ["--defaults-suite", "print-source"]);
        Assert.Equal(0, code);

        var map = output.ToString()
            .Split('\n', StringSplitOptions.RemoveEmptyEntries)
            .Select(line => line.Split('=', 2))
            .Where(parts => parts.Length == 2)
            .ToDictionary(parts => parts[0], parts => parts[1], StringComparer.Ordinal);

        Assert.Equal("cli", map["source"]);
        Assert.Equal("false", map["sampleData"]);
        Assert.Equal(AppPaths.InstallRoot, map["installRoot"]);
        Assert.Equal(DefaultPaths.AppDirectory, map["appDir"]);
        Assert.NotEqual("", map["python"]);
        Assert.Equal(DefaultPaths.RepoCliDirectory, map["cliDir"]);
        Assert.Equal("0.5.1", map["cliVersion"]);
    }

    /// <summary>诊断是只读的：不能因为读了一次就创建 / 改写设置文件。</summary>
    [Fact]
    public void TestPrintSourceDoesNotWriteSettings()
    {
        var dir = TempDir();
        var before = Directory.GetFiles(dir);
        var output = new StringWriter();
        SourceDiagnostics.Print(output, ["--defaults-suite", "readonly"]);
        Assert.Equal(before.Length, Directory.GetFiles(dir).Length);
        Assert.False(File.Exists(Path.Combine(dir, "settings-readonly.json")));
    }
}
