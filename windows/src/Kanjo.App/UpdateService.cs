using Kanjo.Core;
using Velopack;
using Velopack.Sources;

namespace Kanjo.App;

/// <summary>
/// 自动更新（Velopack + GitHub Releases）。策略判断在 <see cref="UpdatePolicy"/> 里（纯逻辑、有测试），
/// 这里只负责真正的网络 / 磁盘动作：
/// <list type="bullet">
/// <item>启动 30 秒后检查一次，之后每 6 小时一次；</item>
/// <item>有更新就在后台下载，下载完记下来（不打断用户）；</item>
/// <item>下次启动时由 Velopack 自己装上（<c>SetAutoApplyOnStartup</c>），
///       用户也可以从托盘菜单「Restart to update」立刻重启装上。</item>
/// </list>
/// Mac 版没有更新界面，所以这里也不弹窗、不提示，只在托盘菜单里多一项（有更新可装时才出现）。
/// </summary>
public sealed class UpdateService : IDisposable
{
    private readonly UpdateManager? _manager;
    private readonly IBackgroundScheduler _timers;
    private readonly object _lock = new();

    private IBackgroundTimer? _firstCheck;
    private IBackgroundTimer? _periodic;
    private bool _checking;
    private bool _disposed;

    /// <summary>状态变化（有更新 / 下载完成 / 出错）。可能在后台线程触发。</summary>
    public event Action? Changed;

    private UpdateService(UpdateManager? manager, IBackgroundScheduler timers)
    {
        _manager = manager;
        _timers = timers;
    }

    /// <summary>
    /// 按策略决定要不要更新；不该更新（开发运行、截图 / 预览模式、非 Velopack 安装）时返回 null。
    /// </summary>
    public static UpdateService? Create(IReadOnlyList<string> args, IBackgroundScheduler? timers = null)
    {
        var scheduler = timers ?? ThreadPoolBackgroundScheduler.Shared;
        if (!UpdatePolicy.ShouldRun(args, DefaultPaths.IsDebugBuild, IsInstalled()))
        {
            return null;
        }
        var manager = new UpdateManager(new GithubSource(UpdatePolicy.RepositoryUrl, null, false),
            new UpdateOptions { ExplicitChannel = UpdatePolicy.CurrentChannel });
        return new UpdateService(manager, scheduler);
    }

    /// <summary>
    /// 当前进程是不是 Velopack 装的（开发运行 / 解压运行 / 便携版都是 false）。
    /// 没有 locator（IDE、单元测试里没跑过 <c>VelopackApp.Run()</c>）时也算没安装。
    /// </summary>
    private static bool IsInstalled()
    {
        try
        {
            return new UpdateManager(new UpdateOptions()).IsInstalled;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

    /// <summary>已下载、等下次启动安装的版本（托盘菜单「Restart to update」用它）。</summary>
    public VelopackAsset? ReadyToApply { get; private set; }

    /// <summary>最近一次检查 / 下载的错误。只写进 trace 日志（不打扰用户），留个排查线索。</summary>
    public string? LastError { get; private set; }

    public bool HasReadyUpdate
    {
        get { lock (_lock) return ReadyToApply is not null; }
    }

    /// <summary>启动后 30 秒第一次检查，之后每 6 小时一次。</summary>
    public void Start()
    {
        lock (_lock)
        {
            if (_disposed || _manager is null || _firstCheck is not null) return;
            _firstCheck = _timers.ScheduleOnce(UpdatePolicy.InitialDelay, () =>
            {
                _ = CheckAsync();
                lock (_lock)
                {
                    if (_disposed) return;
                    _periodic = _timers.SchedulePeriodic(UpdatePolicy.Interval, () => _ = CheckAsync());
                }
            });
        }
    }

    /// <summary>检查 → 有新版就在后台下载。串行执行，同一时间只有一次。</summary>
    public async Task CheckAsync()
    {
        UpdateManager? manager;
        lock (_lock)
        {
            if (_disposed || _checking || _manager is null) return;
            _checking = true;
            manager = _manager;
        }
        try
        {
            var update = await manager.CheckForUpdatesAsync().ConfigureAwait(false);
            if (update is null) return;
            await manager.DownloadUpdatesAsync(update).ConfigureAwait(false);
            lock (_lock)
            {
                if (_disposed) return;
                ReadyToApply = update.TargetFullRelease;
                LastError = null;
            }
            // 托盘菜单据此显示「Restart to update」。
            Changed?.Invoke();
        }
        catch (Exception e)
        {
            // 没网 / 限流 / 还没发版都很正常：记下来，下次再试，绝不打扰用户。
            lock (_lock)
            {
                LastError = e.Message;
            }
            System.Diagnostics.Trace.WriteLine($"kanjo: update check failed: {e.Message}");
        }
        finally
        {
            lock (_lock)
            {
                _checking = false;
            }
        }
    }

    /// <summary>托盘菜单「Restart to update」：装上已下载的版本并重启（进程在这里退出）。</summary>
    public void RestartToUpdate()
    {
        VelopackAsset? target;
        UpdateManager? manager;
        lock (_lock)
        {
            target = ReadyToApply;
            manager = _manager;
        }
        if (target is null || manager is null) return;
        manager.ApplyUpdatesAndRestart(target);
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
