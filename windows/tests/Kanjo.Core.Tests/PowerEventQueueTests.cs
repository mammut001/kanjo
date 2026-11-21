using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 电源事件离开 UI 线程：SystemEvents 通过 UI 线程的 SynchronizationContext 回调，
/// 唤醒后的刷新（同步跑 kanjo export）不能卡住托盘 / 面板。
/// </summary>
public sealed class PowerEventQueueTests : KanjoTestCase
{
    /// <summary>记录有没有被借用的同步上下文（模拟 Avalonia 的 UI 线程上下文）。</summary>
    private sealed class RecordingContext : SynchronizationContext
    {
        public int Uses;

        public override void Post(SendOrPostCallback d, object? state)
        {
            Interlocked.Increment(ref Uses);
            base.Post(d, state);
        }

        public override void Send(SendOrPostCallback d, object? state)
        {
            Interlocked.Increment(ref Uses);
            base.Send(d, state);
        }
    }

    [Fact]
    public void TestPostReturnsBeforeHandlerFinishes()
    {
        var queue = new PowerEventQueue();
        using var gate = new ManualResetEventSlim(false);
        using var finished = new CountdownEvent(2);
        var order = new List<int>();
        var callerThread = Environment.CurrentManagedThreadId;
        var handlerThreads = new List<int>();
        var context = new RecordingContext();
        var previous = SynchronizationContext.Current;
        SynchronizationContext.SetSynchronizationContext(context);
        try
        {
            queue.Post(() =>
            {
                gate.Wait(TimeSpan.FromSeconds(10));
                lock (order) { order.Add(1); handlerThreads.Add(Environment.CurrentManagedThreadId); }
                finished.Signal();
            });
            queue.Post(() =>
            {
                lock (order) { order.Add(2); handlerThreads.Add(Environment.CurrentManagedThreadId); }
                finished.Signal();
            });
        }
        finally
        {
            SynchronizationContext.SetSynchronizationContext(previous);
        }

        // 两个 Post 都已返回，第一个处理器还卡在 gate 上：调用方没被拖住。
        Assert.Empty(order);
        gate.Set();
        Assert.True(finished.Wait(TimeSpan.FromSeconds(10)));
        Assert.Equal([1, 2], order); // 睡眠 / 唤醒的顺序不能乱
        Assert.DoesNotContain(callerThread, handlerThreads);
        Assert.Equal(0, context.Uses);
    }

    [Fact]
    public void TestHandlerExceptionDoesNotBreakQueue()
    {
        var queue = new PowerEventQueue();
        using var done = new ManualResetEventSlim(false);
        queue.Post(() => throw new InvalidOperationException("boom"));
        queue.Post(done.Set);
        Assert.True(done.Wait(TimeSpan.FromSeconds(10)));
    }
}
