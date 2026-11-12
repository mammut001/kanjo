using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>磁盘报告预取（Mac 的 DiskStore.schedulePrefetch）：第一次等 15 秒，之后立即；用量刷新开始会取消。</summary>
public sealed class DiskPrefetchTests : KanjoTestCase
{
    [Fact]
    public void TestFirstPrefetchWaitsFifteenSeconds()
    {
        var timers = new FakeBackgroundScheduler();
        var runs = 0;
        using var prefetcher = new DiskPrefetcher(timers, () => runs++);

        prefetcher.Schedule();
        Assert.True(prefetcher.DidSchedule);
        Assert.True(prefetcher.HasPending);
        Assert.Equal(TimeSpan.FromSeconds(15), timers.LastPending!.Delay);
        Assert.Equal(0, runs);

        timers.LastPending!.Fire();
        Assert.Equal(1, runs);
        Assert.False(prefetcher.HasPending);
    }

    [Fact]
    public void TestLaterPrefetchRunsImmediately()
    {
        var timers = new FakeBackgroundScheduler();
        var runs = 0;
        using var prefetcher = new DiskPrefetcher(timers, () => runs++);

        prefetcher.Schedule();
        timers.LastPending!.Fire();
        Assert.Equal(1, runs);

        // 第二次之后不再等待：直接跑（和 Mac 的 didScheduleDiskPrefetch 一样）。
        prefetcher.Schedule();
        Assert.Equal(2, runs);
        Assert.False(prefetcher.HasPending);
    }

    [Fact]
    public void TestCancelDropsPendingPrefetch()
    {
        var timers = new FakeBackgroundScheduler();
        var runs = 0;
        using var prefetcher = new DiskPrefetcher(timers, () => runs++);

        prefetcher.Schedule();
        var pending = timers.LastPending!;
        prefetcher.Cancel();

        Assert.True(pending.WasCancelled);
        Assert.False(prefetcher.HasPending);
        pending.Fire();
        Assert.Equal(0, runs);

        // 取消过一次之后仍然是「已经是第二次」，立即跑（Mac 用同一个标志）。
        prefetcher.Schedule();
        Assert.Equal(1, runs);
    }

    [Fact]
    public void TestDisposeCancels()
    {
        var timers = new FakeBackgroundScheduler();
        var runs = 0;
        var prefetcher = new DiskPrefetcher(timers, () => runs++);
        prefetcher.Schedule();
        var pending = timers.LastPending!;

        prefetcher.Dispose();
        pending.Fire();
        Assert.Equal(0, runs);
    }
}
