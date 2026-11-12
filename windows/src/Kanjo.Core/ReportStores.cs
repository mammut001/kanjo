using System.Globalization;
using System.Text.Json.Nodes;

namespace Kanjo.Core;

/// <summary>
/// 跑发布 / 家庭上报的命令（和用量导出用同一个 CLI 运行器）。返回原始结果而不抛异常，
/// 因为 Mac 版对「退出码非 0」「超时」有各自的错误文案（见 <c>PublishStore.performPublish</c>）。
/// </summary>
public interface IReportCommandRunner
{
    /// <summary>`kanjo publish-usage --repo … [--file …] [--branch …]`，超时 120 秒。</summary>
    CliResult RunPublishUsage(string repo, string file, string branch);

    /// <summary>`kanjo report-family --url … [--member-label …]`（超时 45 秒），令牌只走环境变量。</summary>
    CliResult RunFamilyReport(string url, string? memberLabel, string token);
}

/// <summary>
/// 发布到网站 / 家庭上报的共用状态（对应 Mac 的 PublishStore / FamilyReportStore）：
/// 记录上次尝试、上次成功和最后一次结果（结果里带 `"status":"error"` 时提取 message）。
/// </summary>
public sealed class ReportActivity
{
    private readonly AppSettings _settings;
    private readonly string _attemptKey;
    private readonly string _successKey;
    private readonly string _resultKey;
    private readonly object _lock = new();

    public ReportActivity(AppSettings settings, string attemptKey, string successKey, string resultKey)
    {
        _settings = settings;
        _attemptKey = attemptKey;
        _successKey = successKey;
        _resultKey = resultKey;
        LastAttemptAt = settings.GetDate(attemptKey);
        LastSuccessAt = settings.GetDate(successKey);
        var res = settings.GetString(resultKey);
        LastResult = res;
        LastError = ExtractError(res);
    }

    public bool IsBusy { get; private set; }
    public DateTimeOffset? LastAttemptAt { get; private set; }
    public DateTimeOffset? LastSuccessAt { get; private set; }
    public string? LastResult { get; private set; }
    public string? LastError { get; private set; }

    public event Action? Changed;

    /// <summary>Mac：结果里含 `"status": "error"` 时取 message，取不到就把整段结果当错误文本。</summary>
    public static string? ExtractError(string? result)
    {
        if (string.IsNullOrEmpty(result)) return null;
        if (!result.Contains("\"status\": \"error\"", StringComparison.Ordinal) &&
            !result.Contains("\"status\":\"error\"", StringComparison.Ordinal))
        {
            return null;
        }
        try
        {
            if (JsonNode.Parse(result) is JsonObject obj &&
                obj["message"] is JsonValue value && value.TryGetValue<string>(out var message))
            {
                return message;
            }
        }
        catch (Exception)
        {
            // 不是 JSON，就原样当错误文本。
        }
        return result;
    }

    public void Begin()
    {
        lock (_lock) IsBusy = true;
        Changed?.Invoke();
    }

    public void End()
    {
        lock (_lock) IsBusy = false;
        Changed?.Invoke();
    }

    /// <summary>令牌等外部状态变化时通知 UI。</summary>
    public void Notify() => Changed?.Invoke();

    public void RecordSuccess(DateTimeOffset at, string result)
    {
        LastSuccessAt = at;
        LastAttemptAt = at;
        LastResult = result;
        LastError = null;
        _settings.SetDate(_successKey, at);
        _settings.SetDate(_attemptKey, at);
        _settings.Set(_resultKey, result);
    }

    public void RecordFailure(DateTimeOffset at, string message)
    {
        LastAttemptAt = at;
        LastError = message;
        var json = "{\"status\": \"error\", \"message\": " + JsonString(message) + "}";
        LastResult = json;
        _settings.SetDate(_attemptKey, at);
        _settings.Set(_resultKey, json);
    }

    private static string JsonString(string s)
    {
        var node = JsonValue.Create(s);
        return node?.ToJsonString() ?? "\"\"";
    }
}

/// <summary>发布 / 家庭上报共用的一次执行结果解析（Mac 两处 perform 方法的判断顺序一致）。</summary>
internal static class ReportResultReader
{
    /// <summary>stdout / stderr 的裁剪版本。</summary>
    public static (string Out, string Err) Text(CliResult result) =>
        ((result.Stdout ?? "").Trim(), (result.Stderr ?? "").Trim());

    /// <summary>退出码非 0 时的错误文案：stdout 里的 message → stderr → stdout → 退出码。</summary>
    public static string FailureMessage(CliResult result, string outText, string errText)
    {
        if (outText.Length > 0)
        {
            try
            {
                if (JsonNode.Parse(outText) is JsonObject obj &&
                    obj["message"] is JsonValue value && value.TryGetValue<string>(out var message))
                {
                    return message;
                }
            }
            catch (Exception)
            {
                // 不是 JSON：继续按 stderr / stdout 取。
            }
        }
        if (errText.Length > 0) return errText;
        if (outText.Length > 0) return outText;
        return $"Process failed with exit code {result.ExitCode}";
    }

    /// <summary>stdout 是 JSON 且有 status 字段时取出来；没有就返回 null。</summary>
    public static (string? Status, string? Message) Status(string outText)
    {
        if (outText.Length == 0) return (null, null);
        try
        {
            if (JsonNode.Parse(outText) is JsonObject obj &&
                obj["status"] is JsonValue value && value.TryGetValue<string>(out var parsed))
            {
                return (parsed, obj["message"] is JsonValue m && m.TryGetValue<string>(out var mm) ? mm : null);
            }
        }
        catch (Exception)
        {
            // 不是 JSON。
        }
        return (null, null);
    }
}

/// <summary>发布到网站（PublishStore）：按频率 + 上次结果决定要不要发，调用 `kanjo publish-usage`。</summary>
public sealed class PublishStore
{
    /// <summary>Mac 的 publish 超时。</summary>
    public static readonly TimeSpan Timeout = TimeSpan.FromSeconds(120);

    private readonly AppSettings _settings;
    private readonly Func<IReportCommandRunner?> _runner;
    private readonly Func<string?> _noNetworkReason;
    private readonly Func<DateTimeOffset> _clock;

    public PublishStore(AppSettings settings, Func<IReportCommandRunner?> runner, Func<string?> noNetworkReason,
        Func<DateTimeOffset>? clock = null)
    {
        _settings = settings;
        _runner = runner;
        _noNetworkReason = noNetworkReason;
        _clock = clock ?? (() => DateTimeOffset.UtcNow);
        Activity = new ReportActivity(settings, SettingsKeys.PublishLastAttemptAt,
            SettingsKeys.PublishLastSuccessAt, SettingsKeys.PublishLastResult);
    }

    public ReportActivity Activity { get; }

    public bool IsEnabled => _settings.Bool(SettingsKeys.PublishEnabled, SettingsDefaults.PublishEnabled);

    public PublishFrequency Frequency =>
        PublishFrequencies.Parse(_settings.GetString(SettingsKeys.PublishFrequency)) ?? PublishFrequency.Weekly;

    public string RepoPath => _settings.Str(SettingsKeys.PublishRepoPath, SettingsDefaults.PublishRepoPath);

    public string FilePath
    {
        get
        {
            var value = _settings.GetString(SettingsKeys.PublishFilePath) ?? "";
            return value.Length == 0 ? SettingsDefaults.PublishFilePath : value;
        }
    }

    public string Branch
    {
        get
        {
            var value = _settings.GetString(SettingsKeys.PublishBranch) ?? "";
            return value.Length == 0 ? SettingsDefaults.PublishBranch : value;
        }
    }

    /// <summary>每次用量刷新后调用（后台线程）：满足条件就发一次。</summary>
    public void ReportDidRefresh(UsageReport report)
    {
        if (!IsEnabled) return;
        if (string.IsNullOrWhiteSpace(RepoPath)) return;
        if (_noNetworkReason() is not null) return;

        var due = PublishSchedule.ShouldPublish(
            true, RepoPath, Frequency, Activity.LastSuccessAt, Activity.LastAttemptAt,
            _clock(), RangeEngine.TimezoneOf(report));
        if (!due) return;
        try
        {
            PublishNow();
        }
        catch (Exception)
        {
            // 结果已经记在 Activity 里。
        }
    }

    /// <summary>立刻发布一次（同步执行；UI 层放后台线程）。</summary>
    public void PublishNow()
    {
        var repo = RepoPath.Trim();
        if (repo.Length == 0) return;
        if (Activity.IsBusy) return;
        var now = _clock();
        Activity.Begin();
        try
        {
            var runner = _runner();
            if (runner is null) throw DataSourceError.LaunchFailed("Python not found.");
            var result = runner.RunPublishUsage(repo, FilePath, Branch);
            Record(result, now);
        }
        catch (Exception e)
        {
            Activity.RecordFailure(now, e.Message);
        }
        finally
        {
            Activity.End();
        }
    }

    private void Record(CliResult result, DateTimeOffset now)
    {
        var (outText, errText) = ReportResultReader.Text(result);
        if (result.TimedOut)
        {
            Activity.RecordFailure(now, $"Command timed out after {(int)Timeout.TotalSeconds}s");
            return;
        }

        if (result.ExitCode == 0)
        {
            var (status, message) = ReportResultReader.Status(outText);
            switch (status)
            {
                case "pushed" or "unchanged":
                    Activity.RecordSuccess(now, outText);
                    return;
                case "error":
                    Activity.RecordFailure(now, message ?? outText);
                    return;
                default:
                    Activity.RecordSuccess(now, outText.Length == 0 ? "{\"status\":\"pushed\"}" : outText);
                    return;
            }
        }

        Activity.RecordFailure(now, ReportResultReader.FailureMessage(result, outText, errText));
    }

    /// <summary>设置里的状态文案（和 Mac 的 publishStatusText 一致）。</summary>
    public (string Text, bool IsError, bool IsWarning) StatusText(string? localErrorMessage = null)
    {
        _ = localErrorMessage;
        if (_noNetworkReason() is { } reason)
        {
            _ = reason;
            return (L10n.Tr("settings.publish.status.no_network"), false, true);
        }
        if (Activity.IsBusy) return (L10n.Tr("settings.publish.status.in_progress"), false, false);
        if (Activity.LastError is { } err) return (L10n.TrL(null, "settings.publish.status.failed", err), true, false);
        if (Activity.LastSuccessAt is { } success)
        {
            return (L10n.TrL(null, "settings.publish.status.last_published",
                FamilyReportStatus.RelativeText(success, _clock(), null)), false, false);
        }
        return (L10n.Tr("settings.publish.status.never"), false, false);
    }
}

/// <summary>家庭用量上报（FamilyReportStore）：令牌走凭据存储，命令行只收到环境变量。</summary>
public sealed class FamilyReportStore
{
    /// <summary>Mac 的 family report 超时。</summary>
    public static readonly TimeSpan Timeout = TimeSpan.FromSeconds(45);

    private readonly AppSettings _settings;
    private readonly IFamilyTokenStorage _tokens;
    private readonly Func<IReportCommandRunner?> _runner;
    private readonly Func<string?> _noNetworkReason;
    private readonly Func<DateTimeOffset> _clock;

    public FamilyReportStore(AppSettings settings, IFamilyTokenStorage tokens,
        Func<IReportCommandRunner?> runner, Func<string?> noNetworkReason, Func<DateTimeOffset>? clock = null)
    {
        _settings = settings;
        _tokens = tokens;
        _runner = runner;
        _noNetworkReason = noNetworkReason;
        _clock = clock ?? (() => DateTimeOffset.UtcNow);
        Activity = new ReportActivity(settings, SettingsKeys.FamilyReportLastAttemptAt,
            SettingsKeys.FamilyReportLastSuccessAt, SettingsKeys.FamilyReportLastResult);
    }

    public ReportActivity Activity { get; }

    public bool HasToken => _tokens.HasToken();

    public bool IsEnabled => _settings.Bool(SettingsKeys.FamilyReportEnabled, SettingsDefaults.FamilyReportEnabled);

    public string ServerUrl => _settings.Str(SettingsKeys.FamilyReportUrl, SettingsDefaults.FamilyReportUrl);

    public string MemberLabel =>
        _settings.Str(SettingsKeys.FamilyReportMemberLabel, SettingsDefaults.FamilyReportMemberLabel);

    public bool SetToken(string token)
    {
        var ok = _tokens.SaveToken(token);
        Activity.Notify();
        return ok;
    }

    public bool ClearToken()
    {
        var ok = _tokens.DeleteToken();
        Activity.Notify();
        return ok;
    }

    /// <summary>每次用量刷新后调用：满足条件就在后台报一次（Mac 上是 async，这里同步跑在后台线程）。</summary>
    public void ReportDidRefresh(UsageReport report)
    {
        if (!IsEnabled) return;
        if (!HasToken) return;
        if (_noNetworkReason() is not null) return;
        var due = FamilyReportSchedule.ShouldReport(
            true, HasToken, ServerUrl, Activity.LastSuccessAt, Activity.LastAttemptAt,
            _clock(), false);
        if (!due) return;
        try
        {
            ReportNow();
        }
        catch (Exception)
        {
            // 结果已经记在 Activity 里。
        }
    }

    /// <summary>立刻上报（同步；UI 层放后台线程）。</summary>
    public void ReportNow()
    {
        if (Activity.IsBusy) return;
        var token = _tokens.LoadToken();
        if (string.IsNullOrWhiteSpace(token))
        {
            Activity.RecordFailure(_clock(), "Token not configured");
            return;
        }
        var cleanToken = token.Trim();
        var url = ServerUrl.Trim();
        if (!FamilyReportSchedule.IsValidUrl(url)) return;

        var now = _clock();
        Activity.Begin();
        try
        {
            var runner = _runner();
            if (runner is null) throw DataSourceError.LaunchFailed("Python not found.");
            var result = runner.RunFamilyReport(url, MemberLabel, cleanToken);
            Record(result, now);
        }
        catch (Exception e)
        {
            Activity.RecordFailure(now, e.Message);
        }
        finally
        {
            Activity.End();
        }
    }

    private void Record(CliResult result, DateTimeOffset now)
    {
        var (outText, errText) = ReportResultReader.Text(result);
        if (result.TimedOut)
        {
            Activity.RecordFailure(now, $"Command timed out after {(int)Timeout.TotalSeconds}s");
            return;
        }

        if (result.ExitCode == 0)
        {
            var (status, message) = ReportResultReader.Status(outText);
            switch (status)
            {
                case "sent":
                    Activity.RecordSuccess(now, outText);
                    return;
                case "error":
                    Activity.RecordFailure(now, message ?? outText);
                    return;
                default:
                    Activity.RecordSuccess(now, outText.Length == 0 ? "{\"status\":\"sent\"}" : outText);
                    return;
            }
        }

        Activity.RecordFailure(now, ReportResultReader.FailureMessage(result, outText, errText));
    }

    /// <summary>状态文案（SettingsView.familyReportStatusText）。</summary>
    public (string Text, FamilyReportStatusStateKind Kind) StatusText()
    {
        var noNetwork = _noNetworkReason() is not null;
        var state = FamilyReportStatus.State(ServerUrl, HasToken, Activity.IsBusy,
            Activity.LastError, Activity.LastSuccessAt, noNetwork);
        return (FamilyReportStatus.Text(ServerUrl, HasToken, Activity.IsBusy,
            Activity.LastError, Activity.LastSuccessAt, noNetwork, _clock(), null), state.Kind);
    }

    /// <summary>是否满足「Report now」的条件（有令牌、不在上报中、URL 合法）。</summary>
    public bool CanReportNow =>
        HasToken && !Activity.IsBusy && FamilyReportSchedule.IsValidUrl(ServerUrl.Trim());
}
