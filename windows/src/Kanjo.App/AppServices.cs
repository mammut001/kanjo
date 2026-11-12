using Avalonia.Controls;
using Kanjo.App.Views;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 应用服务容器：设置、数据源（--data / CLI）、磁盘报告、配置写入、家庭上报 / 发布。
/// 所有状态都从设置里读，UI 只订阅 <see cref="Changed"/>。
/// </summary>
public sealed class AppServices
{
    public AppSettings Settings { get; }
    public string[] Arguments { get; }
    public string? DataOverride { get; }
    public string? DiskDataOverride { get; }

    /// <summary>UI 状态变化（报告 / 语言 / 设置变更）。</summary>
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

    /// <summary>磁盘报告缓存的目录（测试 / 隔离用）；null 表示 <c>%LOCALAPPDATA%\Kanjo</c>。</summary>
    public string? CacheDirectory { get; }

    public AppServices(AppSettings settings, string[] arguments, string? cacheDirectory = null)
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

        Config = new ConfigDataSource(BuildRunner);
        Disk = new DiskStore(MakeDiskSource,
            DiskDataOverride is null ? new DiskReportCache(cacheDirectory) : null);
        Disk.Changed += NotifyChanged;
        Family = new FamilyReportStore(settings, NewTokenStorage(), () => BuildRunnerOrNull(), NoNetworkReason);
        Publish = new PublishStore(settings, () => BuildRunnerOrNull(), NoNetworkReason);
        Family.Activity.Changed += NotifyChanged;
        Publish.Activity.Changed += NotifyChanged;
    }

    private static IFamilyTokenStorage NewTokenStorage() =>
        WindowsCredentialFamilyTokenStorage.IsSupported
            ? new WindowsCredentialFamilyTokenStorage()
            : new InMemoryFamilyTokenStorage();

    public static AppServices Create(string[] arguments, string? settingsDirectory = null,
        string? cacheDirectory = null)
    {
        var settings = AppSettings.ForLaunch(arguments, AppSettings.ReadEnvironment(), settingsDirectory);
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
    public void Refresh()
    {
        IsLoading = true;
        Changed?.Invoke();
        try
        {
            Report = LoadReport();
            Error = null;
            LastRefresh = DateTimeOffset.UtcNow;
        }
        catch (DataSourceError e)
        {
            Error = e.Message;
        }
        catch (Exception e)
        {
            Error = e.Message;
        }
        finally
        {
            IsLoading = false;
            Changed?.Invoke();
        }
        AfterRefresh();
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

    /// <summary>用量报告就绪后：磁盘预取 + 定时上报（发布 / 家庭）。都放后台，不阻塞 UI。</summary>
    private void AfterRefresh()
    {
        if (Report is not { } report) return;
        if (DiskDataOverride is null && !Disk.IsLoading && (!Disk.HasReport || Disk.IsStale()))
        {
            Disk.Refresh();
        }
        Task.Run(() =>
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
        });
    }

    /// <summary>当前数据源的可读描述（出错时也能显示，方便排查）。</summary>
    public string DescribeSource()
    {
        if (DataOverride is { } path) return $"File (--data): {path}";
        var kind = SourceKinds.Parse(Settings.GetString(SettingsKeys.SourceKind)) ?? SourceKind.File;
        if (kind == SourceKind.File)
        {
            var raw = Settings.Str(SettingsKeys.FilePath, SettingsDefaults.FilePath).Trim();
            var file = raw.Length == 0 ? DefaultPaths.SampleFixture : DefaultPaths.ExpandTilde(raw);
            return $"File: {file}";
        }
        return "Command: python -m kanjo export";
    }

    private UsageReport LoadReport()
    {
        SourceDescription = DescribeSource();
        if (DataOverride is { } path)
        {
            return new FileDataSource(path).Load();
        }

        var kind = SourceKinds.Parse(Settings.GetString(SettingsKeys.SourceKind)) ?? SourceKind.File;
        if (kind == SourceKind.File)
        {
            var raw = Settings.Str(SettingsKeys.FilePath, SettingsDefaults.FilePath).Trim();
            var file = raw.Length == 0 ? DefaultPaths.SampleFixture : DefaultPaths.ExpandTilde(raw);
            return new FileDataSource(file).Load();
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
        SourceKinds.Parse(Settings.GetString(SettingsKeys.SourceKind)) == SourceKind.Cli;

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

    /// <summary>设置变更后重新读数据（语言 / 范围 / 数据源）。</summary>
    public void ApplySettings()
    {
        L10n.ResetCache();
        Disk.ApplySettings();
        Config.ResetCache();
        Refresh();
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
