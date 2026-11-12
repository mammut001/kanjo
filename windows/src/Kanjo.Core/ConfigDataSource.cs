namespace Kanjo.Core;

/// <summary>
/// 配置写入：所有订阅 / 额度 / 家庭范围的改动都交给 CLI（`kanjo config set|unset`），
/// 参数构造在 <see cref="ConfigCommand"/> 里（和 Mac 版 ConfigCommand.swift 逐条对应）。
/// 缓存已知档位（`config plans --json`），失败时回退到内置档位表。
/// </summary>
public sealed class ConfigDataSource
{
    private readonly object _lock = new();
    private IReadOnlyDictionary<string, IReadOnlyList<KnownPlan>>? _cachedPlans;
    private bool _attempted;

    public Func<CliRunner> Runner { get; }

    public ConfigDataSource(Func<CliRunner> runner) => Runner = runner;

    public IReadOnlyDictionary<string, IReadOnlyList<KnownPlan>>? CachedPlans
    {
        get { lock (_lock) return _cachedPlans; }
    }

    /// <summary>读取各 agent 的已知档位；失败或空结果回退到内置表。结果缓存，只尝试一次。</summary>
    public IReadOnlyDictionary<string, IReadOnlyList<KnownPlan>> KnownPlans()
    {
        lock (_lock)
        {
            if (_attempted) return _cachedPlans ?? KnownPlan.FallbackPlans;
            _attempted = true;
        }
        var plans = KnownPlan.FallbackPlans;
        try
        {
            plans = Runner().KnownPlans();
        }
        catch (Exception)
        {
            // 用内置表。
        }
        lock (_lock) _cachedPlans = plans;
        return plans;
    }

    public void ResetCache()
    {
        lock (_lock)
        {
            _cachedPlans = null;
            _attempted = false;
        }
    }

    private void Execute(IReadOnlyList<string> arguments) => Runner().RunChecked(arguments, "config output");

    public void SetAnchorDay(string agent, int? day) =>
        Execute(ConfigCommand.Arguments(agent, day));

    /// <summary>和 ConfigDataSource.setSubscription 一样：价格、档位按需写入，未给价格时清掉覆盖，最后写续费日。</summary>
    public void SetSubscription(string agent, string? plan, double? monthlyPriceUsd, int? anchorDay)
    {
        foreach (var args in SubscriptionArguments(agent, plan, monthlyPriceUsd, anchorDay)) Execute(args);
    }

    public static IReadOnlyList<IReadOnlyList<string>> SubscriptionArguments(
        string agent, string? plan, double? monthlyPriceUsd, int? anchorDay)
    {
        var list = new List<IReadOnlyList<string>>();
        if (monthlyPriceUsd is { } price)
        {
            var text = price == Math.Round(price)
                ? ((long)Math.Round(price)).ToString(System.Globalization.CultureInfo.InvariantCulture)
                : price.ToString(System.Globalization.CultureInfo.InvariantCulture);
            list.Add(ConfigCommand.FieldArguments(agent, "monthly_price_usd", text));
        }
        if (!string.IsNullOrWhiteSpace(plan))
        {
            list.Add(ConfigCommand.FieldArguments(agent, "plan", plan));
        }
        if (monthlyPriceUsd is null)
        {
            list.Add(ConfigCommand.FieldArguments(agent, "monthly_price_usd", null));
        }
        if (anchorDay is { } day)
        {
            list.Add(ConfigCommand.Arguments(agent, day));
        }
        return list;
    }

    public void RemoveSubscription(string agent)
    {
        Execute(ConfigCommand.FieldArguments(agent, "plan", null));
        Execute(ConfigCommand.FieldArguments(agent, "monthly_price_usd", null));
        Execute(ConfigCommand.Arguments(agent, null));
    }

    public void SetWeeklyReset(string agent, string? reset) =>
        Execute(ConfigCommand.QuotaResetArguments(agent, reset));

    public void SetFamilySince(string? since) =>
        Execute(ConfigCommand.FamilySinceArguments(since));

    public void SetFamilyAgents(string? agents) =>
        Execute(ConfigCommand.FamilyAgentsArguments(agents));
}

/// <summary>
/// 设置页的订阅 / 额度 agent 列表（对应 SettingsView.subscriptionAgentList）：
/// 先按报告里的花费顺序，再补只在订阅表里的，再补报告里出现过的，最后是已知 agent 的固定顺序。
/// </summary>
public static class SettingsAgentList
{
    /// <summary>已知 agent 的固定顺序（和 Swift 里的 knownOrder 一字不差）。</summary>
    public static readonly IReadOnlyList<string> KnownOrder =
    [
        "claude", "codex", "antigravity", "grok", "copilot", "minimax", "qwen", "commandcode", "opencode", "pi",
        "workbuddy", "workbuddy_ai", "grok_bot", "qoderwork", "qodercli", "qodercli_cn", "zcode", "kimicode", "musecode",
        "codebuddy", "qoder_ide", "hermes", "openclaw", "devin", "mimocode", "prime_agent", "omp", "deepseek_harness", "qwenwork",
    ];

    public static List<string> SubscriptionAgents(UsageReport report, string? editingAgent = null)
    {
        var subs = report.Subscriptions?.Keys.ToHashSet(StringComparer.Ordinal)
                   ?? new HashSet<string>(StringComparer.Ordinal);
        var order = RangeCaptionBuilder.AgentOrder(report);
        var list = new List<string>();
        var seen = new HashSet<string>(StringComparer.Ordinal);

        foreach (var agent in order)
        {
            if (subs.Contains(agent) && seen.Add(agent)) list.Add(agent);
        }
        foreach (var agent in subs.OrderBy(a => a, StringComparer.Ordinal))
        {
            if (seen.Add(agent)) list.Add(agent);
        }
        foreach (var agent in order)
        {
            if (seen.Add(agent)) list.Add(agent);
        }
        foreach (var agent in KnownOrder)
        {
            if (seen.Add(agent)) list.Add(agent);
        }
        if (editingAgent is { Length: > 0 } editing && seen.Add(editing)) list.Add(editing);
        return list;
    }

    /// <summary>额度重置一节只列有订阅或有额度窗口的 agent。</summary>
    public static List<string> QuotaAgents(UsageReport report) =>
        SubscriptionAgents(report)
            .Where(a => report.Subscriptions?.ContainsKey(a) == true || report.QuotaWindows?.ContainsKey(a) == true)
            .ToList();
}

/// <summary>家庭上报的当前范围描述（SettingsView.currentFamilyScopeText）。</summary>
public static class FamilyScopeText
{
    public static string Make(FamilyConfig? config, string? language = null)
    {
        var lang = language ?? L10n.CurrentLanguage;
        var agents = config?.Agents?.ToList() ?? ["antigravity"];
        var isAll = agents.Count == 1 ? agents[0] == "all" : agents.Contains("all");
        var agentsText = isAll
            ? L10n.TrL(lang, "settings.family.scope.agents_all")
            : L10n.TrL(lang, "settings.family.scope.agents_antigravity");
        var since = config?.Since;
        if (!string.IsNullOrEmpty(since))
        {
            return $"{agentsText} · {L10n.TrL(lang, "settings.family.scope.since_date", since)}";
        }
        return agentsText;
    }
}
