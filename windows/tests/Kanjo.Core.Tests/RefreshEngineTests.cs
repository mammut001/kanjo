using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 后台行为（批次 3）：文件监听 → 防抖 → 刷新、兜底定时器重排、睡眠 / 唤醒 / 节电模式、
/// 面板打开刷新。全部用假计时器与假监听器，不碰真实时钟。
/// </summary>
public sealed class RefreshEngineTests : KanjoTestCase
{
    private static DateTimeOffset At(double seconds) => DateTimeOffset.FromUnixTimeSeconds((long)seconds);

    private sealed class Clock
    {
        public DateTimeOffset Now { get; set; } = At(1_000);

        public void Advance(double seconds) => Now = Now.AddSeconds(seconds);
    }

    private static (RefreshEngine Engine, FakeBackgroundScheduler Timers, FakeLogWatcherFactory Watchers,
        FakePowerMonitor Power, Clock Clock, List<RefreshTrigger> Refreshes) NewEngine(int fallbackMinutes = 30)
    {
        var timers = new FakeBackgroundScheduler();
        var watchers = new FakeLogWatcherFactory();
        var power = new FakePowerMonitor();
        var clock = new Clock();
        var engine = new RefreshEngine(timers, () => clock.Now, fallbackMinutes);
        var refreshes = new List<RefreshTrigger>();
        engine.RefreshRequested += trigger => refreshes.Add(trigger);
        engine.Attach(watchers, power);
        return (engine, timers, watchers, power, clock, refreshes);
    }

    [Fact]
    public void TestFileEventSchedulesDebouncedRefresh()
    {
        var (engine, timers, watchers, _, clock, refreshes) = NewEngine();
        using var _engine = engine;
        watchers.Missing.Clear();
        engine.StartWatcher(["/tmp/kanjo-logs"]);
        Assert.True(engine.IsWatching);

        // 事件落在 t=1000；上次刷新时间是「很久以前」，所以只受 60 秒防抖限制。
        watchers.RaiseFileEvent();
        var pending = timers.LastPending;
        Assert.NotNull(pending);
        Assert.Equal(TimeSpan.FromSeconds(60), pending!.Delay);
        Assert.Empty(refreshes);

        // 防抖期间再来事件：重新计时（仍然是 60 秒，从最后一个事件算）。
        clock.Advance(10);
        watchers.RaiseFileEvent();
        Assert.Equal(TimeSpan.FromSeconds(60), timers.LastPending!.Delay);

        // 计时器到点 → 后台刷新一次。
        timers.LastPending!.Fire();
        Assert.Equal([RefreshTrigger.Background], refreshes);
    }

    [Fact]
    public void TestDebounceNeverWaitsLongerThanMaxWait()
    {
        var (engine, timers, watchers, _, clock, refreshes) = NewEngine();
        using var _engine = engine;
        engine.StartWatcher(["/tmp/kanjo-logs"]);

        // 每 40 秒一个事件：debounce 一直往后推，但 180 秒后必须刷。
        RefreshAction? last = null;
        for (var i = 0; i < 30 && refreshes.Count == 0; i++)
        {
            watchers.RaiseFileEvent();
            if (timers.LastPending is { IsPending: true } p)
            {
                last = new RefreshAction(RefreshActionKind.ScheduleRefresh, p.Delay);
                clock.Advance(Math.Min(40, p.Delay.TotalSeconds));
                p.Fire();
            }
        }
        Assert.NotEmpty(refreshes);
        Assert.NotNull(last);
        Assert.True(last!.Value.Delay <= RefreshScheduler.MaxDebounceWait);
    }

    [Fact]
    public void TestRefreshCompletionCoalescesEventsDuringRun()
    {
        var (engine, timers, watchers, _, clock, refreshes) = NewEngine();
        using var _engine = engine;
        engine.StartWatcher(["/tmp/kanjo-logs"]);

        engine.BeginRefresh();
        Assert.True(engine.IsRefreshing);
        Assert.Null(timers.LastPending); // 开始刷新会取消待触发的防抖任务

        watchers.RaiseFileEvent();
        Assert.Empty(refreshes);

        clock.Advance(5);
        engine.EndRefresh();
        Assert.True(engine.HasScheduledRefresh);
        timers.LastPending!.Fire();
        Assert.Equal([RefreshTrigger.Background], refreshes);
    }

    [Fact]
    public void TestFallbackTimerUsesSettingAndRestarts()
    {
        var (engine, timers, _, _, clock, refreshes) = NewEngine(fallbackMinutes: 0);
        using var _engine = engine;

        // 刚刷过一次（t=1000），所以兜底定时器到点那一刻还没到间隔。
        engine.BeginRefresh();
        engine.EndRefresh();

        // 0 = 关：没有定时器。
        engine.RestartFallbackTimer(0);
        Assert.False(engine.HasFallbackTimer);
        Assert.Null(timers.Periodic);

        // 打开：每 30 分钟一次；此时还没到 30 分钟，不刷。
        engine.RestartFallbackTimer(30);
        Assert.True(engine.HasFallbackTimer);
        Assert.Equal(TimeSpan.FromMinutes(30), timers.Periodic!.Interval);
        timers.Periodic.Fire();
        Assert.Empty(refreshes);

        // 改了间隔：旧定时器被销毁，新的是 15 分钟。
        var old = timers.Periodic!;
        engine.RestartFallbackTimer(15);
        Assert.True(old.WasCancelled);
        Assert.Equal(TimeSpan.FromMinutes(15), timers.Periodic!.Interval);
        Assert.Equal(15, engine.FallbackMinutes);

        // 过了兜底间隔再响：刷一次。
        clock.Advance(16 * 60);
        timers.Periodic!.Fire();
        Assert.Equal([RefreshTrigger.Background], refreshes);
    }

    [Fact]
    public void TestFallbackMigrationKeepsStoredSetting()
    {
        var (engine, timers, _, _, _, _) = NewEngine(fallbackMinutes: 0);
        using var _engine = engine;

        // 5 分钟是旧版的默认值：迁移成 30（和 RefreshScheduler 一致）。
        engine.RestartFallbackTimer(5);
        Assert.Equal(30, engine.FallbackMinutes);
        Assert.Equal(TimeSpan.FromMinutes(30), timers.Periodic!.Interval);
    }

    [Fact]
    public void TestSleepSuppressesAndWakeRefreshes()
    {
        var (engine, timers, watchers, power, clock, refreshes) = NewEngine();
        using var _engine = engine;
        engine.StartWatcher(["/tmp/kanjo-logs"]);
        Assert.True(power.IsStarted);

        // 先刷一次，把 lastRefresh 设在 t=1000。
        engine.BeginRefresh();
        engine.EndRefresh();

        power.RaiseSuspend();
        Assert.True(engine.IsAsleep);
        Assert.False(engine.HasScheduledRefresh);

        // 睡眠期间的事件只记下来，不安排刷新（Mac：pendingWakeRefresh）。
        clock.Advance(60);
        watchers.RaiseFileEvent();
        Assert.True(engine.PendingWakeRefresh);
        Assert.Null(timers.LastPending);
        Assert.Empty(refreshes);

        // 唤醒：距上次刷新已超过 120 秒 → 立刻刷。
        clock.Advance(120);
        power.RaiseResume();
        Assert.False(engine.IsAsleep);
        Assert.False(engine.PendingWakeRefresh);
        Assert.Equal([RefreshTrigger.Background], refreshes);
    }

    [Fact]
    public void TestWakeShortlyAfterRefreshSchedulesInsteadOfBursting()
    {
        var (engine, timers, watchers, power, clock, refreshes) = NewEngine();
        using var _engine = engine;
        engine.StartWatcher(["/tmp/kanjo-logs"]);

        engine.BeginRefresh();
        engine.EndRefresh();

        power.RaiseSuspend();
        watchers.RaiseFileEvent();
        clock.Advance(10);
        power.RaiseResume();

        // 距上次刷新只有 10 秒：安排剩下的 110 秒再刷，不立刻刷。
        Assert.Empty(refreshes);
        Assert.Equal(TimeSpan.FromSeconds(110), timers.LastPending!.Delay);
    }

    [Fact]
    public void TestLowPowerModeSuppressesAndResumes()
    {
        var (engine, timers, _, power, clock, refreshes) = NewEngine();
        using var _engine = engine;

        engine.BeginRefresh();
        engine.EndRefresh();
        engine.RestartFallbackTimer(30);

        power.RaiseLowPowerMode(true);
        Assert.True(engine.IsLowPowerMode);

        clock.Advance(3600);
        timers.Periodic!.Fire();
        Assert.True(engine.PendingWakeRefresh);
        Assert.Empty(refreshes);

        // 关掉节电模式：补刷一次（距上次刷新已经很久）。
        power.RaiseLowPowerMode(false);
        Assert.False(engine.IsLowPowerMode);
        Assert.Equal([RefreshTrigger.Background], refreshes);
    }

    [Fact]
    public void TestPanelOpenRefreshesOnlyWhenStale()
    {
        var (engine, _, _, _, clock, refreshes) = NewEngine();
        using var _engine = engine;

        // 从没刷过 → 打开面板就刷。
        engine.OnPanelOpened();
        Assert.Equal([RefreshTrigger.Background], refreshes);

        refreshes.Clear();
        engine.BeginRefresh();
        engine.EndRefresh();

        // 刚刷过：不刷。
        clock.Advance(60);
        engine.OnPanelOpened();
        Assert.Empty(refreshes);

        // 超过 120 秒：刷。
        clock.Advance(90);
        engine.OnPanelOpened();
        Assert.Equal([RefreshTrigger.Background], refreshes);
    }

    [Fact]
    public void TestUserRefreshCancelsPendingDebounce()
    {
        var (engine, timers, watchers, _, _, refreshes) = NewEngine();
        using var _engine = engine;
        engine.StartWatcher(["/tmp/kanjo-logs"]);

        watchers.RaiseFileEvent();
        var debounced = timers.LastPending!;
        Assert.True(debounced.IsPending);

        engine.RequestRefresh();
        Assert.True(debounced.WasCancelled);
        Assert.Equal([RefreshTrigger.UserInitiated], refreshes);
    }

    [Fact]
    public void TestWatcherSkipsMissingDirectories()
    {
        var (engine, _, watchers, _, _, _) = NewEngine();
        using var _engine = engine;

        engine.StartWatcher(["/tmp/kanjo-missing"]);
        watchers.Missing.Add("/tmp/kanjo-missing");
        engine.StartWatcher(["/tmp/kanjo-missing"]);
        Assert.False(engine.IsWatching);
        Assert.Empty(engine.WatchedPaths);

        // 目录之后出现了：下一次刷新重建监听。
        watchers.Missing.Clear();
        engine.StartWatcher(["/tmp/kanjo-missing", "/tmp/kanjo-other"]);
        Assert.True(engine.IsWatching);
        Assert.Equal(["/tmp/kanjo-missing", "/tmp/kanjo-other"], engine.WatchedPaths);
    }

    [Fact]
    public void TestRestartingWatcherDisposesOldOne()
    {
        var (engine, _, watchers, _, _, _) = NewEngine();
        using var _engine = engine;

        engine.StartWatcher(["/tmp/a"]);
        var first = watchers.Current!;
        engine.StartWatcher(["/tmp/b"]);
        Assert.False(first.IsActive);
        Assert.Equal(["/tmp/b"], engine.WatchedPaths);
    }

    [Fact]
    public void TestStopWatcherClears()
    {
        var (engine, _, _, _, _, _) = NewEngine();
        using var _engine = engine;

        engine.StartWatcher(["/tmp/a"]);
        Assert.True(engine.IsWatching);
        engine.StopWatcher();
        Assert.False(engine.IsWatching);
    }

    [Fact]
    public void TestDisposeStopsEverything()
    {
        var (engine, timers, watchers, power, _, refreshes) = NewEngine();
        engine.StartWatcher(["/tmp/a"]);
        engine.RestartFallbackTimer(30);
        var watcher = watchers.Current!;
        var periodic = timers.Periodic!;

        engine.Dispose();

        Assert.False(watcher.IsActive);
        Assert.True(periodic.WasCancelled);
        Assert.Null(timers.LastPending);

        // 释放后收到的唤醒 / 事件不再触发刷新。
        power.RaiseResume();
        engine.OnPanelOpened();
        Assert.Empty(refreshes);
    }
}
