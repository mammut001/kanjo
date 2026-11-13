using Avalonia.Controls;
using Avalonia.Threading;
using Kanjo.App.Views;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 应用服务容器：设置、数据源（--data / CLI）、磁盘报告、配置写入、家庭上报 / 发布，
/// 以及后台刷新的编排（文件监听 / 兜底定时器 / 电源事件 / 面板打开）。
/// 所有状态都从设置里读，UI 只订阅 <see cref="Changed"/>。
/// </summary>
public sealed class AppServices
{
    private readonly object _refreshLock = new();
    private int _generation;
    private IReportCommandRunner? _reportRunner;

    public AppSettings Settings { get; }
    public string[] Arguments { get; }
    public string? DataOverride { get; }
    public string? DiskDataOverride { get; }

    /// <summary>UI 状态变化（报告 / 语言 / 设置变更）。可能在后台线程触发。</summary>
    public event Action? Changed;

    public UsageReport? Report { get; private set; }
    public string? Error { get; private set; }
    public bool IsLoading { get; private set; }
    public DateTimeOffset? LastRefresh { get; private set; }
    public string SourceDescription { get; private set; } = "";

    public ConfigDataSource Config { get; }
    public DiskStore Disk { get; }
    public FamilyReportStore Family { get; }
    public PublishStore Publish { get; }

    /// <summary>
    /// 自动更新的状态（面板横幅 + 设置页 Updates 卡片）。默认是「没安装」的空壳，
    /// 由 <see cref="App.KanjoApplication"/> / 截图在拿到真正的 <see cref="App.UpdateService"/> 后
    /// 用 <see cref="UseUpdates"/> 换掉。
    /// </summary>
    public UpdateService Updates { get; private set; } = UpdateService.CreateUnavailable();

    /// <summary>
    /// 更新状态变了。**不**走 <see cref="Changed"/>：那会让整个面板重建成新的一页（下载进度
    /// 每跳 5% 就把设置页的滚动位置清零）。界面只重建横幅和 Updates 卡片。
    /// </summary>
    public event Action? UpdatesChanged;

    /// <summary>装上真正的更新服务（状态变化会触发 <see cref="UpdatesChanged"/>）。</summary>
    public void UseUpdates(UpdateService updates)
    {
        Updates.Changed -= OnUpdatesChanged;
        Updates = updates;
        Updates.Changed += OnUpdatesChanged;
        OnUpdatesChanged();
    }

    private void OnUpdatesChanged() => UpdatesChanged?.Invoke();

    /// <summary>文件变化 / 兜底定时器 / 睡眠唤醒 / 节电模式 / 面板打开。</summary>
    public RefreshEngine Background { get; }

    /// <summary>磁盘报告的延迟预取（第一次 15 秒，之后立即）。</summary>
    public DiskPrefetcher DiskPrefetch { get; }

    /// <summary>磁盘报告缓存的目录（测试 / 隔离用）；null 表示 <c>%LOCALAPPDATA%\Kanjo</c>。</summary>
    public string? CacheDirectory { get; }

    public AppServices(AppSettings settings, string[] arguments, string? cacheDirectory = null,
        IBackgroundScheduler? timers = null, ILogWatcherFactory? watcherFactory = null,
        IPowerMonitor? powerMonitor = null, IEnumerable<string>? logPathsFallback = null)
    {
        Settings = settings;
        Arguments = arguments;
        CacheDirectory = cacheDirectory;
        L10n.Store = settings;
        DataOverride = DefaultPaths.DataOverride(arguments, AppSettings.ReadEnvironment());
        DiskDataOverride = DefaultPaths.DiskDataOverride(arguments);
        // 截图要可复现：热力条 / 相对日期都基于报告时间，而不是墙钟。
        SnapshotMode = arguments.Contains("--snapshot") ||
                       arguments.Any(a => a.StartsWith("--snapshot=", StringComparison.Ordinal));

        Config = new ConfigDataSource(BuildRunner)
        {
            // 后台回调切回 UI 线程（设置页预热档位表用）。
            CompletionDispatcher = DispatchAction,
        };
        Disk = new DiskStore(MakeDiskSource,
            DiskDataOverride is null ? new DiskReportCache(cacheDirectory) : null);
        Disk.Changed += NotifyChanged;
        Family = new FamilyReportStore(settings, NewTokenStorage(), () => ReportRunnerOrNull(), NoNetworkReason);
        Publish = new PublishStore(settings, () => ReportRunnerOrNull(), NoNetworkReason);
        Family.Activity.Changed += NotifyChanged;
        Publish.Activity.Changed += NotifyChanged;

        var scheduler = timers ?? ThreadPoolBackgroundScheduler.Shared;
        Background = new RefreshEngine(scheduler, null,
            settings.Int(SettingsKeys.RefreshMinutes, SettingsDefaults.RefreshMinutes));
        Background.RefreshRequested += OnRefreshRequested;
        // 截图模式完全静止：不挂系统事件、不起轮询（否则离屏渲染会去读真实电源状态）。
        Background.Attach(watcherFactory ?? new FileSystemLogWatcherFactory(),
            SnapshotMode ? NullPowerMonitor.Shared : powerMonitor ?? CreatePowerMonitor());
        DiskPrefetch = new DiskPrefetcher(scheduler, () => Disk.Refresh());
        LogPathsFallback = logPathsFallback?.ToList();
    }

    /// <summary>CLI `paths` 不可用时用的兜底目录（测试注入；正式运行只信 CLI）。</summary>
    public IReadOnlyList<string>? LogPathsFallback { get; }

    /// <summary>最近一次解析到的日志目录（托盘 / 测试可见）。</summary>
    public IReadOnlyList<string> LogPaths { get; private set; } = [];

    private static IPowerMonitor CreatePowerMonitor() =>
        OperatingSystem.IsWindows() ? new WindowsPowerMonitor() : NullPowerMonitor.Shared;

    private static IFamilyTokenStorage NewTokenStorage() =>
        WindowsCredentialFamilyTokenStorage.IsSupported
            ? new WindowsCredentialFamilyTokenStorage()
            : new InMemoryFamilyTokenStorage();

    public static AppServices Create(string[] arguments, string? settingsDirectory = null,
        string? cacheDirectory = null)
    {
        var settings = AppSettings.ForLaunch(arguments, AppSettings.ReadEnvironment(), settingsDirectory);
        FamilyReportMigration.Migrate(settings);
        return new AppServices(settings, arguments, cacheDirectory);
    }

    /// <summary>订阅卡是否展开（「Show N more」开关；批次 2 起是页面本地状态，保留给截图 / 兼容）。</summary>
    public bool SubscriptionCardExpanded { get; set; }

    /// <summary>「+N more」模型的展开状态（总览页本地状态）。</summary>
    public bool ModelsExpanded { get; set; }

    /// <summary>页面切换请求（底栏按钮 / 续费日提醒 / 返回按钮）。</summary>
    public event Action<AppRoute>? NavigateRequested;

    public void RequestNavigate(AppRoute route) => NavigateRequested?.Invoke(route);

    /// <summary>截图模式（--snapshot）：所有「现在」都取报告时间，保证图片可复现。</summary>
    public bool SnapshotMode { get; }

    /// <summary>
    /// 是否运行后台行为（监听 / 定时器 / 电源事件）。`--snapshot` 是离屏渲染，什么都不要跑；
    /// 托盘模式和 `--window` 开发预览都跑（Mac 的 ReportStore 是单例，预览窗口也照样有定时器）。
    /// </summary>
    public bool RunsBackground => !SnapshotMode;

    /// <summary>
    /// 当前时刻：正常运行时是真实时钟（和 Mac 一致）；只有 --snapshot 才固定在报告的 generated_at，
    /// 这样截图里的相对日期 / 账期倒计时可复现。
    /// </summary>
    public DateTimeOffset Now
    {
        get
        {
            if (!SnapshotMode) return DateTimeOffset.UtcNow;
            if (Report is { } r && ReportDates.ParseTimestamp(r.GeneratedAt) is { } generated) return generated;
            if (Disk.Report is { } d && ReportDates.ParseTimestamp(d.ScannedAt ?? d.GeneratedAt) is { } scanned)
            {
                return scanned;
            }
            return DateTimeOffset.UtcNow;
        }
    }

    public string Language => Settings.Str(SettingsKeys.AppLanguage, SettingsDefaults.AppLanguage);

    public MenuBarMode Mode => MenuBarModes.Parse(Settings.Str(SettingsKeys.MenuBarMode, SettingsDefaults.MenuBarMode))
                               ?? MenuBarMode.Cost;

    public bool ShowAmount => Settings.Bool(SettingsKeys.ShowAmountInMenuBar, SettingsDefaults.ShowAmountInMenuBar);

    public TimeRange Range =>
        TimeRanges.Parse(Settings.Str(SettingsKeys.TimeRange, SettingsDefaults.TimeRange)) ?? TimeRange.All;

    /// <summary>当前范围内的金额与 token（和总览 hero 同一个数）。</summary>
    public (double Cost, long Tokens, TimeRange Range) CurrentTotals()
    {
        if (Report is not { } report) return (0, 0, Range);
        var ctx = new RangeContext(report, Settings.GetString(SettingsKeys.TimeRange));
        if (ctx.IsAll) return (report.Totals.Cost, report.Totals.Tokens.Total, ctx.Range);
        var filtered = ctx.Filtered();
        return (filtered.Cost, filtered.Tokens, ctx.Range);
    }

    public string TrayTooltipText()
    {
        var (cost, tokens, range) = CurrentTotals();
        var currency = Report?.Currency ?? "USD";
        return Core.TrayTooltip.Build(Report is not null, Error is not null, ShowAmount, Mode, cost, tokens, currency, range);
    }

    public TrayStatus TrayStatus => Core.TrayTooltip.Status(Report is not null, Error is not null);

    /// <summary>从 --data 或 CLI 读一次报告。同步执行（UI 线程调用时请自己放到后台）。</summary>
    public void Refresh() => Refresh(RefreshTrigger.UserInitiated);

    /// <summary>
    /// 一次刷新（对应 Mac 的 <c>ReportStore.refresh(qualityOfService:)</c>）：
    /// 取消待触发的防抖任务 → scheduler.onRefreshStarted → 加载 → scheduler.onRefreshFinished。
    /// 失败时保留上一份报告（面板顶部显示错误），但不触发发布 / 家庭上报（Mac 只在成功分支调用）。
    /// </summary>
    public void Refresh(RefreshTrigger trigger)
    {
        _ = trigger;
        Background.BeginRefresh();
        DiskPrefetch.Cancel();
        int generation;
        lock (_refreshLock)
        {
            generation = ++_generation;
            IsLoading = true;
        }
        Changed?.Invoke();

        UsageReport? loaded = null;
        var superseded = false;
        try
        {
            loaded = LoadReport();
            lock (_refreshLock)
            {
                if (generation != _generation)
                {
                    superseded = true;
                }
                else
                {
                    Report = loaded;
                    Error = null;
                }
            }
        }
        catch (Exception e)
        {
            lock (_refreshLock)
            {
                if (generation != _generation) superseded = true;
                // 刷新失败时保留上一份报告，面板顶部显示错误。
                else Error = e is DataSourceError d ? d.Message : e.Message;
            }
        }
        finally
        {
            lock (_refreshLock)
            {
                if (!superseded)
                {
                    LastRefresh = DateTimeOffset.UtcNow;
                    IsLoading = false;
                }
            }
            Changed?.Invoke();
        }

        if (superseded) return;
        Background.EndRefresh();

        // 磁盘预取 / 兜底监听重建：成功和失败都要（Mac 把 schedulePrefetch 放在共用尾部）。
        AfterRefresh(loaded);
        if (loaded is not null)
        {
            // 发布 / 家庭上报只看成功加载的新报告。
            Task.Run(() => ReportLoaded(loaded));
        }
    }

    /// <summary>只加载，不触发通知（快照用，避免 UI 抖动）。</summary>
    public void LoadQuietly()
    {
        try
        {
            Report = LoadReport();
            Error = null;
            LastRefresh = DateTimeOffset.UtcNow;
        }
        catch (Exception e)
        {
            Error = e is DataSourceError d ? d.Message : e.Message;
        }
    }

    /// <summary>
    /// 托盘模式启动（Mac 的 <c>ReportStore.init</c> 顺序）：先刷一次用量，再建兜底定时器，
    /// 最后解析日志目录挂监听。
    /// </summary>
    public void StartBackground()
    {
        Refresh();
        Background.RestartFallbackTimer(
            Settings.Int(SettingsKeys.RefreshMinutes, SettingsDefaults.RefreshMinutes));
        SetupWatcher();
    }

    /// <summary>面板每次打开（Mac 的 <c>MenuPanelView.onAppear</c> → <c>ReportStore.onPanelOpened</c>）。</summary>
    public void OnPanelOpened() => Background.OnPanelOpened();

    /// <summary>托盘右键「Refresh」：用户主动刷新，取消待触发的防抖任务。</summary>
    public void RequestUserRefresh() => Background.RequestRefresh();

    /// <summary>设置里改了「Fallback refresh interval」：立即按新值重排（Mac 的 <c>store.restartTimer()</c>）。</summary>
    public void RestartFallbackTimer() =>
        Background.RestartFallbackTimer(
            Settings.Int(SettingsKeys.RefreshMinutes, SettingsDefaults.RefreshMinutes));

    private void OnRefreshRequested(RefreshTrigger trigger) => Refresh(trigger);

    /// <summary>
    /// 重新解析日志目录并重建监听（Mac 的 <c>setupWatcher</c>）：
    /// 只有 CLI 数据源且没有 --data 覆盖时监听；Mac 用 `kanjo paths --json` 拿路径，这里也一样。
    /// </summary>
    public void SetupWatcher()
    {
        var kind = SourceResolution.Resolve(Settings.GetString(SettingsKeys.SourceKind));
        if (!LogWatchPaths.ShouldWatch(DataOverride is not null, kind))
        {
            Background.StopWatcher();
            LogPaths = [];
            return;
        }

        var runner = BuildRunner();
        Task.Run(() =>
        {
            IReadOnlyList<string> paths;
            try
            {
                paths = ReportPaths(runner);
            }
            catch (Exception)
            {
                // CLI paths 拿不到：靠兜底定时器刷新（和 Mac 的注释一致）。
                paths = LogPathsFallback ?? [];
            }
            if (paths.Count == 0) return;
            DispatchAction(() =>
            {
                LogPaths = paths;
                Background.StartWatcher(paths);
            });
        });
    }

    /// <summary>`kanjo paths --json` 里所有 agent 的目录（去重）。</summary>
    public IReadOnlyList<string> ReportPaths(CliRunner runner) => LogWatchPaths.Flatten(runner.Paths());

    private bool UsesCliSource =>
        SourceResolution.Resolve(Settings.GetString(SettingsKeys.SourceKind)) == SourceKind.Cli;

    /// <summary>用量刷新完成后：磁盘预取 + 监听器自愈。都放后台，不阻塞 UI。</summary>
    private void AfterRefresh(UsageReport? report)
    {
        _ = report;
        // 磁盘预取：启动后第一次等 15 秒（Mac 的 schedulePrefetch(delay: 15)），之后每次用量刷新完成立即预取；
        // 已经有新鲜报告就不重复扫描（磁盘页 onAppear 的判断也是「缺报告或过期才刷」）。
        // 扫描本身在 DiskStore 里串行排队，不会两个 disk 进程抢 CPU。
        if (DiskDataOverride is null && (!Disk.HasReport || Disk.IsStale()))
        {
            DiskPrefetch.Schedule();
        }

        // 监听器没建起来（目录还不存在 / CLI paths 当时失败）时，下一次刷新再试一次。
        if (RunsBackground && DataOverride is null && UsesCliSource && !Background.IsWatching)
        {
            SetupWatcher();
        }
    }

    /// <summary>成功加载报告后：发布到网站 / 家庭上报（Mac 的 reportDidRefresh 调用点）。</summary>
    private void ReportLoaded(UsageReport report)
    {
        try
        {
            Publish.ReportDidRefresh(report);
        }
        catch (Exception)
        {
            // 发布失败不影响用量。
        }
        try
        {
            Family.ReportDidRefresh(report);
        }
        catch (Exception)
        {
            // 上报失败不影响用量。
        }
    }

    /// <summary>当前数据源的可读描述（和 Mac 的 <c>makeSource</c> 文案一致，出错时也能显示）。</summary>
    public string DescribeSource()
    {
        if (DataOverride is { } path) return $"File (--data): {path}";
        var kind = SourceResolution.Resolve(Settings.GetString(SettingsKeys.SourceKind));
        if (kind == SourceKind.File)
        {
            return $"File: {SourceResolution.FileFor(Settings.GetString(SettingsKeys.FilePath))}";
        }
        return DescribeCliSource();
    }

    /// <summary>
    /// CLI 来源的描述：`Command: python -m kanjo export (in &lt;cli dir&gt;)`。
    /// 安装版里 python 和 cli 目录都是包里的（&lt;appdir&gt;\python\python.exe、&lt;appdir&gt;\cli），
    /// 用真实解析出来的值，而不是写死一句默认命令。
    /// </summary>
    private string DescribeCliSource()
    {
        var runner = BuildRunner();
        var python = runner.PythonExecutable ?? CliRunner.ResolvePython()?.Executable;
        var cwd = CliRunner.ResolveCliDirectory(runner.WorkingDirectory);
        var command = python is null ? "python -m kanjo export" : $"{Path.GetFileName(python)} -m kanjo export";
        return $"Command: {command}" + (cwd is null ? "" : $" (in {cwd})");
    }

    private UsageReport LoadReport()
    {
        SourceDescription = DescribeSource();
        if (DataOverride is { } path)
        {
            return new FileDataSource(path).Load();
        }

        var kind = SourceResolution.Resolve(Settings.GetString(SettingsKeys.SourceKind));
        if (kind == SourceKind.File)
        {
            // 只有文件来源且路径留空时才读示例数据（Mac 的 settings.file_note）。
            return new FileDataSource(SourceResolution.FileFor(Settings.GetString(SettingsKeys.FilePath))).Load();
        }

        return BuildRunner().Export();
    }

    public CliRunner BuildRunner()
    {
        var configuredDir = Settings.Str(SettingsKeys.CliWorkingDirectory, SettingsDefaults.CliWorkingDirectory).Trim();
        return new CliRunner
        {
            WorkingDirectory = configuredDir.Length == 0 ? null : configuredDir,
        };
    }

    /// <summary>能跑 CLI 时返回 runner，否则 null（发布 / 家庭上报用）。</summary>
    public CliRunner? BuildRunnerOrNull()
    {
        try
        {
            var runner = BuildRunner();
            return runner.CanRun(out _) ? runner : null;
        }
        catch (Exception)
        {
            return null;
        }
    }

    /// <summary>发布 / 家庭上报用的命令运行器（截图 / 测试可换成假实现）。</summary>
    public IReportCommandRunner? ReportRunnerOrNull() => _reportRunner ?? BuildRunnerOrNull();

    /// <summary>替换发布 / 家庭上报的执行器（测试注入假实现）。</summary>
    public void UseReportRunner(IReportCommandRunner? runner) => _reportRunner = runner;

    /// <summary>`KANJO_NO_NETWORK=1` 或报告的 config.no_network 为真时，发布 / 上报暂停。</summary>
    public string? NoNetworkReason()
    {
        if (Environment.GetEnvironmentVariable("KANJO_NO_NETWORK") == "1") return "KANJO_NO_NETWORK=1";
        if (Report?.Config.NoNetwork == true) return "config.no_network";
        return null;
    }

    /// <summary>设置里的订阅编辑只在 CLI 数据源且没有 --data 覆盖时可用。</summary>
    public bool CanEditSubscriptions =>
        DataOverride is null &&
        SourceResolution.Resolve(Settings.GetString(SettingsKeys.SourceKind)) == SourceKind.Cli;

    /// <summary>磁盘页的数据源：`--disk-data` 文件，否则 CLI（`disk --json --max-age 21600 [--rescan]`）。</summary>
    private (IDiskSource Source, string Description) MakeDiskSource(bool rescan)
    {
        if (DiskDataOverride is { } file)
        {
            return (new FileDiskSource(file), $"File (--disk-data): {file}");
        }
        var runner = BuildRunner();
        var shown = DiskCommand.Report("python -m kanjo export", rescan, TimeSpan.FromHours(6));
        var cwd = CliRunner.ResolveCliDirectory(runner.WorkingDirectory);
        var description = $"Command: {shown}" + (cwd is null ? "" : $" (in {cwd})");
        return (new CliCliDiskSource(runner, rescan), description);
    }

    public void NotifyChanged() => Changed?.Invoke();

    /// <summary>把回调切到 UI 线程；测试可换成直接执行（默认走 Avalonia 的 Dispatcher）。</summary>
    public Action<Action> DispatchAction { get; set; } = Dispatch;

    private static void Dispatch(Action action)
    {
        try
        {
            if (Dispatcher.UIThread.CheckAccess()) action();
            else Dispatcher.UIThread.Post(action);
        }
        catch (Exception)
        {
            // 没有 UI 线程（单元测试 / 无显示器）：直接执行。
            action();
        }
    }

    /// <summary>设置变更后重新读数据（语言 / 范围 / 数据源 / 定时器 / 监听器）。</summary>
    public void ApplySettings()
    {
        L10n.ResetCache();
        if (RunsBackground)
        {
            // Mac 的 applySettings 顺序：restartTimer() → setupWatcher() → DiskStore.applySettings() → refresh()。
            RestartFallbackTimer();
            SetupWatcher();
        }
        Disk.ApplySettings();
        DiskPrefetch.Cancel();
        Config.ResetCache();
        // 刷新可能跑 CLI（几秒）：放到后台，别卡住设置页。
        Task.Run(() => Refresh(RefreshTrigger.UserInitiated));
    }
}

/// <summary>`kanjo disk --json --max-age 21600 [--rescan]` / `disk clean` 的数据源。</summary>
public sealed class CliCliDiskSource : IDiskSource
{
    private readonly CliRunner _runner;
    private readonly bool _rescan;

    public CliCliDiskSource(CliRunner runner, bool rescan)
    {
        _runner = runner;
        _rescan = rescan;
    }

    public DiskReport Load() => _rescan
        ? _runner.Disk(rescan: true)
        : _runner.Disk(maxAge: TimeSpan.FromHours(6));

    public CleanResult Clean(IReadOnlyList<string> ids, string? olderThan, bool confirmed) =>
        _runner.DiskClean(ids, olderThan, confirmed);
}
