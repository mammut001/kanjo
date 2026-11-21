using Xunit;

namespace Kanjo.Core.Tests;

public sealed class RefreshSchedulerTests : KanjoTestCase
{
    private static DateTimeOffset At(double seconds) => DateTimeOffset.FromUnixTimeSeconds((long)seconds);

    [Fact]
    public void TestFallbackMigration()
    {
        Assert.Equal(30, RefreshScheduler.MigrateFallbackMinutes(5));
        Assert.Equal(30, RefreshScheduler.MigrateFallbackMinutes(10));
        Assert.Equal(30, RefreshScheduler.MigrateFallbackMinutes(14));
        Assert.Equal(15, RefreshScheduler.MigrateFallbackMinutes(15));
        Assert.Equal(30, RefreshScheduler.MigrateFallbackMinutes(30));
        Assert.Equal(60, RefreshScheduler.MigrateFallbackMinutes(60));
        Assert.Equal(0, RefreshScheduler.MigrateFallbackMinutes(0));
    }

    [Fact]
    public void TestDebounce60SecondsAfterEvent()
    {
        var t0 = At(1000);
        var scheduler = new RefreshScheduler(lastRefreshTime: At(0));
        var action = scheduler.OnFileEvent(t0);
        Assert.Equal(RefreshActionKind.ScheduleRefresh, action.Kind);
        Assert.Equal(TimeSpan.FromSeconds(60), action.Delay);
    }

    [Fact]
    public void TestMinimumInterval120SecondsBetweenRefreshes()
    {
        var scheduler = new RefreshScheduler(lastRefreshTime: At(1000));
        // 事件发生在上次刷新后 30s。防抖是 +60（1090），但最小间隔是 +120（1120）→ 延迟 90s。
        var action = scheduler.OnFileEvent(At(1030));
        Assert.Equal(90, (int)action.Delay.TotalSeconds);
    }

    [Fact]
    public void TestCoalesceEventsDuringRunningRefresh()
    {
        var scheduler = new RefreshScheduler(lastRefreshTime: At(800));
        scheduler.OnRefreshStarted(At(1000));

        Assert.Equal(RefreshActionKind.None, scheduler.OnFileEvent(At(1005)).Kind);
        Assert.True(scheduler.HasPendingEventWhileRefreshing);
        Assert.Equal(RefreshActionKind.None, scheduler.OnFileEvent(At(1010)).Kind);

        // 合并后的后续刷新要同时满足：从 t2 防抖（1070）与从 t3 的最小间隔（1135）→ 1135，延迟 120s。
        var finishAction = scheduler.OnRefreshFinished(At(1015));
        Assert.Equal(120, (int)finishAction.Delay.TotalSeconds);
        Assert.False(scheduler.HasPendingEventWhileRefreshing);
    }

    [Fact]
    public void TestShouldRefreshOnOpen()
    {
        var t0 = At(1000);

        Assert.True(new RefreshScheduler(lastRefreshTime: null).ShouldRefreshOnOpen(t0));
        Assert.False(new RefreshScheduler(lastRefreshTime: At(950)).ShouldRefreshOnOpen(t0));
        Assert.True(new RefreshScheduler(lastRefreshTime: At(870)).ShouldRefreshOnOpen(t0));

        var refreshing = new RefreshScheduler(lastRefreshTime: At(500));
        refreshing.OnRefreshStarted(t0);
        Assert.False(refreshing.ShouldRefreshOnOpen(t0));
    }

    [Fact]
    public void TestSleepAndWakeHandling()
    {
        var scheduler = new RefreshScheduler(lastRefreshTime: At(500));
        scheduler.OnSleep();
        Assert.True(scheduler.IsAsleep);

        Assert.Equal(RefreshActionKind.None, scheduler.OnFileEvent(At(600)).Kind);
        Assert.True(scheduler.PendingWakeRefresh);

        var wakeAction = scheduler.OnWake(At(1000));
        Assert.Equal(RefreshActionKind.RefreshNow, wakeAction.Kind);
        Assert.False(scheduler.IsAsleep);
        Assert.False(scheduler.PendingWakeRefresh);
    }

    [Fact]
    public void TestLowPowerModeHandling()
    {
        var scheduler = new RefreshScheduler(lastRefreshTime: At(500));
        scheduler.OnLowPowerModeChanged(true, At(600));
        Assert.True(scheduler.IsLowPowerMode);

        Assert.Equal(RefreshActionKind.None, scheduler.OnFallbackTimerFired(At(3000)).Kind);
        Assert.True(scheduler.PendingWakeRefresh);

        Assert.Equal(RefreshActionKind.RefreshNow,
            scheduler.OnLowPowerModeChanged(false, At(3100)).Kind);
    }

    /// <summary>节电模式下睡眠再唤醒：仍在节电，不能立刻跑一次完整导出（Mac：onWake 在低电量时返回 none）。</summary>
    [Fact]
    public void TestWakeDuringLowPowerModeDefers()
    {
        var scheduler = new RefreshScheduler(lastRefreshTime: At(0));
        scheduler.OnLowPowerModeChanged(true, At(100));
        scheduler.OnFileEvent(At(200));
        scheduler.OnSleep();

        Assert.Equal(RefreshActionKind.None, scheduler.OnWake(At(800)).Kind);
        Assert.True(scheduler.PendingWakeRefresh);
        Assert.Equal(RefreshActionKind.RefreshNow, scheduler.OnLowPowerModeChanged(false, At(900)).Kind);
    }

    /// <summary>已安排的防抖刷新遇到睡眠：唤醒后要补上，而不是丢掉。</summary>
    [Fact]
    public void TestSleepKeepsScheduledRefreshForWake()
    {
        var scheduler = new RefreshScheduler(lastRefreshTime: At(0));
        Assert.Equal(RefreshActionKind.ScheduleRefresh, scheduler.OnFileEvent(At(1000)).Kind);
        scheduler.OnSleep();

        Assert.Equal(RefreshActionKind.RefreshNow, scheduler.OnWake(At(2800)).Kind);
    }

    /// <summary>开启节电时已安排的刷新：转成「恢复后再刷」，关掉节电时补上。</summary>
    [Fact]
    public void TestLowPowerKeepsScheduledRefreshForResume()
    {
        var scheduler = new RefreshScheduler(lastRefreshTime: At(0));
        Assert.Equal(RefreshActionKind.ScheduleRefresh, scheduler.OnFileEvent(At(1000)).Kind);
        Assert.Equal(RefreshActionKind.None, scheduler.OnLowPowerModeChanged(true, At(1010)).Kind);
        Assert.True(scheduler.PendingWakeRefresh);

        Assert.Equal(RefreshActionKind.RefreshNow, scheduler.OnLowPowerModeChanged(false, At(2000)).Kind);
    }

    /// <summary>睡眠 / 节电中结束的刷新带着补刷：记成唤醒后刷新，而不是丢掉。</summary>
    [Fact]
    public void TestFollowUpFinishedWhileAsleepIsKeptForWake()
    {
        var scheduler = new RefreshScheduler(lastRefreshTime: At(0));
        scheduler.OnRefreshStarted(At(1000));
        scheduler.OnFileEvent(At(1005));
        scheduler.OnSleep();
        Assert.Equal(RefreshActionKind.None, scheduler.OnRefreshFinished(At(1010)).Kind);
        Assert.True(scheduler.PendingWakeRefresh);

        Assert.Equal(RefreshActionKind.RefreshNow, scheduler.OnWake(At(2000)).Kind);
    }

    /// <summary>唤醒时还有刷新在跑：补刷留给 OnRefreshFinished，不直接丢掉。</summary>
    [Fact]
    public void TestWakeWhileRefreshingKeepsFollowUp()
    {
        var scheduler = new RefreshScheduler(lastRefreshTime: At(0));
        scheduler.OnSleep();
        scheduler.OnFileEvent(At(500));
        scheduler.OnRefreshStarted(At(900));

        Assert.Equal(RefreshActionKind.None, scheduler.OnWake(At(1000)).Kind);
        Assert.True(scheduler.HasPendingEventWhileRefreshing);
        Assert.Equal(RefreshActionKind.ScheduleRefresh, scheduler.OnRefreshFinished(At(1010)).Kind);
    }

    [Fact]
    public void TestFallbackTimerFiresWhenDue()
    {
        var scheduler = new RefreshScheduler(30, At(0));
        Assert.Equal(RefreshActionKind.None, scheduler.OnFallbackTimerFired(At(20 * 60)).Kind);
        Assert.Equal(RefreshActionKind.RefreshNow, scheduler.OnFallbackTimerFired(At(30 * 60)).Kind);
    }

    [Fact]
    public void TestDebounceStarvationMaxWait()
    {
        var scheduler = new RefreshScheduler(lastRefreshTime: null);
        var t0 = At(1000);
        var refreshStartTimes = new List<DateTimeOffset>();
        DateTimeOffset? scheduledRefreshTime = null;

        // 连续 10 分钟每 5s 一个事件（120 个间隔）
        for (var step = 0; step <= 120; step++)
        {
            var currentTime = t0.AddSeconds(step * 5);

            if (scheduledRefreshTime is { } scheduled && currentTime >= scheduled)
            {
                refreshStartTimes.Add(scheduled);
                scheduler.OnRefreshStarted(scheduled);
                scheduledRefreshTime = null;

                var finishTime = scheduled.AddSeconds(1);
                var finishAction = scheduler.OnRefreshFinished(finishTime);
                if (finishAction.Kind == RefreshActionKind.ScheduleRefresh)
                {
                    scheduledRefreshTime = finishTime + finishAction.Delay;
                }
            }

            var action = scheduler.OnFileEvent(currentTime);
            if (action.Kind == RefreshActionKind.ScheduleRefresh)
            {
                scheduledRefreshTime = currentTime + action.Delay;
            }
        }

        // 首次事件后 180s 内至少刷新一次
        Assert.NotEmpty(refreshStartTimes);
        Assert.True(refreshStartTimes[0] - t0 <= TimeSpan.FromSeconds(180));

        // 最多约每 3 分钟刷新一次（>= 120s 最小间隔，<= 190s 因 5s 步长）
        Assert.True(refreshStartTimes.Count >= 3);
        for (var i = 1; i < refreshStartTimes.Count; i++)
        {
            var interval = refreshStartTimes[i] - refreshStartTimes[i - 1];
            Assert.True(interval >= TimeSpan.FromSeconds(120));
            Assert.True(interval <= TimeSpan.FromSeconds(190));
        }
    }
}
