namespace Kanjo.Core;

/// <summary>刷新触发方式（对应 Mac 的 qualityOfService：userInitiated / background）。</summary>
public enum RefreshTrigger
{
    UserInitiated,
    Background,
}

/// <summary>一次性的 / 周期性的后台计时器。测试注入假实现，运行时不碰真实时钟。</summary>
public interface IBackgroundTimer : IDisposable
{
    bool IsActive { get; }
}

/// <summary>后台计时器工厂：只提供「延时执行一次」和「每 N 秒执行一次」两件事。</summary>
public interface IBackgroundScheduler
{
    IBackgroundTimer ScheduleOnce(TimeSpan delay, Action callback);

    IBackgroundTimer SchedulePeriodic(TimeSpan interval, Action callback);
}

/// <summary>真实实现：<see cref="Timer"/>（线程池，不占 UI 线程）。</summary>
public sealed class ThreadPoolBackgroundScheduler : IBackgroundScheduler
{
    public static ThreadPoolBackgroundScheduler Shared { get; } = new();

    private sealed class TimerHandle : IBackgroundTimer
    {
        private readonly Timer _timer;
        private readonly object _lock = new();
        private bool _active = true;

        public TimerHandle(Timer timer) => _timer = timer;

        public bool IsActive
        {
            get { lock (_lock) return _active; }
        }

        internal void Complete(bool dispose)
        {
            lock (_lock) _active = false;
            if (dispose) _timer.Dispose();
        }

        public void Dispose() => Complete(dispose: true);
    }

    public IBackgroundTimer ScheduleOnce(TimeSpan delay, Action callback)
    {
        if (delay < TimeSpan.Zero) delay = TimeSpan.Zero;
        TimerHandle? handle = null;
        var timer = new Timer(_ =>
        {
            if (handle is null) return;
            handle.Complete(dispose: true);
            callback();
        }, null, Timeout.Infinite, Timeout.Infinite);
        handle = new TimerHandle(timer);
        timer.Change(delay, Timeout.InfiniteTimeSpan);
        return handle;
    }

    public IBackgroundTimer SchedulePeriodic(TimeSpan interval, Action callback)
    {
        if (interval <= TimeSpan.Zero) interval = TimeSpan.FromSeconds(1);
        var timer = new Timer(_ => callback(), null, interval, interval);
        return new TimerHandle(timer);
    }
}

/// <summary>
/// 后台刷新的编排（Mac <c>ReportStore</c> 里 scheduler / timer / watcher / 电源事件那部分）：
/// <list type="bullet">
/// <item>文件变化 → <see cref="RefreshScheduler.OnFileEvent"/> → 防抖后要求后台刷新；</item>
/// <item>兜底定时器（设置里的「Fallback refresh interval」）→ <see cref="RefreshScheduler.OnFallbackTimerFired"/>；</item>
/// <item>睡眠 / 唤醒 / 节电模式 → 暂停与补刷；</item>
/// <item>面板打开 → 超过 120 秒没刷新就刷一次。</item>
/// </list>
/// 计时器、监听器、电源事件都从外面注入；真正的数据加载由 <see cref="RefreshRequested"/> 的订阅者完成。
/// </summary>
public sealed class RefreshEngine : IDisposable
{
    private readonly object _lock = new();
    private readonly IBackgroundScheduler _timers;
    private readonly Func<DateTimeOffset> _clock;
    private readonly RefreshScheduler _scheduler;

    private ILogWatcherFactory? _watcherFactory;
    private IPowerMonitor? _power;
    private ILogWatcher? _watcher;
    private IBackgroundTimer? _scheduled;
    private IBackgroundTimer? _fallback;
    private bool _disposed;

    public RefreshEngine(IBackgroundScheduler? timers = null, Func<DateTimeOffset>? clock = null,
        int fallbackMinutes = RefreshScheduler.DefaultFallbackMinutes)
    {
        _timers = timers ?? ThreadPoolBackgroundScheduler.Shared;
        _clock = clock ?? (() => DateTimeOffset.UtcNow);
        _scheduler = new RefreshScheduler(fallbackMinutes);
    }

    /// <summary>需要开始一次刷新（<see cref="RefreshTrigger.UserInitiated"/> 来自托盘 / 面板按钮）。</summary>
    public event Action<RefreshTrigger>? RefreshRequested;

    public int FallbackMinutes
    {
        get { lock (_lock) return _scheduler.FallbackMinutes; }
    }

    public bool IsRefreshing
    {
        get { lock (_lock) return _scheduler.IsRefreshing; }
    }

    public bool IsAsleep
    {
        get { lock (_lock) return _scheduler.IsAsleep; }
    }

    public bool IsLowPowerMode
    {
        get { lock (_lock) return _scheduler.IsLowPowerMode; }
    }

    public bool PendingWakeRefresh
    {
        get { lock (_lock) return _scheduler.PendingWakeRefresh; }
    }

    public bool HasScheduledRefresh
    {
        get { lock (_lock) return _scheduled is { IsActive: true }; }
    }

    public bool HasFallbackTimer
    {
        get { lock (_lock) return _fallback is { IsActive: true }; }
    }

    public bool IsWatching
    {
        get { lock (_lock) return _watcher is { IsActive: true }; }
    }

    public IReadOnlyList<string> WatchedPaths
    {
        get { lock (_lock) return _watcher?.Paths ?? []; }
    }

    /// <summary>接上文件监听器与电源事件源（启动时调用一次）。</summary>
    public void Attach(ILogWatcherFactory watchers, IPowerMonitor? power)
    {
        lock (_lock)
        {
            if (_disposed) return;
            _watcherFactory = watchers;
            _power = power;
        }
        if (power is null) return;
        power.WillSuspend += HandleWillSuspend;
        power.DidResume += HandleDidResume;
        power.LowPowerModeChanged += HandleLowPowerModeChanged;
        power.Start();
    }

    /// <summary>
    /// 开始监听这些目录（Mac 的 <c>startLogWatcher</c>）。目录不存在时工厂会跳过；
    /// 一个都不剩就没有监听器，下次刷新时会再试（<see cref="IsWatching"/> 为 false）。
    /// </summary>
    public void StartWatcher(IReadOnlyList<string> paths)
    {
        ILogWatcher? old;
        ILogWatcher? created = null;
        lock (_lock)
        {
            if (_disposed) return;
            old = _watcher;
            _watcher = null;
            if (_watcherFactory is { } factory && paths.Count > 0)
            {
                created = factory.Start(paths, OnFileEvent);
            }
            _watcher = created;
        }
        old?.Dispose();
    }

    public void StopWatcher()
    {
        ILogWatcher? old;
        lock (_lock)
        {
            old = _watcher;
            _watcher = null;
        }
        old?.Dispose();
    }

    /// <summary>设置页改了「Fallback refresh interval」：销毁旧定时器，按新间隔重建（0 = 关）。</summary>
    public void RestartFallbackTimer(int minutes)
    {
        var migrated = RefreshScheduler.MigrateFallbackMinutes(minutes);
        lock (_lock)
        {
            _fallback?.Dispose();
            _fallback = null;
            _scheduler.FallbackMinutes = migrated;
            if (_disposed || migrated <= 0) return;
            _fallback = _timers.SchedulePeriodic(TimeSpan.FromMinutes(migrated), OnFallbackTick);
        }
    }

    /// <summary>文件监听器报来一个变化事件。</summary>
    public void OnFileEvent()
    {
        RefreshAction action;
        lock (_lock)
        {
            if (_disposed) return;
            action = _scheduler.OnFileEvent(_clock());
        }
        Handle(action);
    }

    /// <summary>一次刷新开始（<see cref="RefreshScheduler.OnRefreshStarted"/>：取消待触发的防抖任务）。</summary>
    public void BeginRefresh()
    {
        lock (_lock)
        {
            if (_disposed) return;
            CancelScheduledLocked();
            _scheduler.OnRefreshStarted(_clock());
        }
    }

    /// <summary>一次刷新结束（包括失败）：更新上次刷新时间，并按需要安排合并后的补刷。</summary>
    public void EndRefresh()
    {
        RefreshAction action;
        lock (_lock)
        {
            if (_disposed) return;
            action = _scheduler.OnRefreshFinished(_clock());
        }
        Handle(action);
    }

    /// <summary>面板打开：上次刷新超过 120 秒（或从没刷过）就刷一次。</summary>
    public void OnPanelOpened()
    {
        bool should;
        lock (_lock)
        {
            if (_disposed) return;
            should = _scheduler.ShouldRefreshOnOpen(_clock());
            if (should) CancelScheduledLocked();
        }
        if (should) RefreshRequested?.Invoke(RefreshTrigger.Background);
    }

    /// <summary>用户主动刷新（托盘右键 / 面板刷新按钮）：取消待触发的防抖任务，立刻刷。</summary>
    public void RequestRefresh()
    {
        lock (_lock)
        {
            if (_disposed) return;
            CancelScheduledLocked();
        }
        RefreshRequested?.Invoke(RefreshTrigger.UserInitiated);
    }

    /// <summary>系统将要睡眠（Mac <c>onWillSleep</c>）：取消待触发的刷新，标记为睡眠。</summary>
    public void Suspend()
    {
        lock (_lock)
        {
            if (_disposed) return;
            CancelScheduledLocked();
            _scheduler.OnSleep();
        }
    }

    /// <summary>系统唤醒（Mac <c>onDidWake</c>）。</summary>
    public void Resume()
    {
        RefreshAction action;
        lock (_lock)
        {
            if (_disposed) return;
            action = _scheduler.OnWake(_clock());
        }
        Handle(action);
    }

    /// <summary>节电模式开关（Mac <c>onPowerStateDidChange</c>）。</summary>
    public void SetLowPowerMode(bool enabled)
    {
        RefreshAction action;
        lock (_lock)
        {
            if (_disposed) return;
            action = _scheduler.OnLowPowerModeChanged(enabled, _clock());
        }
        Handle(action);
    }

    private void HandleWillSuspend(object? sender, EventArgs e) => Suspend();

    private void HandleDidResume(object? sender, EventArgs e) => Resume();

    private void HandleLowPowerModeChanged(object? sender, LowPowerModeEventArgs e) =>
        SetLowPowerMode(e.Enabled);

    private void OnFallbackTick()
    {
        RefreshAction action;
        lock (_lock)
        {
            if (_disposed) return;
            action = _scheduler.OnFallbackTimerFired(_clock());
        }
        Handle(action);
    }

    private void OnScheduledTimer()
    {
        lock (_lock)
        {
            _scheduled = null;
            if (_disposed) return;
        }
        RefreshRequested?.Invoke(RefreshTrigger.Background);
    }

    private void Handle(RefreshAction action)
    {
        switch (action.Kind)
        {
            case RefreshActionKind.RefreshNow:
                lock (_lock)
                {
                    if (_disposed) return;
                    CancelScheduledLocked();
                }
                RefreshRequested?.Invoke(RefreshTrigger.Background);
                return;
            case RefreshActionKind.ScheduleRefresh:
                ScheduleBackground(action.Delay);
                return;
            default:
                return;
        }
    }

    private void ScheduleBackground(TimeSpan delay)
    {
        if (delay <= TimeSpan.Zero)
        {
            lock (_lock)
            {
                if (_disposed) return;
                CancelScheduledLocked();
            }
            RefreshRequested?.Invoke(RefreshTrigger.Background);
            return;
        }
        lock (_lock)
        {
            if (_disposed) return;
            CancelScheduledLocked();
            _scheduled = _timers.ScheduleOnce(delay, OnScheduledTimer);
        }
    }

    private void CancelScheduledLocked()
    {
        _scheduled?.Dispose();
        _scheduled = null;
    }

    public void Dispose()
    {
        ILogWatcher? watcher;
        IPowerMonitor? power;
        lock (_lock)
        {
            if (_disposed) return;
            _disposed = true;
            CancelScheduledLocked();
            _fallback?.Dispose();
            _fallback = null;
            watcher = _watcher;
            _watcher = null;
            power = _power;
            _power = null;
        }
        watcher?.Dispose();
        if (power is null) return;
        power.WillSuspend -= HandleWillSuspend;
        power.DidResume -= HandleDidResume;
        power.LowPowerModeChanged -= HandleLowPowerModeChanged;
        power.Dispose();
    }
}
