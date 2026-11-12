using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 应用服务容器：设置、数据源（--data / CLI）、托盘文本刷新。
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

    public AppServices(AppSettings settings, string[] arguments)
    {
        Settings = settings;
        Arguments = arguments;
        L10n.Store = settings;
        DataOverride = DefaultPaths.DataOverride(arguments, AppSettings.ReadEnvironment());
        DiskDataOverride = DefaultPaths.DiskDataOverride(arguments);
        // 截图要可复现：热力条 / 相对日期都基于报告时间，而不是墙钟。
        SnapshotMode = arguments.Contains("--snapshot") ||
                       arguments.Any(a => a.StartsWith("--snapshot=", StringComparison.Ordinal));
        _now = SnapshotMode ? null : DateTimeOffset.UtcNow;
    }

    private readonly DateTimeOffset? _now;

    /// <summary>截图模式（--snapshot）：所有「现在」都取报告时间，保证图片可复现。</summary>
    public bool SnapshotMode { get; }

    /// <summary>当前时刻。截图模式下固定在报告的 generated_at。</summary>
    public DateTimeOffset Now => _now ?? ReportGeneratedAt ?? DateTimeOffset.UtcNow;

    private DateTimeOffset? ReportGeneratedAt =>
        Report is { } r ? ReportDates.ParseTimestamp(r.GeneratedAt) : null;

    public static AppServices Create(string[] arguments, string? settingsDirectory = null)
    {
        var settings = AppSettings.ForLaunch(arguments, AppSettings.ReadEnvironment(), settingsDirectory);
        return new AppServices(settings, arguments);
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

    public void NotifyChanged() => Changed?.Invoke();

    /// <summary>设置变更后重新读数据（语言 / 范围 / 数据源）。</summary>
    public void ApplySettings()
    {
        L10n.ResetCache();
        Refresh();
    }
}
