namespace Kanjo.Core;

public enum RefreshActionKind
{
    None,
    RefreshNow,
    ScheduleRefresh,
}

/// <summary>调度动作。<see cref="Delay"/> 只在 <see cref="RefreshActionKind.ScheduleRefresh"/> 时有意义。</summary>
public readonly record struct RefreshAction(RefreshActionKind Kind, TimeSpan Delay)
{
    public static readonly RefreshAction None = new(RefreshActionKind.None, TimeSpan.Zero);
    public static readonly RefreshAction RefreshNow = new(RefreshActionKind.RefreshNow, TimeSpan.Zero);
    public static RefreshAction Schedule(TimeSpan delay) => new(RefreshActionKind.ScheduleRefresh, delay);
}

/// <summary>
/// 纯调度决策引擎：防抖、最小间隔、刷新中合并、兜底定时器、睡眠/唤醒、节电模式。
/// 对应 Mac 版 `RefreshScheduler`。
/// </summary>
public sealed class RefreshScheduler
{
    public const int DefaultFallbackMinutes = 30;
    public const int MinimumFallbackMinutes = 15;
    public static readonly TimeSpan DebounceInterval = TimeSpan.FromSeconds(60);
    public static readonly TimeSpan MinimumRefreshInterval = TimeSpan.FromSeconds(120);
    public static readonly TimeSpan MaxDebounceWait = TimeSpan.FromSeconds(180);

    public DateTimeOffset? LastRefreshTime { get; private set; }
    public DateTimeOffset? LastEventTime { get; private set; }
    public DateTimeOffset? FirstUnhandledEventTime { get; private set; }
    public bool IsRefreshing { get; private set; }
    public bool HasPendingEventWhileRefreshing { get; private set; }
    public bool IsAsleep { get; private set; }
    public bool IsLowPowerMode { get; private set; }
    public bool PendingWakeRefresh { get; private set; }
    public int FallbackMinutes { get; set; }

    public RefreshScheduler(int fallbackMinutes = DefaultFallbackMinutes, DateTimeOffset? lastRefreshTime = null)
    {
        FallbackMinutes = MigrateFallbackMinutes(fallbackMinutes);
        LastRefreshTime = lastRefreshTime;
    }

    public static int MigrateFallbackMinutes(int stored)
    {
        if (stored == 0) return 0;
        if (stored == 5 || stored < MinimumFallbackMinutes) return DefaultFallbackMinutes;
        return stored;
    }

    /// <summary>文件变化事件（Windows 上是 FileSystemWatcher）。</summary>
    public RefreshAction OnFileEvent(DateTimeOffset? at = null)
    {
        var date = at ?? DateTimeOffset.UtcNow;
        LastEventTime = date;
        FirstUnhandledEventTime ??= date;
        if (IsAsleep || IsLowPowerMode)
        {
            PendingWakeRefresh = true;
            return RefreshAction.None;
        }
        if (IsRefreshing)
        {
            HasPendingEventWhileRefreshing = true;
            return RefreshAction.None;
        }
        var firstEvent = FirstUnhandledEventTime ?? date;
        var deadline = firstEvent + MaxDebounceWait;
        var debounceTarget = date + DebounceInterval;
        var effectiveTarget = debounceTarget < deadline ? debounceTarget : deadline;
        var minIntervalTarget = (LastRefreshTime ?? DateTimeOffset.MinValue) + MinimumRefreshInterval;
        var scheduledTarget = effectiveTarget > minIntervalTarget ? effectiveTarget : minIntervalTarget;
        var delay = scheduledTarget - date;
        return RefreshAction.Schedule(delay > TimeSpan.Zero ? delay : TimeSpan.Zero);
    }

    public void OnRefreshStarted(DateTimeOffset? at = null)
    {
        IsRefreshing = true;
        HasPendingEventWhileRefreshing = false;
        FirstUnhandledEventTime = null;
    }

    public RefreshAction OnRefreshFinished(DateTimeOffset? at = null)
    {
        var date = at ?? DateTimeOffset.UtcNow;
        IsRefreshing = false;
        LastRefreshTime = date;

        if (IsAsleep || IsLowPowerMode) return RefreshAction.None;

        if (HasPendingEventWhileRefreshing)
        {
            HasPendingEventWhileRefreshing = false;
            var firstEvent = FirstUnhandledEventTime ?? (LastEventTime ?? date);
            var deadline = firstEvent + MaxDebounceWait;
            var debounceTarget = (LastEventTime ?? date) + DebounceInterval;
            var effectiveTarget = debounceTarget < deadline ? debounceTarget : deadline;
            var minIntervalTarget = date + MinimumRefreshInterval;
            var scheduledTarget = effectiveTarget > minIntervalTarget ? effectiveTarget : minIntervalTarget;
            var delay = scheduledTarget - date;
            return RefreshAction.Schedule(delay > TimeSpan.Zero ? delay : TimeSpan.Zero);
        }
        return RefreshAction.None;
    }

    /// <summary>面板打开时：上次刷新超过 120 秒或从未刷新就立刻刷新。</summary>
    public bool ShouldRefreshOnOpen(DateTimeOffset? at = null)
    {
        if (IsRefreshing) return false;
        if (LastRefreshTime is not { } last) return true;
        return (at ?? DateTimeOffset.UtcNow) - last > MinimumRefreshInterval;
    }

    public void OnSleep() => IsAsleep = true;

    public RefreshAction OnWake(DateTimeOffset? at = null)
    {
        var date = at ?? DateTimeOffset.UtcNow;
        IsAsleep = false;
        if (!PendingWakeRefresh) return RefreshAction.None;
        PendingWakeRefresh = false;
        if (IsRefreshing) return RefreshAction.None;
        var minIntervalTarget = (LastRefreshTime ?? DateTimeOffset.MinValue) + MinimumRefreshInterval;
        if (date >= minIntervalTarget) return RefreshAction.RefreshNow;
        var delay = minIntervalTarget - date;
        return RefreshAction.Schedule(delay > TimeSpan.Zero ? delay : TimeSpan.Zero);
    }

    public RefreshAction OnLowPowerModeChanged(bool enabled, DateTimeOffset? at = null)
    {
        var date = at ?? DateTimeOffset.UtcNow;
        IsLowPowerMode = enabled;
        if (!enabled && PendingWakeRefresh)
        {
            PendingWakeRefresh = false;
            if (IsRefreshing) return RefreshAction.None;
            var minIntervalTarget = (LastRefreshTime ?? DateTimeOffset.MinValue) + MinimumRefreshInterval;
            if (date >= minIntervalTarget) return RefreshAction.RefreshNow;
            var delay = minIntervalTarget - date;
            return RefreshAction.Schedule(delay > TimeSpan.Zero ? delay : TimeSpan.Zero);
        }
        return RefreshAction.None;
    }

    public RefreshAction OnFallbackTimerFired(DateTimeOffset? at = null)
    {
        var date = at ?? DateTimeOffset.UtcNow;
        if (FallbackMinutes <= 0) return RefreshAction.None;
        if (IsAsleep || IsLowPowerMode)
        {
            PendingWakeRefresh = true;
            return RefreshAction.None;
        }
        if (IsRefreshing)
        {
            HasPendingEventWhileRefreshing = true;
            return RefreshAction.None;
        }
        var elapsed = date - (LastRefreshTime ?? DateTimeOffset.MinValue);
        return elapsed >= TimeSpan.FromMinutes(FallbackMinutes) ? RefreshAction.RefreshNow : RefreshAction.None;
    }
}

/// <summary>发布到网站（spec Part B3 &amp; B4）的纯调度决策。</summary>
public static class PublishSchedule
{
    /// <summary>失败后最小重试间隔。</summary>
    public static readonly TimeSpan FailureRetryBackoff = TimeSpan.FromSeconds(3600);

    public static readonly TimeSpan DailyInterval = TimeSpan.FromSeconds(86400);

    public static readonly TimeSpan WeeklyInterval = TimeSpan.FromSeconds(7 * 86400);

    public static bool ShouldPublish(
        bool enabled,
        string repoPath,
        PublishFrequency frequency,
        DateTimeOffset? lastSuccessAt,
        DateTimeOffset? lastAttemptAt,
        DateTimeOffset? now = null,
        TimeZoneInfo? timeZone = null)
    {
        if (!enabled) return false;
        if (string.IsNullOrWhiteSpace(repoPath)) return false;

        var n = now ?? DateTimeOffset.UtcNow;

        // Backoff: 上次尝试是失败（在上次成功之后，或从来没有成功过），至少等 1 小时再试。
        if (lastAttemptAt is { } attempt)
        {
            var wasFailure = lastSuccessAt is null || attempt > lastSuccessAt.Value;
            if (wasFailure && n - attempt < FailureRetryBackoff) return false;
        }

        // 从未成功过且已过退避：立刻发布。
        if (lastSuccessAt is not { } success) return true;

        // 时钟回拨保护。
        if (n < success) return false;

        var tz = timeZone ?? TimeZoneInfo.Local;
        switch (frequency)
        {
            case PublishFrequency.Daily:
                return n - success >= DailyInterval;
            case PublishFrequency.Weekly:
                return n - success >= WeeklyInterval;
            default:
            {
                var s = TimeZoneInfo.ConvertTime(success, tz);
                var c = TimeZoneInfo.ConvertTime(n, tz);
                return c.Year > s.Year || (c.Year == s.Year && c.Month > s.Month);
            }
        }
    }
}

/// <summary>家庭用量上报（spec batch 2）的纯调度决策。</summary>
public static class FamilyReportSchedule
{
    /// <summary>两次成功上报之间至少 15 分钟。</summary>
    public static readonly TimeSpan SuccessInterval = TimeSpan.FromMinutes(15);

    /// <summary>失败后至少等 30 分钟再试。</summary>
    public static readonly TimeSpan FailureRetryBackoff = TimeSpan.FromMinutes(30);

    /// <summary>校验服务器 URL（必须 HTTPS，本地测试可用 http://127.0.0.1 或 http://localhost）。</summary>
    public static bool IsValidUrl(string urlString)
    {
        if (!Uri.TryCreate(urlString.Trim(), UriKind.Absolute, out var uri)) return false;
        var scheme = uri.Scheme.ToLowerInvariant();
        var host = uri.Host.ToLowerInvariant();
        if (scheme == "https") return host.Length > 0;
        if (scheme == "http" && (host == "127.0.0.1" || host == "localhost")) return true;
        return false;
    }

    public static bool ShouldReport(
        bool enabled,
        bool hasToken,
        string url,
        DateTimeOffset? lastSuccessAt,
        DateTimeOffset? lastAttemptAt,
        DateTimeOffset? now = null,
        bool noNetwork = false)
    {
        if (!enabled) return false;
        if (!hasToken) return false;
        if (!IsValidUrl(url)) return false;
        if (noNetwork) return false;

        var n = now ?? DateTimeOffset.UtcNow;

        if (lastAttemptAt is { } attempt)
        {
            var wasFailure = lastSuccessAt is null || attempt > lastSuccessAt.Value;
            if (wasFailure && n - attempt < FailureRetryBackoff) return false;
        }

        if (lastSuccessAt is not { } success) return true;

        if (n < success) return false;
        return n - success >= SuccessInterval;
    }
}

public enum FamilyReportStatusStateKind
{
    NoNetwork,
    NoServer,
    InProgress,
    MissingToken,
    Failed,
    LastReported,
    Never,
}

public sealed record FamilyReportStatusState(FamilyReportStatusStateKind Kind, string? Error, DateTimeOffset? Date);

public static class FamilyReportStatus
{
    public static FamilyReportStatusState State(
        string url, bool hasToken, bool isReporting, string? lastError, DateTimeOffset? lastSuccessAt, bool noNetwork)
    {
        if (noNetwork) return new FamilyReportStatusState(FamilyReportStatusStateKind.NoNetwork, null, null);
        var trimmed = url.Trim();
        if (trimmed.Length == 0 || !FamilyReportSchedule.IsValidUrl(trimmed))
        {
            return new FamilyReportStatusState(FamilyReportStatusStateKind.NoServer, null, null);
        }
        if (isReporting) return new FamilyReportStatusState(FamilyReportStatusStateKind.InProgress, null, null);
        if (!hasToken) return new FamilyReportStatusState(FamilyReportStatusStateKind.MissingToken, null, null);
        if (lastError is { } err) return new FamilyReportStatusState(FamilyReportStatusStateKind.Failed, err, null);
        if (lastSuccessAt is { } success) return new FamilyReportStatusState(FamilyReportStatusStateKind.LastReported, null, success);
        return new FamilyReportStatusState(FamilyReportStatusStateKind.Never, null, null);
    }

    public static string Text(
        string url, bool hasToken, bool isReporting, string? lastError, DateTimeOffset? lastSuccessAt,
        bool noNetwork, DateTimeOffset? now = null, string? language = null)
    {
        var state = State(url, hasToken, isReporting, lastError, lastSuccessAt, noNetwork);
        var lang = language ?? L10n.CurrentLanguage;
        return state.Kind switch
        {
            FamilyReportStatusStateKind.NoNetwork => L10n.TrL(lang, "settings.family.status.no_network"),
            FamilyReportStatusStateKind.NoServer => L10n.TrL(lang, "settings.family.status.no_server"),
            FamilyReportStatusStateKind.InProgress => L10n.TrL(lang, "settings.family.status.in_progress"),
            FamilyReportStatusStateKind.MissingToken => L10n.TrL(lang, "settings.family.status.missing_token"),
            FamilyReportStatusStateKind.Failed => L10n.TrL(lang, "settings.family.status.failed", state.Error ?? ""),
            FamilyReportStatusStateKind.LastReported =>
                L10n.TrL(lang, "settings.family.status.last_reported", RelativeText(state.Date!.Value, now ?? DateTimeOffset.UtcNow, lang)),
            _ => L10n.TrL(lang, "settings.family.status.never"),
        };
    }

    /// <summary>相对时间（"5 minutes ago"），近似 Swift 的 RelativeDateTimeFormatter(.full)。</summary>
    public static string RelativeText(DateTimeOffset date, DateTimeOffset now, string? language)
    {
        var lang = language ?? L10n.CurrentLanguage;
        var delta = now - date;
        var future = delta < TimeSpan.Zero;
        var span = future ? -delta : delta;
        if (span.TotalSeconds < 60)
        {
            return lang.StartsWith("zh", StringComparison.Ordinal) ? (future ? "片刻后" : "刚刚")
                : lang.StartsWith("fr", StringComparison.Ordinal) ? (future ? "dans un instant" : "à l'instant")
                : (future ? "in a moment" : "just now");
        }
        var (value, unit) = span.TotalMinutes < 60 ? ((int)span.TotalMinutes, "minute")
            : span.TotalHours < 24 ? ((int)span.TotalHours, "hour")
            : span.TotalDays < 30 ? ((int)span.TotalDays, "day")
            : span.TotalDays < 365 ? ((int)(span.TotalDays / 30), "month")
            : ((int)(span.TotalDays / 365), "year");

        if (lang.StartsWith("zh", StringComparison.Ordinal))
        {
            var names = new Dictionary<string, string>
            {
                ["minute"] = "分钟", ["hour"] = "小时", ["day"] = "天", ["month"] = "个月", ["year"] = "年",
            };
            return future ? $"{value} {names[unit]}后" : $"{value} {names[unit]}前";
        }
        if (lang.StartsWith("fr", StringComparison.Ordinal))
        {
            var names = new Dictionary<string, string>
            {
                ["minute"] = "minute", ["hour"] = "heure", ["day"] = "jour", ["month"] = "mois", ["year"] = "an",
            };
            var plural = value > 1 && unit is not "mois" ? "s" : "";
            return future ? $"dans {value} {names[unit]}{plural}" : $"il y a {value} {names[unit]}{plural}";
        }
        var en = value == 1 ? unit : unit + "s";
        return future ? $"in {value} {en}" : $"{value} {en} ago";
    }
}

/// <summary>
/// 旧版家庭设置的一次性迁移：早期版本 `familyReportURL` 有内置默认值 `https://usage.paytonpei.top`，
/// 曾经启用但没写过 URL 的老用户迁移一次。
/// </summary>
public static class FamilyReportMigration
{
    public const string LegacyDefaultUrl = "https://usage.paytonpei.top";

    /// <summary>返回是否真的写入了 URL。</summary>
    public static bool Migrate(AppSettings? settings = null)
    {
        var store = settings ?? AppSettings.ForLaunch();
        if (store.Bool(SettingsKeys.FamilyReportMigrationDone, false)) return false;
        try
        {
            var isEnabled = store.Bool(SettingsKeys.FamilyReportEnabled, false);
            var hasStoredUrl = store.Raw(SettingsKeys.FamilyReportUrl) is not null;
            if (isEnabled && !hasStoredUrl)
            {
                store.Set(SettingsKeys.FamilyReportUrl, LegacyDefaultUrl);
                return true;
            }
            return false;
        }
        finally
        {
            store.Set(SettingsKeys.FamilyReportMigrationDone, true);
        }
    }
}

/// <summary>首次扫描提示：没有报告且耗时 ≥ 3 秒时展示。</summary>
public static class FirstScanHint
{
    public static readonly TimeSpan Threshold = TimeSpan.FromSeconds(3.0);

    public static bool ShouldShow(bool hasReport, TimeSpan elapsed) => !hasReport && elapsed >= Threshold;

    public static bool ShouldShow(bool hasReport, double elapsedSeconds) =>
        ShouldShow(hasReport, TimeSpan.FromSeconds(elapsedSeconds));

    public static bool ShouldShow(UsageReport? report, TimeSpan elapsed) => ShouldShow(report is not null, elapsed);

    public static bool ShouldShow(UsageReport? report, double elapsedSeconds) =>
        ShouldShow(report is not null, TimeSpan.FromSeconds(elapsedSeconds));

    public static bool ShouldShowHint(bool hasReport, TimeSpan elapsed) => ShouldShow(hasReport, elapsed);

    public static bool ShouldShowHint(UsageReport? report, TimeSpan elapsed) => ShouldShow(report, elapsed);

    /// <summary>首次扫描解释文案。</summary>
    public static string Explanation(string? language = null) => L10n.TrL(language, "menu.first_scan_hint");

    /// <summary>已用时间文案（如 "已用 12 秒" / "12 s elapsed" / "12 s écoulées"）。</summary>
    public static string ElapsedText(int seconds, string? language = null) =>
        L10n.TrL(language, "menu.first_scan_elapsed", Math.Max(0, seconds));

    public static string ElapsedText(TimeSpan elapsed, string? language = null) =>
        ElapsedText((int)Math.Max(0, Math.Floor(elapsed.TotalSeconds)), language);
}

/// <summary>磁盘页刷新状态：刷新时始终保留上一份报告。</summary>
public sealed class DiskReportState
{
    public DiskReport? Report { get; private set; }
    public bool IsLoading { get; private set; }

    public DiskReportState(DiskReport? report = null) => Report = report;

    public bool HasReport => Report is not null;

    public bool IsRescanning => HasReport && IsLoading;

    public bool BeginRefresh()
    {
        if (IsLoading) return false;
        IsLoading = true;
        return true;
    }

    public void FinishRefresh(DiskReport? report = null)
    {
        if (report is not null) Report = report;
        IsLoading = false;
    }

    public bool IsStale(TimeSpan? maxAge = null, DateTimeOffset? now = null)
    {
        if (Report is not { } report) return true;
        var date = ReportDates.ParseTimestamp(report.ScannedAt ?? report.GeneratedAt);
        if (date is null) return true;
        return (now ?? DateTimeOffset.UtcNow) - date.Value > (maxAge ?? TimeSpan.FromHours(6));
    }
}

public static class DiskScanCaption
{
    public static string Text(DiskReport report, DateTimeOffset? now = null)
    {
        var date = ReportDates.ParseTimestamp(report.ScannedAt ?? report.GeneratedAt);
        if (date is null) return L10n.Tr("disk.scan_time_unknown");
        var seconds = Math.Max(0, ((now ?? DateTimeOffset.UtcNow) - date.Value).TotalSeconds);
        if (seconds < 60) return L10n.Tr("disk.scanned_just_now");
        if (seconds < 3600) return L10n.Tr("disk.scanned_min_ago", (int)(seconds / 60));
        if (seconds < 86400) return L10n.Tr("disk.scanned_hr_ago", (int)(seconds / 3600));
        var days = (int)(seconds / 86400);
        return days == 1 ? L10n.Tr("disk.scanned_day_ago", days) : L10n.Tr("disk.scanned_days_ago", days);
    }
}

/// <summary>云端同步指纹：totals + quota 百分比的稳定字符串。</summary>
public static class SyncFingerprint
{
    public static string Make(UsageReport report)
    {
        var parts = new List<string>
        {
            $"cost:{(long)Math.Round(report.Totals.Cost * 100, MidpointRounding.AwayFromZero)}",
            $"tokens:{report.Totals.Tokens.Total}",
            $"sessions:{report.Totals.Sessions}",
        };

        var windows = report.QuotaWindows ?? new Dictionary<string, QuotaWindow>();
        foreach (var agent in windows.Keys.OrderBy(k => k, StringComparer.Ordinal))
        {
            var window = windows[agent];
            parts.Add($"{agent}.weekly:{Percent(window.WeeklyUsedPercent)}");
            parts.Add($"{agent}.five:{Percent(window.FiveHourUsedPercent)}");
            var extras = (window.ExtraWindows ?? []).OrderBy(e => e.Id, StringComparer.Ordinal);
            foreach (var extra in extras)
            {
                parts.Add($"{agent}.{extra.Id}:{Percent(extra.UsedPercent)}");
            }
        }
        return string.Join("|", parts);
    }

    private static string Percent(double? value) =>
        value is { } v ? ((long)Math.Round(v, MidpointRounding.AwayFromZero)).ToString(System.Globalization.CultureInfo.InvariantCulture) : "-";
}

/// <summary>菜单栏（Windows 上是托盘 tooltip）文本生成器：纯逻辑，方便测试。</summary>
public static class MenuBarText
{
    /// <summary>金额：金额优先，固定窗口显示后缀（如 `$3,057 · 30d`）；其他范围无后缀。</summary>
    public static string Make(double cost, string currency, TimeRange range)
    {
        var amount = Fmt.MenuBarMoney(cost, currency);
        var suffix = range.MenuBarSuffix();
        return string.IsNullOrEmpty(suffix) ? amount : $"{amount} · {suffix}";
    }

    /// <summary>Token：Token 优先，固定窗口显示后缀（如 `23.5B · 30d`）；其他范围无后缀。</summary>
    public static string Make(long tokens, TimeRange range, string? language = null)
    {
        var formatted = language is null ? Fmt.Tokens(tokens) : Fmt.Tokens(tokens, language);
        var suffix = range.MenuBarSuffix();
        return string.IsNullOrEmpty(suffix) ? formatted : $"{formatted} · {suffix}";
    }

    /// <summary>统一入口，支持按模式格式化。</summary>
    public static string Make(MenuBarMode mode, double cost, long tokens, string currency, TimeRange range, string? language = null) =>
        mode == MenuBarMode.Tokens ? Make(tokens, range, language) : Make(cost, currency, range);
}
