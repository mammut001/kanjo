namespace Kanjo.Core;

/// <summary>
/// 磁盘报告的预取调度（Mac 的 <c>DiskStore.schedulePrefetch(delay:)</c>）：
/// 启动后第一次预取等 <see cref="FirstDelay"/>（15 秒，让用量导出先跑完），
/// 之后的每次刷新完成都立刻预取（0 秒）。新的用量刷新会取消还没触发的预取，
/// 避免两个 <c>kanjo disk</c> 进程和用量导出抢 CPU。真正的扫描排队由 <see cref="DiskStore"/> 负责。
/// </summary>
public sealed class DiskPrefetcher : IDisposable
{
    /// <summary>启动后第一次预取的延迟（Mac: 15 秒）。</summary>
    public static readonly TimeSpan FirstDelay = TimeSpan.FromSeconds(15);

    private readonly IBackgroundScheduler _timers;
    private readonly Action _refresh;
    private readonly object _lock = new();
    private IBackgroundTimer? _pending;
    private bool _didSchedule;
    private bool _disposed;

    public DiskPrefetcher(IBackgroundScheduler? timers = null, Action? refresh = null)
    {
        _timers = timers ?? ThreadPoolBackgroundScheduler.Shared;
        _refresh = refresh ?? (() => { });
    }

    public Action RefreshAction => _refresh;

    /// <summary>是否已经安排过预取（第一次是 15 秒，之后是立即）。</summary>
    public bool DidSchedule
    {
        get { lock (_lock) return _didSchedule; }
    }

    public bool HasPending
    {
        get { lock (_lock) return _pending is { IsActive: true }; }
    }

    /// <summary>用量刷新完成后调用：取消旧的等待，按「第一次 15 秒、之后立即」安排一次预取。</summary>
    public void Schedule()
    {
        TimeSpan delay;
        lock (_lock)
        {
            if (_disposed) return;
            CancelLocked();
            delay = _didSchedule ? TimeSpan.Zero : FirstDelay;
            _didSchedule = true;
            if (delay > TimeSpan.Zero)
            {
                _pending = _timers.ScheduleOnce(delay, Fire);
                return;
            }
        }
        Fire();
    }

    /// <summary>用量刷新开始前调用（Mac 的 <c>cancelPrefetch</c>）：还没触发的预取作废。</summary>
    public void Cancel()
    {
        lock (_lock) CancelLocked();
    }

    private void Fire()
    {
        lock (_lock)
        {
            _pending = null;
            if (_disposed) return;
        }
        _refresh();
    }

    private void CancelLocked()
    {
        _pending?.Dispose();
        _pending = null;
    }

    public void Dispose()
    {
        lock (_lock)
        {
            if (_disposed) return;
            _disposed = true;
            CancelLocked();
        }
    }
}
