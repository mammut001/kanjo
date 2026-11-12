namespace Kanjo.Core;

/// <summary>
/// 从导出命令推出其它子命令。只替换最后一个独立的 `export`，
/// 这样前面的 `export PATH=...` 不会被改掉（Windows 上通常是 `python.exe -m kanjo export`）。
/// </summary>
public static class DiskCommand
{
    public static string Report(string cliCommand, bool rescan = false, TimeSpan? maxAge = null)
    {
        string flag;
        if (rescan)
        {
            flag = "disk --json --rescan";
        }
        else if (maxAge is { } age)
        {
            flag = $"disk --json --max-age {(int)age.TotalSeconds}";
        }
        else
        {
            flag = "disk --json";
        }
        return ReplacingExport(cliCommand, flag).Trim();
    }

    /// <summary>`disk clean &lt;id&gt;... [--older-than Nd] --dry-run|--yes`</summary>
    public static string Clean(string cliCommand, IReadOnlyList<string> ids, string? olderThan, bool confirmed)
    {
        var parts = new List<string> { ReplacingExport(cliCommand, "disk clean").Trim() };
        parts.AddRange(ids.Select(ShellWord));
        if (!string.IsNullOrEmpty(olderThan))
        {
            parts.Add("--older-than");
            parts.Add(ShellWord(olderThan));
        }
        parts.Add(confirmed ? "--yes" : "--dry-run");
        return string.Join(" ", parts);
    }

    internal static string ReplacingExport(string command, string replacement)
    {
        var range = LastExportToken(command);
        if (range is not { } r) return command;
        return command[..r.Start] + replacement + command[(r.Start + r.Length)..];
    }

    /// <summary>从后往前找作为独立单词的 `export`（前后不是字母、数字、`_` 或 `-`）。</summary>
    internal static (int Start, int Length)? LastExportToken(string command)
    {
        var searchEnd = command.Length;
        while (searchEnd > 0)
        {
            var found = command.LastIndexOf("export", searchEnd - 1, StringComparison.Ordinal);
            if (found < 0) return null;
            var beforeOk = found == 0 || !IsTokenBody(command[found - 1]);
            var afterIndex = found + "export".Length;
            var afterOk = afterIndex >= command.Length || !IsTokenBody(command[afterIndex]);
            if (beforeOk && afterOk) return (found, "export".Length);
            searchEnd = found;
        }
        return null;
    }

    private static bool IsTokenBody(char c) => char.IsLetterOrDigit(c) || c == '_' || c == '-';

    /// <summary>安全字符原样留下，其余用引号包起来（参数仍然按列表传给进程，这里只为日志可读）。</summary>
    internal static string ShellWord(string raw)
    {
        const string ok = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_:./\\";
        if (raw.Length > 0 && raw.All(c => ok.Contains(c, StringComparison.Ordinal))) return raw;
        return "'" + raw.Replace("'", "'\\''", StringComparison.Ordinal) + "'";
    }
}

/// <summary>续费日 / 订阅字段只交给 CLI 写配置（`kanjo config set|unset`）。</summary>
public static class ConfigCommand
{
    private const string AllowedAgentChars =
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-";

    private static void ValidateAgent(string agent)
    {
        if (string.IsNullOrEmpty(agent) || !agent.All(c => AllowedAgentChars.Contains(c, StringComparison.Ordinal)))
        {
            throw DataSourceError.LaunchFailed($"Invalid subscription agent: {agent}");
        }
    }

    public static IReadOnlyList<string> Arguments(string agent, int? anchorDay)
    {
        ValidateAgent(agent);
        var key = $"subscriptions.{agent}.anchor_day";
        if (anchorDay is not { } day) return ["config", "unset", key];
        if (day is < 1 or > 28) throw DataSourceError.LaunchFailed("Renewal day must be between 1 and 28.");
        return ["config", "set", key, day.ToString(System.Globalization.CultureInfo.InvariantCulture)];
    }

    public static IReadOnlyList<string> FieldArguments(string agent, string field, string? value)
    {
        ValidateAgent(agent);
        if (field is not ("anchor_day" or "plan" or "monthly_price_usd"))
        {
            throw DataSourceError.LaunchFailed($"Invalid subscription field: {field}");
        }
        var key = $"subscriptions.{agent}.{field}";
        var trimmed = value?.Trim();
        return string.IsNullOrEmpty(trimmed) ? ["config", "unset", key] : ["config", "set", key, trimmed];
    }

    public static IReadOnlyList<string> QuotaResetArguments(string agent, string? weeklyReset)
    {
        if (string.IsNullOrEmpty(agent) || !agent.All(c => AllowedAgentChars.Contains(c, StringComparison.Ordinal)))
        {
            throw DataSourceError.LaunchFailed($"Invalid agent: {agent}");
        }
        var key = $"quota_windows.{agent}.weekly_reset";
        var trimmed = weeklyReset?.Trim();
        return string.IsNullOrEmpty(trimmed) ? ["config", "unset", key] : ["config", "set", key, trimmed];
    }

    public static IReadOnlyList<string> FamilySinceArguments(string? since)
    {
        const string key = "family.since";
        var trimmed = since?.Trim();
        return string.IsNullOrEmpty(trimmed) ? ["config", "unset", key] : ["config", "set", key, trimmed];
    }

    public static IReadOnlyList<string> FamilyAgentsArguments(string? agents)
    {
        const string key = "family.agents";
        var trimmed = agents?.Trim();
        return string.IsNullOrEmpty(trimmed) ? ["config", "unset", key] : ["config", "set", key, trimmed];
    }

    public static IReadOnlyList<string> PlansArguments() => ["config", "plans", "--json"];

    /// <summary>和 DiskCommand 一样只替换最后一个 export，保留前面的前缀。</summary>
    public static string Command(string cliCommand, IReadOnlyList<string> arguments)
    {
        var trimmed = cliCommand.Trim();
        var token = DiskCommand.LastExportToken(trimmed);
        if (token is not { } t || t.Start + t.Length != trimmed.Length || t.Start == 0 ||
            !char.IsWhiteSpace(trimmed[t.Start - 1]))
        {
            throw DataSourceError.LaunchFailed("Editing subscriptions needs a CLI command ending in export.");
        }
        var prefix = trimmed[..t.Start];
        return prefix + string.Join(" ", arguments.Select(DiskCommand.ShellWord));
    }
}

/// <summary>`publish-usage` 命令行（由导出命令推导）。</summary>
public static class PublishCommand
{
    public static string Command(string cliCommand, string repo, string file, string branch)
    {
        var parts = new List<string> { DiskCommand.ReplacingExport(cliCommand, "publish-usage").Trim() };
        parts.Add("--repo");
        parts.Add(DiskCommand.ShellWord(repo));
        var cleanFile = file.Trim();
        if (cleanFile.Length > 0)
        {
            parts.Add("--file");
            parts.Add(DiskCommand.ShellWord(cleanFile));
        }
        var cleanBranch = branch.Trim();
        if (cleanBranch.Length > 0)
        {
            parts.Add("--branch");
            parts.Add(DiskCommand.ShellWord(cleanBranch));
        }
        return string.Join(" ", parts);
    }
}

/// <summary>`report-family` 命令行（由导出命令推导）。令牌永远不会出现在命令参数里。</summary>
public static class FamilyReportCommand
{
    public static string Command(string cliCommand, string url, string? memberLabel)
    {
        var parts = new List<string> { DiskCommand.ReplacingExport(cliCommand, "report-family").Trim() };
        parts.Add("--url");
        parts.Add(DiskCommand.ShellWord(url.Trim()));
        var label = memberLabel?.Trim();
        if (!string.IsNullOrEmpty(label))
        {
            parts.Add("--member-label");
            parts.Add(DiskCommand.ShellWord(label));
        }
        return string.Join(" ", parts);
    }
}
