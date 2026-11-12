using System.Text.Json;

namespace Kanjo.Core;

/// <summary>严格对应 CONTRACT.md 的数据模型。契约里标注「可为 null」的字段才是可空，其余缺失即解码失败。</summary>
public sealed record ReportConfig(double DominantThreshold, bool? NoNetwork, FamilyConfig? Family)
{
    public static ReportConfig Decode(JsonElement e, string path) => new(
        J.Number(e, "dominant_threshold", path),
        J.BoolOrNull(e, "no_network", path),
        J.Optional(e, "family") is { } f ? FamilyConfig.Decode(f, J.Child(path, "family")) : null);
}

public sealed record FamilyConfig(string? Since, RoList<string>? Agents)
{
    public static FamilyConfig Decode(JsonElement e, string path) => new(
        J.StringOrNull(e, "since", path),
        J.ArrayOrNull(e, "agents", path) is { } a
            ? new RoList<string>(J.List(a, J.Child(path, "agents"), (i, p) => J.ToString(i, p)))
            : null);
}

/// <summary>额度附加窗口（如 Antigravity 中的第三方模型组 Claude / GPT 窗口）。</summary>
public sealed record ExtraQuotaWindow(
    string Id,
    string Title,
    double? UsedPercent,
    string? ResetsAt,
    int? WindowHours)
{
    public static ExtraQuotaWindow Decode(JsonElement e, string path) => new(
        J.String(e, "id", path),
        J.String(e, "title", path),
        J.NumberOrNull(e, "used_percent", path),
        J.StringOrNull(e, "resets_at", path),
        J.IntOrNull(e, "window_hours", path));
}

/// <summary>一个 agent 的额度窗口（契约第 2 节 quota_windows）。</summary>
public sealed record QuotaWindow(
    string WeeklyResetsAt,
    int WeeklyWindowHours,
    double? WeeklyUsedPercent,
    string? FiveHourResetsAt,
    int? FiveHourWindowHours,
    double? FiveHourUsedPercent,
    string Source,
    RoList<ExtraQuotaWindow>? ExtraWindows)
{
    public static QuotaWindow Decode(JsonElement e, string path) => new(
        J.String(e, "weekly_resets_at", path),
        J.IntOrNull(e, "weekly_window_hours", path) ?? 168,
        J.NumberOrNull(e, "weekly_used_percent", path),
        J.StringOrNull(e, "five_hour_resets_at", path),
        J.IntOrNull(e, "five_hour_window_hours", path),
        J.NumberOrNull(e, "five_hour_used_percent", path),
        J.StringOrNull(e, "source", path) ?? "tokei",
        J.ArrayOrNull(e, "extra_windows", path) is { } x
            ? new RoList<ExtraQuotaWindow>(J.List(x, J.Child(path, "extra_windows"), ExtraQuotaWindow.Decode))
            : null);
}

/// <summary>检测到的账号信息（邮箱，以及可选的显示名／组织名）。</summary>
public sealed record SubscriptionAccount(string Email, string? Name)
{
    public static SubscriptionAccount Decode(JsonElement e, string path) => new(
        J.String(e, "email", path),
        J.StringOrNull(e, "name", path));
}

/// <summary>一个 agent 的订阅档位（契约第 2 节 subscriptions）。月费未知时 MonthlyPriceUsd 为 null。</summary>
public sealed record Subscription(
    string Plan,
    string PlanLabel,
    double? MonthlyPriceUsd,
    string CycleStart,
    string CycleEnd,
    int? AnchorDay,
    string CycleSource,
    bool ExtraUsageEnabled,
    string Source,
    SubscriptionAccount? Account)
{
    public static Subscription Decode(JsonElement e, string path) => new(
        J.String(e, "plan", path),
        J.String(e, "plan_label", path),
        J.NumberOrNull(e, "monthly_price_usd", path),
        J.String(e, "cycle_start", path),
        J.String(e, "cycle_end", path),
        J.IntOrNull(e, "anchor_day", path),
        J.StringOrNull(e, "cycle_source", path) ?? "subscription_cycle",
        J.BoolOrNull(e, "extra_usage_enabled", path) ?? false,
        J.StringOrNull(e, "source", path) ?? "detected",
        J.Optional(e, "account") is { } a ? SubscriptionAccount.Decode(a, J.Child(path, "account")) : null);
}

public sealed record AgentCost(string Agent, string Label, double Cost, Tokens Tokens, int Sessions)
{
    public static AgentCost Decode(JsonElement e, string path) => new(
        J.String(e, "agent", path),
        J.String(e, "label", path),
        J.Number(e, "cost", path),
        Tokens.Decode(J.RequiredObject(e, "tokens", path), J.Child(path, "tokens")),
        J.Int(e, "sessions", path));
}

public sealed record ModelCost(string Model, string Agent, double Cost, Tokens Tokens, bool Estimated)
{
    public string Id => Agent + "/" + Model;

    public static ModelCost Decode(JsonElement e, string path) => new(
        J.String(e, "model", path),
        J.String(e, "agent", path),
        J.Number(e, "cost", path),
        Tokens.Decode(J.RequiredObject(e, "tokens", path), J.Child(path, "tokens")),
        J.BoolOrNull(e, "estimated", path) ?? false);
}

/// <summary>某一天的用量。<see cref="ByAgent"/> / <see cref="ByAgentTokens"/> 是旧数据里没有的字段。</summary>
public sealed record DayCost(
    string Day,
    double Cost,
    long Tokens,
    RoDict<double>? ByAgent,
    RoDict<long>? ByAgentTokens)
{
    public string Id => Day;

    public static DayCost Decode(JsonElement e, string path) => new(
        J.String(e, "day", path),
        J.Number(e, "cost", path),
        J.LongOrNull(e, "tokens", path) ?? 0,
        J.Optional(e, "by_agent") is { } a ? new RoDict<double>(LongDoubleDict(a, J.Child(path, "by_agent"))) : null,
        J.Optional(e, "by_agent_tokens") is { } t
            ? new RoDict<long>(LongIntDict(t, J.Child(path, "by_agent_tokens")))
            : null);

    private static Dictionary<string, double> LongDoubleDict(JsonElement e, string path) =>
        J.DoubleDict(e, path);

    private static Dictionary<string, long> LongIntDict(JsonElement e, string path)
    {
        var result = new Dictionary<string, long>(StringComparer.Ordinal);
        foreach (var (key, value) in J.Properties(e, path))
        {
            result[key] = (long)J.ToInt(value, J.Child(path, key));
        }
        return result;
    }
}

public sealed record BranchCost(string Branch, double Cost, int Sessions)
{
    public string Id => Branch;

    public static BranchCost Decode(JsonElement e, string path) => new(
        J.String(e, "branch", path),
        J.Number(e, "cost", path),
        J.Int(e, "sessions", path));
}

public sealed record Session(
    string Id,
    string Agent,
    string Label,
    string Started,
    string Ended,
    string? Cwd,
    string? Branch,
    RoList<string> Models,
    double Cost,
    Tokens Tokens,
    double Share,
    string Attribution,
    int Subagents,
    string? Title,
    RoList<DayCost>? ByDay)
{
    public DateTimeOffset? StartedDate => ReportDates.ParseTimestamp(Started);
    public DateTimeOffset? EndedDate => ReportDates.ParseTimestamp(Ended);

    /// <summary>手机快照的精简会话没有 id / label / share / attribution / subagents / by_day，这里给兜底值。</summary>
    public static Session Decode(JsonElement e, string path)
    {
        var agent = J.String(e, "agent", path);
        var started = J.String(e, "started", path);
        return new Session(
            J.StringOrNull(e, "id", path) ?? $"{agent}@{started}",
            agent,
            J.StringOrNull(e, "label", path) ?? AgentColors.Label(agent),
            started,
            J.String(e, "ended", path),
            J.StringOrNull(e, "cwd", path),
            J.StringOrNull(e, "branch", path),
            J.ArrayOrNull(e, "models", path) is { } m
                ? new RoList<string>(J.List(m, J.Child(path, "models"), (i, p) => J.ToString(i, p)))
                : [],
            J.Number(e, "cost", path),
            Tokens.Decode(J.RequiredObject(e, "tokens", path), J.Child(path, "tokens")),
            J.NumberOrNull(e, "share", path) ?? 1,
            J.StringOrNull(e, "attribution", path) ?? "none",
            J.IntOrNull(e, "subagents", path) ?? 0,
            J.StringOrNull(e, "title", path),
            J.ArrayOrNull(e, "by_day", path) is { } d
                ? new RoList<DayCost>(J.List(d, J.Child(path, "by_day"), DayCost.Decode))
                : null);
    }
}

public sealed record Project(
    string Id,
    string Name,
    string? Remote,
    RoList<string> Paths,
    bool PathMissing,
    double Cost,
    Tokens Tokens,
    int Sessions,
    string? FirstActive,
    string? LastActive,
    RoList<AgentCost> ByAgent,
    RoList<ModelCost> ByModel,
    RoList<DayCost> ByDay,
    RoList<BranchCost> ByBranch,
    RoList<Session> SessionsDetail)
{
    public static Project Decode(JsonElement e, string path) => new(
        J.String(e, "id", path),
        J.String(e, "name", path),
        J.StringOrNull(e, "remote", path),
        J.ArrayOrNull(e, "paths", path) is { } paths
            ? new RoList<string>(J.List(paths, J.Child(path, "paths"), (i, p) => J.ToString(i, p)))
            : [],
        J.BoolOrNull(e, "path_missing", path) ?? false,
        J.Number(e, "cost", path),
        Tokens.Decode(J.RequiredObject(e, "tokens", path), J.Child(path, "tokens")),
        J.Int(e, "sessions", path),
        J.StringOrNull(e, "first_active", path),
        J.StringOrNull(e, "last_active", path),
        J.List(J.Array(e, "by_agent", path), J.Child(path, "by_agent"), AgentCost.Decode),
        J.List(J.Array(e, "by_model", path), J.Child(path, "by_model"), ModelCost.Decode),
        J.List(J.Array(e, "by_day", path), J.Child(path, "by_day"), DayCost.Decode),
        J.List(J.ArrayOrNull(e, "by_branch", path), J.Child(path, "by_branch"), BranchCost.Decode),
        J.List(J.ArrayOrNull(e, "sessions_detail", path), J.Child(path, "sessions_detail"), Session.Decode));
}

public sealed record UsageReport(
    int SchemaVersion,
    string GeneratedAt,
    string? GeneratedBy,
    string? Timezone,
    string Currency,
    string CostNote,
    ReportConfig Config,
    RoDict<QuotaWindow>? QuotaWindows,
    RoDict<Subscription>? Subscriptions,
    Aggregate Totals,
    RoList<Project> Projects,
    Buckets Buckets)
{
    /// <summary>schema_version 高于本 UI 支持的版本：显示警告，继续渲染。</summary>
    public bool IsNewerSchema => SchemaVersion > Contract.SupportedSchemaVersion;

    /// <summary>报告里所有 agent 的显示名（agent key → label）。</summary>
    public Dictionary<string, string> AgentLabels()
    {
        var labels = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var p in Projects)
        {
            foreach (var a in p.ByAgent) labels[a.Agent] = a.Label;
        }
        return labels;
    }

    /// <summary>
    /// 格式化后的 cost_note 文本。若为空或纯空白返回 null；若为默认英文字符串则返回本地化文案；否则返回原文。
    /// </summary>
    public string? CostNoteDisplayText
    {
        get
        {
            var trimmed = CostNote.Trim();
            if (trimmed.Length == 0) return null;
            if (trimmed == ContractCostNote) return L10n.Tr("common.cost_note_default");
            return trimmed;
        }
    }

    public const string ContractCostNote =
        "API-equivalent cost estimated from public API prices. Not actual subscription spend.";

    public static UsageReport Decode(JsonElement e, string path = "")
    {
        var config = J.Optional(e, "config") is { } c
            ? ReportConfig.Decode(c, J.Child(path, "config"))
            : new ReportConfig(0.8, null, null);
        return new UsageReport(
            J.Int(e, "schema_version", path),
            J.String(e, "generated_at", path),
            J.StringOrNull(e, "generated_by", path),
            J.StringOrNull(e, "timezone", path),
            J.String(e, "currency", path),
            J.String(e, "cost_note", path),
            config,
            DecodeWindows(e, path),
            DecodeSubscriptions(e, path),
            Aggregate.Decode(J.RequiredObject(e, "totals", path), J.Child(path, "totals")),
            J.List(J.Array(e, "projects", path), J.Child(path, "projects"), Project.Decode),
            Buckets.Decode(J.RequiredObject(e, "buckets", path), J.Child(path, "buckets")));
    }

    private static RoDict<QuotaWindow>? DecodeWindows(JsonElement e, string path)
    {
        if (J.Optional(e, "quota_windows") is not { } q) return null;
        return new RoDict<QuotaWindow>(J.Dict(q, J.Child(path, "quota_windows"), QuotaWindow.Decode));
    }

    private static RoDict<Subscription>? DecodeSubscriptions(JsonElement e, string path)
    {
        if (J.Optional(e, "subscriptions") is not { } s) return null;
        return new RoDict<Subscription>(J.Dict(s, J.Child(path, "subscriptions"), Subscription.Decode));
    }
}
