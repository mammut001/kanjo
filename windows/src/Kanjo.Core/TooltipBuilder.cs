namespace Kanjo.Core;

/// <summary>悬停提示文本构建器：纯逻辑，保证所有带颜色的图块悬停时展示一致的金额与 token 信息。</summary>
public static class TooltipBuilder
{
    /// <summary>统一金额与 token 格式化，如 "$12.34 · 1.2亿 token"。</summary>
    public static string CostAndTokens(double cost, long tokens, string currency = "USD", string? language = null) =>
        Fmt.CostAndTokens(cost, tokens, currency, language);

    /// <summary>单个 agent 格式化行，如 "● Claude Code  $10.00 · 9000万 token"。</summary>
    public static string AgentLine(string label, double cost, long tokens, string currency = "USD", string? language = null)
    {
        var formatted = CostAndTokens(cost, tokens, currency, language);
        return $"● {label}  {formatted}";
    }

    /// <summary>按花费降序排列的 per-agent 行（花费相同按标签字母排序）。</summary>
    public static IReadOnlyList<string> AgentLines(
        IEnumerable<(string Label, double Cost, long Tokens)> items,
        string currency = "USD",
        string? language = null)
    {
        return items
            .Where(i => i.Cost > 0 || i.Tokens > 0)
            .OrderByDescending(i => i.Cost)
            .ThenBy(i => i.Label, StringComparer.Ordinal)
            .Select(i => AgentLine(i.Label, i.Cost, i.Tokens, currency, language))
            .ToList();
    }

    public static IReadOnlyList<string> AgentLines(
        IReadOnlyList<AgentCost> agents, string currency = "USD", string? language = null) =>
        AgentLines(agents.Select(a => (a.Label, a.Cost, a.Tokens.Total)), currency, language);

    public static IReadOnlyList<string> AgentLines(
        IReadOnlyDictionary<string, double>? byAgent,
        IReadOnlyDictionary<string, long>? byAgentTokens,
        IReadOnlyDictionary<string, string> agentLabels,
        string currency = "USD",
        string? language = null)
    {
        var cost = byAgent ?? new Dictionary<string, double>();
        var tokens = byAgentTokens ?? new Dictionary<string, long>();
        var keys = cost.Keys.Union(tokens.Keys, StringComparer.Ordinal);
        var items = keys.Select(k => (
            Label: agentLabels.GetValueOrDefault(k) ?? AgentColors.DefaultLabels.GetValueOrDefault(k) ?? k,
            Cost: cost.GetValueOrDefault(k),
            Tokens: tokens.GetValueOrDefault(k)));
        return AgentLines(items, currency, language);
    }

    /// <summary>马赛克项目方块 tooltip：项目名 · $12.34 · 1.2亿 token，随后每个 agent 一行。</summary>
    public static string ProjectTileTooltip(
        string name, double cost, long tokens, IReadOnlyList<AgentCost> agents,
        string currency = "USD", string? language = null)
    {
        var header = $"{name} · {CostAndTokens(cost, tokens, currency, language)}";
        var lines = AgentLines(agents, currency, language);
        return lines.Count == 0 ? header : string.Join("\n", new[] { header }.Concat(lines));
    }

    /// <summary>合并小项目的总和计算。</summary>
    public static (double Cost, long Tokens) MergedTileSum(IEnumerable<(double Cost, long Tokens)> projects)
    {
        var cost = 0.0;
        long tokens = 0;
        foreach (var p in projects)
        {
            cost += p.Cost;
            tokens += p.Tokens;
        }
        return (cost, tokens);
    }

    public static (double Cost, long Tokens) MergedTileSum(IEnumerable<Project> projects) =>
        MergedTileSum(projects.Select(p => (p.Cost, p.Tokens.Total)));

    /// <summary>
    /// 马赛克 "+N more" 合并方块 tooltip：
    /// 5 个较小项目 · $12.34 · 1.2亿 token，随后每个项目一行（名字 + 金额 · token）。
    /// </summary>
    public static string MergedTileTooltip(IReadOnlyList<Project> projects, string currency = "USD", string? language = null)
    {
        var lang = language ?? L10n.CurrentLanguage;
        var (totalCost, totalTokens) = MergedTileSum(projects);
        var sumStr = CostAndTokens(totalCost, totalTokens, currency, lang);
        // 注意 L10n.tr("mosaic.smaller_projects") 模板自带末尾换行符 "\n"
        var header = L10n.TrL(lang, "mosaic.smaller_projects", projects.Count, sumStr);
        var sorted = projects
            .OrderByDescending(p => p.Cost)
            .ThenBy(p => p.Name, StringComparer.Ordinal)
            .Select(p => $"{p.Name}  {CostAndTokens(p.Cost, p.Tokens.Total, currency, lang)}")
            .ToList();
        var body = string.Join("\n", sorted);
        return body.Length == 0 ? header.Trim('\n') : header + body;
    }

    /// <summary>热力条周格 tooltip：Oct 13–19 · $42.10 · 1.2亿 token，随后每个 agent 一行。</summary>
    public static string WeekTooltip(
        string weekLabel, double cost, long tokens,
        IReadOnlyDictionary<string, double> byAgent,
        IReadOnlyDictionary<string, long> byAgentTokens,
        IReadOnlyDictionary<string, string> agentLabels,
        string currency = "USD", string? language = null)
    {
        var header = $"{weekLabel} · {CostAndTokens(cost, tokens, currency, language)}";
        var lines = AgentLines(byAgent, byAgentTokens, agentLabels, currency, language);
        return lines.Count == 0 ? header : string.Join("\n", new[] { header }.Concat(lines));
    }

    /// <summary>日图表 tooltip：2026年10月24日 · $12.34 · 1.2亿 token，随后每个 agent 一行。</summary>
    public static string DayTooltip(
        string dayString, double cost, long tokens,
        IReadOnlyDictionary<string, double>? byAgent = null,
        IReadOnlyDictionary<string, long>? byAgentTokens = null,
        IReadOnlyDictionary<string, string>? agentLabels = null,
        string currency = "USD", string? language = null)
    {
        var lang = language ?? L10n.CurrentLanguage;
        var dayFormatted = Fmt.Day(dayString, lang);
        var header = $"{dayFormatted} · {CostAndTokens(cost, tokens, currency, lang)}";
        var lines = AgentLines(byAgent, byAgentTokens, agentLabels ?? new Dictionary<string, string>(), currency, lang);
        return lines.Count == 0 ? header : string.Join("\n", new[] { header }.Concat(lines));
    }

    /// <summary>模型行 tooltip：claude-3-5-sonnet (claude) · $10.00 · 9000万 token。</summary>
    public static string ModelTooltip(
        string model, string agent, double cost, long tokens,
        string currency = "USD", string? language = null)
    {
        var ct = CostAndTokens(cost, tokens, currency, language);
        return $"{model} ({agent}) · {ct}";
    }
}

/// <summary>总览摘要行构建器：Today 隐藏冗余日期，其他范围保留。</summary>
public static class OverviewSummaryText
{
    public static string Make(
        TimeRange range, string dateRange, int projectsCount, int sessionsCount, long tokensCount,
        int hiddenCount = 0, string? language = null)
    {
        var lang = language ?? L10n.CurrentLanguage;
        var projCountStr = projectsCount == 1
            ? L10n.TrL(lang, "overview.count.project.singular", projectsCount)
            : L10n.TrL(lang, "overview.count.project.plural", projectsCount);
        var hiddenStr = hiddenCount > 0 ? L10n.TrL(lang, "overview.count.hidden", hiddenCount) : "";
        var projects = projCountStr + hiddenStr;

        var sessCountStr = sessionsCount == 1
            ? L10n.TrL(lang, "overview.count.session.singular", sessionsCount)
            : L10n.TrL(lang, "overview.count.session.plural", sessionsCount);

        var tokensFormatted = Fmt.Tokens(tokensCount, lang);
        var tokensStr = L10n.TrL(lang, "overview.tokens_count", tokensFormatted);

        var counts = string.Join(" · ", new[] { projects, sessCountStr, tokensStr });
        return range == TimeRange.Today ? counts : $"{dateRange} · {counts}";
    }
}

/// <summary>项目详情副标题行：Today 隐藏冗余日期，其他范围保留。</summary>
public static class ProjectSubtitleText
{
    public static string Make(TimeRange range, int sessions, string usageDate, string? language = null)
    {
        var lang = language ?? L10n.CurrentLanguage;
        var sessStr = sessions == 1
            ? L10n.TrL(lang, "overview.count.session.singular", sessions)
            : L10n.TrL(lang, "overview.count.session.plural", sessions);
        if (range == TimeRange.Today) return sessStr;
        var templateKey = sessions == 1 ? "project.subtitle.singular" : "project.subtitle.plural";
        return L10n.TrL(lang, templateKey, sessions, usageDate);
    }
}
