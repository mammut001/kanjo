using Avalonia.Threading;
using Kanjo.Core;
using Velopack;

namespace Kanjo.App;

/// <summary>
/// 自动更新（Velopack + GitHub Releases）的门面：判断能不能更新（<see cref="UpdatePolicy"/>）、
/// 建真正的 Velopack 管理器，然后把状态机交给 Core 的 <see cref="UpdateCoordinator"/>。
///
/// <list type="bullet">
/// <item>启动 30 秒后检查一次，之后每 6 小时一次；</item>
/// <item>有更新就在后台下载，下载完进 Ready（面板横幅 + 设置页按钮出现）；</item>
/// <item>下次启动时由 Velopack 自己装上（<c>SetAutoApplyOnStartup</c>），
///       用户也可以点「Restart to update」立刻重启装上（托盘菜单 / 横幅 / 设置页同一条路径）。</item>
/// </list>
///
/// 不是安装版（开发运行、解压运行、便携版、截图 / 预览模式）时照样有这个对象，只是状态是
/// <see cref="UpdateState.NotInstalled"/>：设置页显示版本号 + 一句说明，按钮禁用，绝不联网。
/// </summary>
public sealed class UpdateService : IDisposable
{
    private readonly UpdateCoordinator _coordinator;

    private UpdateService(UpdateCoordinator coordinator) => _coordinator = coordinator;

    /// <summary>状态变了（已切到 UI 线程）。面板 / 设置页 / 托盘菜单据此重建。</summary>
    public event Action? Changed
    {
        add => _coordinator.Changed += value;
        remove => _coordinator.Changed -= value;
    }

    /// <summary>当前状态快照（Idle / Checking / UpToDate / Downloading / Ready / Failed / NotInstalled）。</summary>
    public UpdateStatus Status => _coordinator.Status;

    /// <summary>本进程的版本号（设置页「Current version」）。</summary>
    public string CurrentVersion => _coordinator.CurrentVersion;

    /// <summary>已下载、可以立刻重启装上的版本。</summary>
    public bool HasReadyUpdate => _coordinator.HasReadyUpdate;

    /// <summary>用户关掉了哪个版本的横幅（只在本次运行有效）。</summary>
    public string? DismissedVersion => _coordinator.DismissedVersion;

    /// <summary>关掉面板顶部的更新横幅（同一次运行里不再出现）。</summary>
    public void DismissBanner() => _coordinator.DismissBanner();

    /// <summary>
    /// 按策略决定要不要真的连 Velopack；不该更新（开发运行、截图 / 预览模式、非 Velopack 安装）时
    /// 返回一个 NotInstalled 状态的空壳，界面仍然能显示版本号。
    /// </summary>
    public static UpdateService Create(IReadOnlyList<string> args, IBackgroundScheduler? timers = null,
        Action<Action>? dispatch = null)
    {
        var version = AppVersion.Current;
        var scheduler = timers ?? ThreadPoolBackgroundScheduler.Shared;
        IUpdateManager? manager = null;
        if (UpdatePolicy.ShouldRun(args, DefaultPaths.IsDebugBuild, IsInstalled()))
        {
            try
            {
                manager = VelopackUpdateManager.Create();
            }
            catch (Exception e)
            {
                // locator 坏了 / 目录不可写：当没安装处理（设置页会说明），绝不因此起不来。
                System.Diagnostics.Trace.WriteLine($"kanjo: update manager unavailable: {e.Message}");
            }
        }
        var coordinator = new UpdateCoordinator(manager, manager?.CurrentVersion ?? version, scheduler,
            dispatch ?? DispatchToUi);
        return new UpdateService(coordinator);
    }

    /// <summary>
    /// 只用于截图 / 测试：给定状态，不联网（快照里注入假的 Ready / Downloading）。
    /// </summary>
    public static UpdateService ForSnapshot(UpdateStatus status, IBackgroundScheduler? timers = null)
    {
        var coordinator = new UpdateCoordinator(null, status.CurrentVersion, timers, action => action());
        coordinator.SeedForSnapshot(status);
        return new UpdateService(coordinator);
    }

    /// <summary>
    /// 没有任何更新能力（纯 Core 测试 / 还没接上真正服务的 <see cref="AppServices"/>）：
    /// 状态是 NotInstalled，只显示版本号，绝不联网。
    /// </summary>
    public static UpdateService CreateUnavailable() =>
        ForSnapshot(UpdateStatus.NotInstalled(AppVersion.Current));

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

    /// <summary>启动后 30 秒第一次检查，之后每 6 小时一次（非安装版什么都不做）。</summary>
    public void Start() => _coordinator.Start();

    /// <summary>用户点「Check for updates」：立刻检查（正在跑时复用同一次，不叠加）。</summary>
    public Task CheckNowAsync() => _coordinator.CheckNowAsync();

    /// <summary>装上已下载的版本并重启（Velopack 会在这里结束进程）。</summary>
    public void RestartToUpdate() => _coordinator.RestartToUpdate();

    /// <summary>和 <c>AppServices.DispatchAction</c> 同一条规则：非 UI 线程就 Post 过去。</summary>
    private static void DispatchToUi(Action action)
    {
        try
        {
            if (Dispatcher.UIThread.CheckAccess()) action();
            else Dispatcher.UIThread.Post(action);
        }
        catch (Exception)
        {
            action();
        }
    }

    public void Dispose() => _coordinator.Dispose();
}
