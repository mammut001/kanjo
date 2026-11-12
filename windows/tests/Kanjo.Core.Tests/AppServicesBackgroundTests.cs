using Kanjo.App;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// <see cref="AppServices"/> 的后台接线（用假计时器 / 假电源 / 假监听器，绝不碰真实时钟和真实设置）。
/// </summary>
public sealed class AppServicesBackgroundTests : KanjoTestCase
{
    private AppServices NewServices(FakeBackgroundScheduler timers, FakeLogWatcherFactory watchers,
        FakePowerMonitor power, params string[] args)
    {
        var settings = AppSettings.InMemory();
        settings.Set(SettingsKeys.AppLanguage, "en");
        return new AppServices(settings, args, TempDir(), timers, watchers, power);
    }

    [Fact]
    public void TestRefreshLoadsReportAndRecordsTime()
    {
        var services = NewServices(new FakeBackgroundScheduler(), new FakeLogWatcherFactory(),
            new FakePowerMonitor(), "--data", FixturePath);

        Assert.Null(services.Report);
        services.Refresh();
        Assert.NotNull(services.Report);
        Assert.Null(services.Error);
        Assert.NotNull(services.LastRefresh);
        Assert.False(services.IsLoading);
        Assert.False(services.Background.IsRefreshing);
    }

    [Fact]
    public void TestRefreshFailureKeepsPreviousReport()
    {
        var path = Path.Combine(TempDir(), "usage.json");
        File.Copy(FixturePath, path);
        var services = NewServices(new FakeBackgroundScheduler(), new FakeLogWatcherFactory(),
            new FakePowerMonitor(), "--data", path);

        services.Refresh();
        Assert.NotNull(services.Report);

        File.Delete(path);
        services.Refresh();
        Assert.NotNull(services.Report); // 和 Mac 一样保留上一份
        Assert.NotNull(services.Error);
        Assert.Contains("not found", services.Error, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void TestDiskPrefetchScheduledAfterRefresh()
    {
        var timers = new FakeBackgroundScheduler();
        var services = NewServices(timers, new FakeLogWatcherFactory(), new FakePowerMonitor(),
            "--data", FixturePath);

        services.Refresh();
        Assert.True(services.DiskPrefetch.DidSchedule);
        // 第一次预取等 15 秒（Mac 的 DiskStore.schedulePrefetch(delay: 15)）。
        Assert.Equal(TimeSpan.FromSeconds(15), timers.LastPending!.Delay);
    }

    [Fact]
    public void TestDiskPrefetchSkippedWithDiskOverride()
    {
        var timers = new FakeBackgroundScheduler();
        var disk = Path.Combine(TempDir(), "disk.json");
        var services = NewServices(timers, new FakeLogWatcherFactory(), new FakePowerMonitor(),
            "--data", FixturePath, "--disk-data", disk);

        services.Refresh();
        Assert.False(services.DiskPrefetch.DidSchedule);
    }

    [Fact]
    public void TestWatcherNotCreatedForFileSource()
    {
        var watchers = new FakeLogWatcherFactory();
        var services = NewServices(new FakeBackgroundScheduler(), watchers, new FakePowerMonitor());
        services.Settings.Set(SettingsKeys.SourceKind, "file");

        services.SetupWatcher();
        Assert.Empty(watchers.Created);
        Assert.False(services.Background.IsWatching);
        Assert.Empty(services.LogPaths);
    }

    [Fact]
    public void TestWatcherNotCreatedWithDataOverride()
    {
        var watchers = new FakeLogWatcherFactory();
        var services = NewServices(new FakeBackgroundScheduler(), watchers, new FakePowerMonitor(),
            "--data", FixturePath);
        services.Settings.Set(SettingsKeys.SourceKind, "cli");

        services.SetupWatcher();
        Assert.Empty(watchers.Created);
    }

    [Fact]
    public void TestFallbackTimerFromSettingAndRestart()
    {
        var timers = new FakeBackgroundScheduler();
        var services = NewServices(timers, new FakeLogWatcherFactory(), new FakePowerMonitor(),
            "--data", FixturePath);
        services.Settings.Set(SettingsKeys.RefreshMinutes, 30);

        services.RestartFallbackTimer();
        Assert.Equal(TimeSpan.FromMinutes(30), timers.Periodic!.Interval);

        services.Settings.Set(SettingsKeys.RefreshMinutes, 60);
        services.RestartFallbackTimer();
        Assert.Equal(TimeSpan.FromMinutes(60), timers.Periodic!.Interval);
        Assert.Equal(60, services.Background.FallbackMinutes);

        services.Settings.Set(SettingsKeys.RefreshMinutes, 0);
        services.RestartFallbackTimer();
        Assert.False(services.Background.HasFallbackTimer);
    }

    [Fact]
    public void TestPanelOpenedRefreshesThroughEngine()
    {
        var services = NewServices(new FakeBackgroundScheduler(), new FakeLogWatcherFactory(),
            new FakePowerMonitor(), "--data", FixturePath);

        services.OnPanelOpened();
        Assert.NotNull(services.Report);
        Assert.NotNull(services.LastRefresh);
        Assert.False(services.Background.IsRefreshing);
    }

    [Fact]
    public void TestPowerEventsReachScheduler()
    {
        var timers = new FakeBackgroundScheduler();
        var power = new FakePowerMonitor();
        var services = NewServices(timers, new FakeLogWatcherFactory(), power, "--data", FixturePath);
        Assert.True(power.IsStarted);

        power.RaiseSuspend();
        Assert.True(services.Background.IsAsleep);

        power.RaiseLowPowerMode(true);
        Assert.True(services.Background.IsLowPowerMode);
        power.RaiseLowPowerMode(false);
        Assert.False(services.Background.IsLowPowerMode);

        power.RaiseResume();
        Assert.False(services.Background.IsAsleep);
    }

    [Fact]
    public void TestSnapshotModeDisablesBackground()
    {
        var power = new FakePowerMonitor();
        var services = NewServices(new FakeBackgroundScheduler(), new FakeLogWatcherFactory(), power,
            "--snapshot", Path.Combine(TempDir(), "x.png"), "--data", FixturePath);

        Assert.True(services.SnapshotMode);
        Assert.False(services.RunsBackground);
        Assert.False(power.IsStarted);
    }

    [Fact]
    public void TestWindowModeRunsBackground()
    {
        var services = NewServices(new FakeBackgroundScheduler(), new FakeLogWatcherFactory(),
            new FakePowerMonitor(), "--window", "--data", FixturePath);
        Assert.True(services.RunsBackground);
    }

    [Fact]
    public void TestApplySettingsRearrangesTimer()
    {
        var timers = new FakeBackgroundScheduler();
        var services = NewServices(timers, new FakeLogWatcherFactory(), new FakePowerMonitor(),
            "--data", FixturePath);
        services.Settings.Set(SettingsKeys.RefreshMinutes, 15);

        // 刷新放到后台线程：等它通知「加载完成」（用信号等待，不用真实时钟）。
        using var done = new ManualResetEventSlim();
        services.Changed += () =>
        {
            if (!services.IsLoading && services.Report is not null) done.Set();
        };

        services.ApplySettings();
        Assert.True(done.Wait(TimeSpan.FromSeconds(10)));
        Assert.Equal(TimeSpan.FromMinutes(15), timers.Periodic!.Interval);
    }

    [Fact]
    public void TestReportRunnerOverrideIsUsed()
    {
        var services = NewServices(new FakeBackgroundScheduler(), new FakeLogWatcherFactory(),
            new FakePowerMonitor(), "--data", FixturePath);
        var fake = new FakeReportRunner();
        services.UseReportRunner(fake);
        Assert.Same(fake, services.ReportRunnerOrNull());

        // 注入之后，发布 / 家庭上报都走假实现（不会起真实进程）。
        services.Settings.Set(SettingsKeys.PublishEnabled, true);
        services.Settings.Set(SettingsKeys.PublishRepoPath, "/repo");
        services.Publish.ReportDidRefresh(LoadFixture());
        Assert.Single(fake.Calls);
        Assert.Equal("publish-usage", fake.Calls[0].Kind);
    }
}
