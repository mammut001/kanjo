using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>设置文件的读写（Windows 上是 `%APPDATA%\Kanjo\settings.json`，测试一律用临时目录）。</summary>
public sealed class SettingsStoreTests : KanjoTestCase
{
    [Fact]
    public void TestDefaultsMatchMacKeys()
    {
        var settings = AppSettings.InMemory();
        Assert.Equal("system", settings.Str(SettingsKeys.AppLanguage, SettingsDefaults.AppLanguage));
        Assert.Equal("cost", settings.Str(SettingsKeys.MenuBarMode, SettingsDefaults.MenuBarMode));
        Assert.Equal(30, settings.Int(SettingsKeys.RefreshMinutes, SettingsDefaults.RefreshMinutes));
        Assert.True(settings.Bool(SettingsKeys.ShowAmountInMenuBar, SettingsDefaults.ShowAmountInMenuBar));
        Assert.Equal("all", settings.Str(SettingsKeys.TimeRange, SettingsDefaults.TimeRange));
        Assert.Equal("weekly", settings.Str(SettingsKeys.PublishFrequency, SettingsDefaults.PublishFrequency));
        Assert.Equal("src/data/token-usage.json", settings.Str(SettingsKeys.PublishFilePath, SettingsDefaults.PublishFilePath));
        Assert.Equal("main", settings.Str(SettingsKeys.PublishBranch, SettingsDefaults.PublishBranch));

        // 默认值只影响读取，不写进文件
        Assert.False(settings.Has(SettingsKeys.AppLanguage));
    }

    [Fact]
    public void TestRoundTripPreservesTypes()
    {
        var dir = TempDir();
        var path = AppSettings.FilePathFor(dir, null);
        var settings = new AppSettings(path);
        settings.Set(SettingsKeys.AppLanguage, "zh-Hans");
        settings.Set(SettingsKeys.RefreshMinutes, 45);
        settings.Set(SettingsKeys.ShowAmountInMenuBar, false);
        settings.Set(SettingsKeys.TimeRange, "days7");

        var reloaded = new AppSettings(path);
        Assert.Equal("zh-Hans", reloaded.GetString(SettingsKeys.AppLanguage));
        Assert.Equal(45, reloaded.GetInt(SettingsKeys.RefreshMinutes));
        Assert.False(reloaded.GetBool(SettingsKeys.ShowAmountInMenuBar));
        Assert.Equal("days7", reloaded.GetString(SettingsKeys.TimeRange));
    }

    [Fact]
    public void TestRemoveAndNullDeleteKey()
    {
        var dir = TempDir();
        var path = AppSettings.FilePathFor(dir, null);
        var settings = new AppSettings(path);
        settings.Set("a", "1");
        settings.Set("b", "2");
        settings.Remove("a");
        settings.Set("b", (string?)null);

        var reloaded = new AppSettings(path);
        Assert.False(reloaded.Has("a"));
        Assert.False(reloaded.Has("b"));
    }

    [Fact]
    public void TestBrokenFileFallsBackToEmpty()
    {
        var dir = TempDir();
        var path = AppSettings.FilePathFor(dir, null);
        File.WriteAllText(path, "{ this is not json");
        var settings = new AppSettings(path);
        Assert.False(settings.Has(SettingsKeys.AppLanguage));
        Assert.Equal("system", settings.Str(SettingsKeys.AppLanguage, SettingsDefaults.AppLanguage));
    }

    [Fact]
    public void TestTolerantNumericAndBoolReads()
    {
        var dir = TempDir();
        var path = AppSettings.FilePathFor(dir, null);
        File.WriteAllText(path, """{"refreshMinutes": "20", "showAmountInMenuBar": 1, "weird": "x"}""");
        var settings = new AppSettings(path);
        Assert.Equal(20, settings.GetInt(SettingsKeys.RefreshMinutes));
        Assert.True(settings.GetBool(SettingsKeys.ShowAmountInMenuBar));
        Assert.Null(settings.GetInt("weird"));
    }

    [Fact]
    public void TestLanguageFlowsIntoLocalization()
    {
        var dir = TempDir();
        var settings = new AppSettings(AppSettings.FilePathFor(dir, "language-test"));
        settings.Set(SettingsKeys.AppLanguage, "fr");
        L10n.Store = settings;
        L10n.ResetCache();
        Assert.Equal("fr", L10n.CurrentLanguage);
        Assert.Equal("Terminé", L10n.Tr("common.done"));
    }

    [Fact]
    public void TestDatesRoundTrip()
    {
        var settings = AppSettings.InMemory();
        var when = new DateTimeOffset(2026, 10, 25, 9, 57, 0, TimeSpan.Zero);
        settings.SetDate(SettingsKeys.PublishLastSuccessAt, when);
        Assert.Equal(when, settings.GetDate(SettingsKeys.PublishLastSuccessAt));
    }

    [Fact]
    public void TestDefaultDirectoryUsesAppData()
    {
        var dir = AppSettings.DefaultDirectory();
        Assert.NotEmpty(dir);
        if (OperatingSystem.IsWindows())
        {
            var appData = Environment.GetEnvironmentVariable("APPDATA");
            if (!string.IsNullOrEmpty(appData)) Assert.Equal(Path.Combine(appData, "Kanjo"), dir);
        }
    }
}
