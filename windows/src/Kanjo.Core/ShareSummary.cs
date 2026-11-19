namespace Kanjo.Core;

/// <summary>
/// 分享图用的用量摘要（Mac <c>ShareSummary</c> 的移植）。
/// 范围、过滤、金额 / token 格式化都走已有的 <see cref="RangeContext"/> / <see cref="RangeEngine"/>；
/// agent 行的 token 与花费口径与 Mac <c>AgentSummary</c> 一致（0 token 的 agent 不出现，
/// 按 token、花费、名字排序）。隐藏项目不进马赛克和 Top projects，但仍算进总额。
/// </summary>
public sealed record ShareSummary(
    IReadOnlyList<ShareSummary.AgentRow> AgentRows,
    ShareSummary.Total Totals,
    IReadOnlyList<ShareSummary.ProjectShare> TopProjects,
    IReadOnlyList<Project> MosaicProjects,
    string RangeLabel,
    string Currency,
    DateTimeOffset Updated)
{
    public sealed record AgentProjectShare(string Name, double Cost);

    public sealed record AgentRow(
        string Agent,
        string Label,
        long Tokens,
        Tokens TokenBreakdown,
        double? CacheHitRate,
        double Cost,
        Subscription? Subscription,
        double? Multiplier,
        int SessionCount,
        IReadOnlyList<AgentProjectShare> ProjectShares);

    public sealed record ProjectShare(string Name, double Cost, double Share);

    public sealed record Total(
        long Tokens,
        double Cost,
        int AgentsCount,
        int Sessions,
        long Input,
        long Output,
        long CacheRead,
        long CacheWrite,
        long Thinking);

    private static readonly IReadOnlySet<string> NoHidden = new HashSet<string>(StringComparer.Ordinal);

    public static ShareSummary Build(
        UsageReport report,
        string? rangeRaw,
        DateTimeOffset? now = null,
        IReadOnlySet<string>? hiddenProjects = null)
    {
        var moment = now ?? DateTimeOffset.UtcNow;
        var hidden = hiddenProjects ?? NoHidden;
        var ctx = new RangeContext(report, rangeRaw, moment);
        var filtered = ctx.Filtered();

        var agentCost = new Dictionary<string, double>(StringComparer.Ordinal);
        var agentTokens = new Dictionary<string, long>(StringComparer.Ordinal);
        var labels = report.AgentLabels();

        foreach (var project in filtered.Projects)
        {
            foreach (var agent in project.ByAgent)
            {
                agentCost[agent.Agent] = agentCost.GetValueOrDefault(agent.Agent) + agent.Cost;
                agentTokens[agent.Agent] = agentTokens.GetValueOrDefault(agent.Agent) + agent.Tokens.Total;
                RememberLabel(labels, agent.Agent, agent.Label);
            }
        }

        foreach (var session in filtered.Unattributed.SessionsDetail.Concat(filtered.Excluded.SessionsDetail))
        {
            var (cost, tokens) = filtered.Spec.InRangeCostAndTokens(session);
            agentCost[session.Agent] = agentCost.GetValueOrDefault(session.Agent) + cost;
            agentTokens[session.Agent] = agentTokens.GetValueOrDefault(session.Agent) + tokens;
            RememberLabel(labels, session.Agent, session.Label);
        }

        var active = agentTokens.Keys
            .Where(agent => agentTokens[agent] > 0)
            .OrderByDescending(agent => agentTokens[agent])
            .ThenByDescending(agent => agentCost.GetValueOrDefault(agent))
            .ThenBy(agent => agent, StringComparer.Ordinal)
            .ToList();

        var exact = ExactBreakdowns(report);
        var sessionsByAgent = InRangeSessions(filtered);
        var cycle = SubscriptionValue.CycleUsageOf(report, moment);

        var rows = new List<AgentRow>(active.Count);
        long totalInput = 0, totalOutput = 0, totalCacheRead = 0, totalCacheWrite = 0, totalThinking = 0;
        foreach (var agent in active)
        {
            var tokens = agentTokens[agent];
            var cost = agentCost.GetValueOrDefault(agent);
            Tokens breakdown;
            if (filtered.Spec.IsAll)
            {
                breakdown = exact.TryGetValue(agent, out var allTime) && allTime.Total > 0
                    ? allTime
                    : Tokens.WithTotal(tokens);
            }
            else
            {
                sessionsByAgent.TryGetValue(agent, out var sessions);
                exact.TryGetValue(agent, out var fallback);
                breakdown = Apportioned(tokens, sessions ?? [], filtered.Spec, fallback);
            }

            totalInput += breakdown.Input;
            totalOutput += breakdown.Output;
            totalCacheRead += breakdown.CacheRead;
            totalCacheWrite += breakdown.CacheWrite;
            totalThinking += breakdown.Thinking;

            Subscription? subscription = null;
            if (report.Subscriptions?.TryGetValue(agent, out var found) == true) subscription = found;
            var multiplier = subscription is null
                ? null
                : SubscriptionValue.Multiplier(cycle.Total(agent), subscription.MonthlyPriceUsd);

            var projectShares = new List<AgentProjectShare>();
            foreach (var project in filtered.Projects)
            {
                var agentCostOnProject = project.ByAgent.FirstOrDefault(a => a.Agent == agent)?.Cost ?? 0;
                if (agentCostOnProject > 0)
                {
                    projectShares.Add(new AgentProjectShare(project.Project.Name, agentCostOnProject));
                }
            }

            var sessionCount = filtered.Projects
                .SelectMany(project => project.SessionsDetail)
                .Count(session => session.Agent == agent);

            rows.Add(new AgentRow(
                agent,
                labels.GetValueOrDefault(agent) ?? AgentColors.Label(agent),
                tokens,
                breakdown,
                CacheHit(breakdown),
                cost,
                subscription,
                multiplier,
                sessionCount,
                projectShares));
        }

        var projectCosts = new Dictionary<string, (string Name, double Cost)>(StringComparer.Ordinal);
        foreach (var project in filtered.Projects)
        {
            if (hidden.Contains(project.Id)) continue;
            var previous = projectCosts.GetValueOrDefault(project.Id);
            projectCosts[project.Id] = (project.Project.Name, previous.Cost + project.Cost);
        }

        var denom = Math.Max(1, filtered.Cost);
        var top = projectCosts.Values
            .OrderByDescending(project => project.Cost)
            .Take(5)
            .Select(project => new ProjectShare(project.Name, project.Cost, project.Cost / denom))
            .ToList();

        var mosaic = filtered.Projects
            .Where(project => project.Cost > 0 && !hidden.Contains(project.Id))
            .Select(project => project.Projected)
            .ToList();

        return new ShareSummary(
            rows,
            new Total(
                filtered.Tokens,
                filtered.Cost,
                rows.Count,
                filtered.Sessions,
                totalInput,
                totalOutput,
                totalCacheRead,
                totalCacheWrite,
                totalThinking),
            top,
            mosaic,
            ctx.Caption ?? ctx.Range.LongLabel(),
            report.Currency,
            ReportDates.ParseTimestamp(report.GeneratedAt) ?? moment);
    }

    private static void RememberLabel(Dictionary<string, string> labels, string agent, string label)
    {
        if (!labels.TryGetValue(agent, out var existing) || existing == agent) labels[agent] = label;
    }

    private static double? CacheHit(Tokens tokens)
    {
        var denom = tokens.Input + tokens.CacheRead;
        return denom > 0 ? (double)tokens.CacheRead / denom : null;
    }

    /// <summary>全时段的 token 构成：项目 by_agent 加上两个桶的会话（不过滤范围）。</summary>
    private static Dictionary<string, Tokens> ExactBreakdowns(UsageReport report)
    {
        var map = new Dictionary<string, Tokens>(StringComparer.Ordinal);
        foreach (var project in report.Projects)
        {
            foreach (var agent in project.ByAgent)
            {
                map[agent.Agent] = map.GetValueOrDefault(agent.Agent) + agent.Tokens;
            }
        }

        foreach (var session in report.Buckets.Unattributed.SessionsDetail.Concat(report.Buckets.Excluded.SessionsDetail))
        {
            map[session.Agent] = map.GetValueOrDefault(session.Agent) + session.Tokens;
        }

        return map;
    }

    private static Dictionary<string, List<Session>> InRangeSessions(FilteredReport filtered)
    {
        var map = new Dictionary<string, List<Session>>(StringComparer.Ordinal);
        foreach (var project in filtered.Projects)
        {
            foreach (var session in project.SessionsDetail)
            {
                if (!map.TryGetValue(session.Agent, out var list))
                {
                    list = [];
                    map[session.Agent] = list;
                }
                list.Add(session);
            }
        }

        foreach (var session in filtered.Unattributed.SessionsDetail.Concat(filtered.Excluded.SessionsDetail))
        {
            if (!map.TryGetValue(session.Agent, out var list))
            {
                list = [];
                map[session.Agent] = list;
            }
            list.Add(session);
        }

        return map;
    }

    /// <summary>
    /// 非「全部」范围没有按日的 token 构成，按范围内会话的构成比例把目标 token 拆开
    /// （最大余额法，和 Mac <c>AgentSummary.apportion</c> 一致）。
    /// </summary>
    private static Tokens Apportioned(long target, IReadOnlyList<Session> sessions, RangeSpec spec, Tokens fallback)
    {
        if (target <= 0) return Tokens.Zero;

        double wInput = 0, wOutput = 0, wCacheRead = 0, wCacheWrite = 0, wThinking = 0;
        foreach (var session in sessions)
        {
            var (_, inRange) = spec.InRangeCostAndTokens(session);
            if (inRange <= 0) continue;
            var denom = Math.Max(
                session.Tokens.Input + session.Tokens.Output + session.Tokens.CacheRead + session.Tokens.CacheWrite,
                session.Tokens.Total);
            if (denom <= 0) continue;
            var scale = inRange / (double)denom;
            wInput += session.Tokens.Input * scale;
            wOutput += session.Tokens.Output * scale;
            wCacheRead += session.Tokens.CacheRead * scale;
            wCacheWrite += session.Tokens.CacheWrite * scale;
            wThinking += session.Tokens.Thinking * scale;
        }

        var weightedSum = wInput + wOutput + wCacheRead + wCacheWrite;
        double[] weights;
        double thinkingRatio;
        if (weightedSum > 0)
        {
            weights = [wInput, wOutput, wCacheRead, wCacheWrite];
            thinkingRatio = wOutput > 0 ? Math.Min(1, Math.Max(0, wThinking / wOutput)) : 0;
        }
        else if (fallback.Input + fallback.Output + fallback.CacheRead + fallback.CacheWrite > 0)
        {
            weights = [fallback.Input, fallback.Output, fallback.CacheRead, fallback.CacheWrite];
            thinkingRatio = fallback.Output > 0
                ? Math.Min(1, Math.Max(0, (double)fallback.Thinking / fallback.Output))
                : 0;
        }
        else
        {
            return Tokens.WithTotal(target);
        }

        var parts = Apportion(target, weights);
        var output = parts[1];
        var thinking = (long)Math.Round(output * thinkingRatio, MidpointRounding.AwayFromZero);
        if (thinking < 0) thinking = 0;
        if (thinking > output) thinking = output;
        return new Tokens(parts[0], output, parts[2], parts[3], thinking, target);
    }

    private static long[] Apportion(long total, double[] weights)
    {
        if (weights.Length == 0 || total <= 0) return new long[weights.Length];
        var sum = 0.0;
        foreach (var weight in weights) sum += weight;
        if (sum <= 0) return new long[weights.Length];

        var quotas = new double[weights.Length];
        var integers = new long[weights.Length];
        for (var i = 0; i < weights.Length; i++)
        {
            quotas[i] = total * (weights[i] / sum);
            integers[i] = (long)Math.Floor(quotas[i]);
        }

        var leftover = total;
        foreach (var value in integers) leftover -= value;
        if (leftover < 0) leftover = 0;

        var remainders = new (int Index, double Remainder)[weights.Length];
        for (var i = 0; i < weights.Length; i++)
        {
            remainders[i] = (i, quotas[i] - integers[i]);
        }
        Array.Sort(remainders, (a, b) =>
        {
            var delta = Math.Abs(a.Remainder - b.Remainder);
            if (delta > 1e-9) return b.Remainder.CompareTo(a.Remainder);
            return a.Index.CompareTo(b.Index);
        });

        var give = (int)Math.Min(leftover, remainders.Length);
        for (var i = 0; i < give; i++) integers[remainders[i].Index] += 1;
        return integers;
    }
}
