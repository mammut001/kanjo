using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 对应 Mac 版 AppDefaultsTests：suite 解析与隔离存储。
/// Mac 版用 UserDefaults；Windows 版用 JSON 文件（settings.json / settings-&lt;name&gt;.json）。
/// </summary>
public sealed class AppDefaultsTests : KanjoTestCase
{
    private static readonly Dictionary<string, string> NoEnv = new();

    [Fact]
    public void TestPicksSuiteFromCommandLineArgument()
    {
        Assert.Equal("my-test-suite", AppSettings.SuiteName(["--defaults-suite", "my-test-suite"], NoEnv));
        Assert.Equal("another-suite", AppSettings.SuiteName(["--defaults-suite=another-suite"], NoEnv));
    }

    [Fact]
    public void TestPicksSuiteFromEnvironment()
    {
        Assert.Equal("env-test-suite", AppSettings.SuiteName([], new Dictionary<string, string>
        {
            ["KANJO_DEFAULTS_SUITE"] = "env-test-suite",
        }));
    }

    [Fact]
    public void TestCommandLineArgumentOverridesEnvironment()
    {
        Assert.Equal("cli-suite", AppSettings.SuiteName(["--defaults-suite", "cli-suite"],
            new Dictionary<string, string> { ["KANJO_DEFAULTS_SUITE"] = "env-suite" }));
    }

    [Fact]
    public void TestWindowDefaultsToKanjoPreview()
    {
        Assert.Equal(AppSettings.PreviewSuiteName, AppSettings.SuiteName(["--window"], NoEnv));
        Assert.Equal(AppSettings.PreviewSuiteName, AppSettings.SuiteName(["--window", "--route", "overview"], NoEnv));
    }

    [Fact]
    public void TestSnapshotDefaultsToKanjoPreview()
    {
        Assert.Equal(AppSettings.PreviewSuiteName, AppSettings.SuiteName(["--snapshot", "out.png"], NoEnv));
        Assert.Equal(AppSettings.PreviewSuiteName, AppSettings.SuiteName(["--snapshot=out.png"], NoEnv));
        Assert.Equal(AppSettings.PreviewSuiteName, AppSettings.SuiteName(
            ["--snapshot", "out.png", "--route", "overview", "--snapshot-scale", "2"], NoEnv));
    }

    [Fact]
    public void TestDefaultsSuiteOverridesWindow()
    {
        Assert.Equal("explicit-preview", AppSettings.SuiteName(
            ["--window", "--defaults-suite", "explicit-preview"], NoEnv));
        Assert.Equal("explicit-preview", AppSettings.SuiteName(
            ["--defaults-suite", "explicit-preview", "--window"], NoEnv));
        Assert.Equal("env-suite", AppSettings.SuiteName(["--window"],
            new Dictionary<string, string> { ["KANJO_DEFAULTS_SUITE"] = "env-suite" }));
    }

    [Fact]
    public void TestDefaultsSuiteOverridesSnapshot()
    {
        Assert.Equal("explicit-preview", AppSettings.SuiteName(
            ["--snapshot", "out.png", "--defaults-suite", "explicit-preview"], NoEnv));
        Assert.Equal("explicit-preview", AppSettings.SuiteName(
            ["--defaults-suite", "explicit-preview", "--snapshot", "out.png"], NoEnv));
        Assert.Equal("env-suite", AppSettings.SuiteName(["--snapshot", "out.png"],
            new Dictionary<string, string> { ["KANJO_DEFAULTS_SUITE"] = "env-suite" }));
    }

    [Fact]
    public void TestReturnsNilWhenAbsent()
    {
        Assert.Null(AppSettings.SuiteName([], NoEnv));
        Assert.Null(AppSettings.SuiteName(["--data", "/tmp/sample.json"], NoEnv));
        Assert.Null(AppSettings.SuiteName(["--defaults-suite"], NoEnv));
        Assert.Null(AppSettings.SuiteName(["--defaults-suite", ""], NoEnv));
        Assert.Null(AppSettings.SuiteName([], new Dictionary<string, string> { ["KANJO_DEFAULTS_SUITE"] = "" }));
    }

    [Fact]
    public void TestDefaultFileNames()
    {
        Assert.Equal("settings.json", AppSettings.FileNameForSuite(null));
        Assert.Equal("settings-kanjo-preview.json", AppSettings.FileNameForSuite("kanjo-preview"));
        Assert.Equal(Path.Combine("/tmp/kanjo", "settings.json"), AppSettings.FilePathFor("/tmp/kanjo", null));
    }

    [Fact]
    public void TestResolvesIsolatedStore()
    {
        var dir = TempDir();
        var store = AppSettings.ForLaunch(["--defaults-suite", "isolated"], NoEnv, dir);
        Assert.Equal(Path.Combine(dir, "settings-isolated.json"), store.FilePath);

        store.Set("kanjo_isolated_key", "isolatedValue");
        Assert.Equal("isolatedValue", store.GetString("kanjo_isolated_key"));
        Assert.False(File.Exists(Path.Combine(dir, "settings.json")));

        var reloaded = new AppSettings(store.FilePath!);
        Assert.Equal("isolatedValue", reloaded.GetString("kanjo_isolated_key"));
    }

    [Fact]
    public void TestSuiteStoreIsIsolatedFromDefault()
    {
        var dir = TempDir();
        var suite = AppSettings.ForLaunch(["--defaults-suite", "suite"], NoEnv, dir);
        var standard = new AppSettings(AppSettings.FilePathFor(dir, null));

        suite.Set("testKey", "suiteValue");
        Assert.Equal("suiteValue", suite.GetString("testKey"));
        Assert.Null(standard.GetString("testKey"));

        standard.Set("standardOnlyKey", "standardValue");
        Assert.Null(suite.GetString("standardOnlyKey"));
    }
}
