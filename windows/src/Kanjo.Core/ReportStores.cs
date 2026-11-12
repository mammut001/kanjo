using System.Globalization;
using System.Text.Json.Nodes;

namespace Kanjo.Core;

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

/// <summary>发布到网站（PublishStore）：按频率 + 上次结果决定要不要发，调用 `kanjo publish-usage`。</summary>
public sealed class PublishStore
{
    private readonly AppSettings _settings;
    private readonly Func<CliRunner?> _runner;
    private readonly Func<string?> _noNetworkReason;

    public PublishStore(AppSettings settings, Func<CliRunner?> runner, Func<string?> noNetworkReason)
    {
        _settings = settings;
        _runner = runner;
        _noNetworkReason = noNetworkReason;
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
            DateTimeOffset.UtcNow, RangeEngine.TimezoneOf(report));
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
        var now = DateTimeOffset.UtcNow;
        Activity.Begin();
        try
        {
            var runner = _runner();
            if (runner is null) throw DataSourceError.LaunchFailed("Python not found.");
            var output = runner.PublishUsage(repo, FilePath, Branch);
            Record(output, now);
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

    private void Record(string output, DateTimeOffset now)
    {
        var trimmed = output.Trim();
        // 和 Mac 一样：stdout 里有 status 就按 status 判定，否则视为成功。
        if (trimmed.Length > 0)
        {
            try
            {
                if (JsonNode.Parse(trimmed) is JsonObject obj &&
                    obj["status"] is JsonValue value && value.TryGetValue<string>(out var status))
                {
                    if (status == "error")
                    {
                        var message = obj["message"] is JsonValue m && m.TryGetValue<string>(out var mm)
                            ? mm
                            : trimmed;
                        Activity.RecordFailure(now, message);
                        return;
                    }
                    Activity.RecordSuccess(now, trimmed);
                    return;
                }
            }
            catch (Exception)
            {
                // 不是 JSON，按成功处理。
            }
        }
        Activity.RecordSuccess(now, trimmed.Length == 0 ? "{\"status\":\"sent\"}" : trimmed);
    }

    /// <summary>设置里的状态文案（和 Mac 的 publishStatusText 一致）。</summary>
    public (string Text, bool IsError, bool IsWarning) StatusText(string? localErrorMessage = null)
    {
        if (_noNetworkReason() is { } reason)
        {
            return (L10n.Tr("settings.publish.status.no_network"), false, true);
        }
        if (Activity.IsBusy) return (L10n.Tr("settings.publish.status.in_progress"), false, false);
        if (Activity.LastError is { } err) return (L10n.TrL(null, "settings.publish.status.failed", err), true, false);
        if (Activity.LastSuccessAt is { } success)
        {
            return (L10n.TrL(null, "settings.publish.status.last_published",
                FamilyReportStatus.RelativeText(success, DateTimeOffset.UtcNow, null)), false, false);
        }
        return (L10n.Tr("settings.publish.status.never"), false, false);
    }
}

/// <summary>家庭用量上报（FamilyReportStore）：令牌走凭据存储，命令行只收到环境变量。</summary>
public sealed class FamilyReportStore
{
    private readonly AppSettings _settings;
    private readonly IFamilyTokenStorage _tokens;
    private readonly Func<CliRunner?> _runner;
    private readonly Func<string?> _noNetworkReason;

    public FamilyReportStore(AppSettings settings, IFamilyTokenStorage tokens,
        Func<CliRunner?> runner, Func<string?> noNetworkReason)
    {
        _settings = settings;
        _tokens = tokens;
        _runner = runner;
        _noNetworkReason = noNetworkReason;
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
            DateTimeOffset.UtcNow, false);
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
            Activity.RecordFailure(DateTimeOffset.UtcNow, "Token not configured");
            return;
        }
        var url = ServerUrl.Trim();
        if (!FamilyReportSchedule.IsValidUrl(url)) return;

        var now = DateTimeOffset.UtcNow;
        Activity.Begin();
        try
        {
            var runner = _runner();
            if (runner is null) throw DataSourceError.LaunchFailed("Python not found.");
            var output = runner.ReportFamily(url, MemberLabel, token);
            Record(output, now);
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

    private void Record(string output, DateTimeOffset now)
    {
        var trimmed = output.Trim();
        if (trimmed.Length > 0)
        {
            try
            {
                if (JsonNode.Parse(trimmed) is JsonObject obj &&
                    obj["status"] is JsonValue value && value.TryGetValue<string>(out var status))
                {
                    if (status == "sent")
                    {
                        Activity.RecordSuccess(now, trimmed);
                        return;
                    }
                    if (status == "error")
                    {
                        var message = obj["message"] is JsonValue m && m.TryGetValue<string>(out var mm)
                            ? mm
                            : trimmed;
                        Activity.RecordFailure(now, message);
                        return;
                    }
                }
            }
            catch (Exception)
            {
                // 不是 JSON，按成功处理。
            }
        }
        Activity.RecordSuccess(now, trimmed.Length == 0 ? "{\"status\":\"sent\"}" : trimmed);
    }

    /// <summary>状态文案（SettingsView.familyReportStatusText）。</summary>
    public (string Text, FamilyReportStatusStateKind Kind) StatusText()
    {
        var state = FamilyReportStatus.State(ServerUrl, HasToken, Activity.IsBusy,
            Activity.LastError, Activity.LastSuccessAt, _noNetworkReason() is not null);
        return (FamilyReportStatus.Text(ServerUrl, HasToken, Activity.IsBusy,
            Activity.LastError, Activity.LastSuccessAt, _noNetworkReason() is not null,
            DateTimeOffset.UtcNow, null), state.Kind);
    }

    /// <summary>是否满足「Report now」的条件（有令牌、不在上报中、URL 合法）。</summary>
    public bool CanReportNow =>
        HasToken && !Activity.IsBusy && FamilyReportSchedule.IsValidUrl(ServerUrl.Trim());
}
