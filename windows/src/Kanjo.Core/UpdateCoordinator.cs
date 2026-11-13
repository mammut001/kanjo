namespace Kanjo.Core;

/// <summary>
/// 更新状态机：把 <see cref="IUpdateManager"/> 的「检查 / 下载 / 重启装上」串起来，
/// 维护界面要读的 <see cref="Status"/>，并把通知切到 UI 线程。
///
/// 这里的每一条都对应界面上的东西：
/// <list type="bullet">
/// <item>Idle → Checking → UpToDate：设置页按钮的「Checking… / You're up to date」；</item>
/// <item>Checking → Downloading(progress)：横幅的「Downloading Kanjo 0.5.3… 42%」和进度条；</item>
/// <item>Downloading → Ready(version)：横幅的「Kanjo 0.5.3 is ready」+ 按钮，按钮走
///       <see cref="RestartToUpdate"/>（和托盘菜单同一条路径）；</item>
/// <item>任何一步异常 → Failed(短消息)：设置页显示可重试的错误，下次定时检查还会再来。</item>
/// </list>
///
/// 同一时间只有一次检查 / 下载：定时器、托盘、设置页按钮都调 <see cref="CheckNowAsync"/>，
/// 正在跑时直接拿到同一个 Task（不叠加、不互相打断）。
/// 已有的定时后台检查（启动 30 秒 + 每 6 小时）和「下次启动自动装上」都在
/// <see cref="Start"/> / Velopack 的 SetAutoApplyOnStartup 上，行为不变。
/// </summary>
public sealed class UpdateCoordinator : IDisposable
{
    private readonly IUpdateManager? _manager;
    private readonly IBackgroundScheduler _timers;
    private readonly Action<Action> _dispatch;
    private readonly object _lock = new();

    private IBackgroundTimer? _firstCheck;
    private IBackgroundTimer? _periodic;
    private Task? _running;
    private UpdateStatus _status;
    private string? _dismissedVersion;
    private bool _disposed;

    /// <summary>状态变了（可能由后台线程触发；通知已经过 <c>dispatch</c>，到 UI 线程了）。</summary>
    public event Action? Changed;

    /// <param name="manager">Velopack 的窄接口；null = 不是安装版（开发运行 / 便携版）。</param>
    /// <param name="currentVersion">本进程的版本号（非安装版也显示）。</param>
    /// <param name="timers">定时器工厂（测试注入假实现）。</param>
    /// <param name="dispatch">把回调切到 UI 线程；默认直接执行（单元测试）。</param>
    public UpdateCoordinator(IUpdateManager? manager, string currentVersion, IBackgroundScheduler? timers = null,
        Action<Action>? dispatch = null)
    {
        _manager = manager;
        _timers = timers ?? ThreadPoolBackgroundScheduler.Shared;
        _dispatch = dispatch ?? (action => action());
        CurrentVersion = currentVersion;
        _status = manager is null
            ? UpdateStatus.NotInstalled(currentVersion)
            // 上次已经下载好、但还没装上（正常路径下 Velopack 会在启动时自己装上，
            // 这里是「用户没重启、进程又起来了」的兜底）：直接进 Ready，界面立刻能重启更新。
            : manager.PendingRestartVersion is { Length: > 0 } pending
                ? new UpdateStatus(UpdateState.Ready, pending) { CurrentVersion = currentVersion }
                : new UpdateStatus(UpdateState.Idle) { CurrentVersion = currentVersion };
    }

    /// <summary>本进程的版本号（设置页「Current version」）。</summary>
    public string CurrentVersion { get; }

    /// <summary>
    /// 截图专用：把一个假状态直接塞进来（不联网、不跑定时器）。
    /// 只有 <c>--snapshot</c> 模式会走这条路 —— 正常运行时状态一律来自 Velopack。
    /// </summary>
    public void SeedForSnapshot(UpdateStatus status)
    {
        lock (_lock)
        {
            if (_disposed) return;
            _status = status.CurrentVersion.Length == 0
                ? status with { CurrentVersion = CurrentVersion }
                : status;
        }
    }

    /// <summary>当前状态快照。</summary>
    public UpdateStatus Status
    {
        get { lock (_lock) return _status; }
    }

    /// <summary>已下载、可以立刻重启装上的版本；没有则为 null。</summary>
    public bool HasReadyUpdate => Status.State == UpdateState.Ready;

    /// <summary>用户关掉了哪个版本的横幅（下次启动不继承，见 <see cref="UpdateBanner"/>）。</summary>
    public string? DismissedVersion
    {
        get { lock (_lock) return _dismissedVersion; }
    }

    /// <summary>关闭横幅：只对当前这个版本有效。</summary>
    public void DismissBanner()
    {
        var version = Status.Version;
        if (version is not { Length: > 0 }) return;
        lock (_lock) _dismissedVersion = version;
        Notify();
    }

    /// <summary>启动后 30 秒第一次检查，之后每 6 小时一次（非安装版什么都不做）。</summary>
    public void Start()
    {
        lock (_lock)
        {
            if (_disposed || _manager is null || _firstCheck is not null) return;
            _firstCheck = _timers.ScheduleOnce(UpdatePolicy.InitialDelay, () =>
            {
                _ = CheckNowAsync();
                lock (_lock)
                {
                    if (_disposed) return;
                    _periodic = _timers.SchedulePeriodic(UpdatePolicy.Interval, () => _ = CheckNowAsync());
                }
            });
        }
    }

    /// <summary>
    /// 检查 → 有新版本就在后台下载。正在检查 / 下载时返回同一个 Task（不重复跑）。
    /// </summary>
    public Task CheckNowAsync()
    {
        IUpdateManager? manager;
        lock (_lock)
        {
            if (_disposed || _manager is null) return Task.CompletedTask;
            if (_running is { IsCompleted: false }) return _running;
            manager = _manager;
            // 放到线程池：RunAsync 的第一件事就是改状态 + 发通知，不能在锁里跑用户回调。
            _running = Task.Run(() => RunAsync(manager));
            return _running;
        }
    }

    private async Task RunAsync(IUpdateManager manager)
    {
        SetStatus(new UpdateStatus(UpdateState.Checking) { CurrentVersion = CurrentVersion });

        string? version;
        try
        {
            version = await manager.CheckForUpdateAsync().ConfigureAwait(false);
        }
        catch (Exception e)
        {
            Fail(e);
            return;
        }
        if (IsDisposed) return;

        if (version is not { Length: > 0 })
        {
            SetStatus(new UpdateStatus(UpdateState.UpToDate, null, 0, null, DateTimeOffset.UtcNow)
            {
                CurrentVersion = CurrentVersion,
            });
            return;
        }

        SetStatus(new UpdateStatus(UpdateState.Downloading, version, 0, null, DateTimeOffset.UtcNow)
        {
            CurrentVersion = CurrentVersion,
        });
        var lastReported = 0;
        try
        {
            // Velopack 的进度回调是 0–100，可能从任何线程来；SetStatus 会切到 UI 线程。
            // 只在跨过 5% 的档位时才通知：界面上每来一个百分点就重建一次页面太费了。
            await manager.DownloadAsync(percent =>
            {
                if (IsDisposed) return;
                if (percent is > 0 and < 100 && percent - lastReported < 5) return;
                lastReported = percent;
                SetStatus(new UpdateStatus(UpdateState.Downloading, version, percent, null,
                    DateTimeOffset.UtcNow) { CurrentVersion = CurrentVersion });
            }, CancellationToken.None).ConfigureAwait(false);
        }
        catch (Exception e)
        {
            Fail(e);
            return;
        }
        if (IsDisposed) return;

        SetStatus(new UpdateStatus(UpdateState.Ready, version, 100, null, DateTimeOffset.UtcNow)
        {
            CurrentVersion = CurrentVersion,
        });
    }

    /// <summary>失败只记一句短消息（界面上是「retry」），下次定时检查会再试。</summary>
    private void Fail(Exception e)
    {
        System.Diagnostics.Trace.WriteLine($"kanjo: update failed: {e.Message}");
        SetStatus(new UpdateStatus(UpdateState.Failed, null, 0, UpdateStatusText.Shorten(e.Message),
            DateTimeOffset.UtcNow) { CurrentVersion = CurrentVersion });
    }

    /// <summary>
    /// 装上已下载的版本并重启（进程在这里退出）。界面上的横幅按钮、设置页按钮、托盘菜单都走这里。
    /// </summary>
    public void RestartToUpdate()
    {
        IUpdateManager? manager;
        lock (_lock)
        {
            if (_disposed) return;
            manager = _manager;
        }
        if (manager is null) return;

        // 更新器要换掉正在运行的 exe：不要占着 UI 线程（和托盘菜单原来的做法一致）。
        Task.Run(() =>
        {
            try
            {
                manager.RestartToApply();
            }
            catch (Exception e)
            {
                // 更新器起不来就算了：下次启动 Velopack 照样会应用已下载的更新。
                Fail(e);
            }
        });
    }

    private bool IsDisposed
    {
        get { lock (_lock) return _disposed; }
    }

    private void SetStatus(UpdateStatus status)
    {
        lock (_lock)
        {
            if (_disposed) return;
            _status = status;
        }
        Notify();
    }

    /// <summary>通知切到 UI 线程：面板 / 设置页收到后重建（和 <c>AppServices.Changed</c> 的规则一致）。</summary>
    private void Notify()
    {
        void Raise()
        {
            if (IsDisposed) return;
            Changed?.Invoke();
        }
        try
        {
            _dispatch(Raise);
        }
        catch (Exception)
        {
            // 没有 UI 线程（单元测试 / 无显示器）：直接执行。
            Raise();
        }
    }

    public void Dispose()
    {
        lock (_lock)
        {
            if (_disposed) return;
            _disposed = true;
            _firstCheck?.Dispose();
            _firstCheck = null;
            _periodic?.Dispose();
            _periodic = null;
        }
    }
}
