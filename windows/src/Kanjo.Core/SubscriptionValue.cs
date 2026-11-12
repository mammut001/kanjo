namespace Kanjo.Core;

/// <summary>额度卡的一行。Percent 为 null 时显示「—」（窗口已结束或缓存没有百分比）。</summary>
public sealed record QuotaRow(string Id, string Title, double? Percent, string Detail);

public enum QuotaLevel
{
    Normal,
    Warning,
    Critical,
}

/// <summary>
/// 订阅价值（CONTRACT.md 7.4.1）：纯函数。账期用量走 RangeEngine，和「Billing cycle」范围同一套口径。
/// </summary>
public static class SubscriptionValue
{
    /// <summary>契约要求卡片底部固定的一句，不可隐藏。</summary>
    public static string Explanation => L10n.Tr("overview.subscription_value.explanation");

    public static string AssumedDayHelp => L10n.Tr("overview.renewal_day_unknown_help");

    public static bool NeedsRenewalDay(Subscription sub) => sub.CycleSource == "rolling_30d";

    public static string? BillingPage(string agent) => agent switch
    {
        "claude" => "https://claude.ai/settings/billing",
        "codex" => "https://chatgpt.com/settings/billing",
        "antigravity" => "https://one.google.com/subscriptions",
        "copilot" => "https://github.com/settings/copilot",
        "grok" => "https://x.com/settings/premium",
        "minimax" => "https://platform.minimax.io",
        "qwen" => "https://dashscope.console.aliyun.com",
        "commandcode" => "https://commandcode.ai",
        "opencode" => "https://opencode.ai",
        _ => null,
    };

    /// <summary>cycle_source 优先：手填档位也可能仍然不知道续费日。</summary>
    public static string AnchorSource(Subscription sub) => sub.CycleSource switch
    {
        "rolling_30d" => L10n.Tr("settings.source.not_set"),
        "manual" => L10n.Tr("settings.source.manual"),
        "subscription_date" => L10n.Tr("settings.source.detected"),
        _ => sub.Source == "manual" ? L10n.Tr("settings.source.manual") : L10n.Tr("settings.source.detected"),
    };

    /// <summary>
    /// 悬停订阅行时的额度卡（契约 quota_windows）：5 小时窗口、周窗口各一行。
    /// 没有该 agent 的窗口时返回空数组（不显示卡片）。5 小时窗口已结束时那一行标「窗口已结束」。
    /// </summary>
    public static IReadOnlyList<QuotaRow> QuotaRows(
        QuotaWindow? window, TimeZoneInfo timezone, DateTimeOffset? now = null, string? language = null)
    {
        if (window is null) return [];
        var n = now ?? DateTimeOffset.UtcNow;
        var rows = new List<QuotaRow>();

        if (window.FiveHourWindowHours is { } hours)
        {
            var reset = ReportDates.ParseTimestamp(window.FiveHourResetsAt) is { } r && r > n ? r : (DateTimeOffset?)null;
            rows.Add(new QuotaRow(
                "five_hour",
                WindowName(hours),
                reset is null ? null : ClampPercent(window.FiveHourUsedPercent),
                reset is { } rr ? ResetText(rr, timezone, n, language) : L10n.Tr("overview.quota.ended")));
        }

        if (ReportDates.ParseTimestamp(window.WeeklyResetsAt) is { } weeklyReset)
        {
            var ended = weeklyReset <= n;
            rows.Add(new QuotaRow(
                "weekly",
                WindowName(window.WeeklyWindowHours),
                ended ? null : ClampPercent(window.WeeklyUsedPercent),
                ended ? L10n.Tr("overview.quota.ended") : ResetText(weeklyReset, timezone, n, language)));
        }

        if (window.ExtraWindows is { } extra)
        {
            foreach (var ew in extra)
            {
                var reset = ReportDates.ParseTimestamp(ew.ResetsAt) is { } r && r > n ? r : (DateTimeOffset?)null;
                rows.Add(new QuotaRow(
                    ew.Id,
                    ew.Title,
                    reset is null ? null : ClampPercent(ew.UsedPercent),
                    reset is { } rr ? ResetText(rr, timezone, n, language) : L10n.Tr("overview.quota.ended")));
            }
        }
        return rows;
    }

    public static string WindowName(int hours) =>
        hours == 168 ? L10n.Tr("overview.quota.weekly")
        : hours == 5 ? L10n.Tr("overview.quota.five_hour")
        : L10n.Tr("overview.quota.hours", hours);

    /// <summary>「2 小时 5 分后重置 · 周二 10:00」：相对时间 + 报告时区的绝对时间（当天只给时刻）。</summary>
    public static string ResetText(DateTimeOffset reset, TimeZoneInfo timezone, DateTimeOffset? now = null, string? language = null)
    {
        var n = now ?? DateTimeOffset.UtcNow;
        var lang = language ?? L10n.CurrentLanguage;
        var resetLocal = TimeZoneInfo.ConvertTime(reset, timezone);
        var nowLocal = TimeZoneInfo.ConvertTime(n, timezone);
        string absolute;
        if (resetLocal.Date == nowLocal.Date)
        {
            absolute = Fmt.TimeOfDay(resetLocal, lang);
        }
        else
        {
            absolute = Fmt.WeekdayTime(reset, timezone, lang);
        }
        return L10n.TrL(lang, "overview.quota.resets_in", Relative(n, reset, lang), absolute);
    }

    /// <summary>剩余时长，向上取整到分钟：不到 1 小时给分钟，不到 1 天给时+分，否则天+时。</summary>
    public static string Relative(DateTimeOffset now, DateTimeOffset date) => Relative(now, date, L10n.CurrentLanguage);

    public static string Relative(DateTimeOffset now, DateTimeOffset date, string? language)
    {
        var lang = language ?? L10n.CurrentLanguage;
        var minutes = Math.Max(1, (long)Math.Ceiling((date - now).TotalMinutes));
        if (minutes < 60) return L10n.TrL(lang, "overview.quota.rel_m", minutes);
        if (minutes < 1440) return L10n.TrL(lang, "overview.quota.rel_hm", minutes / 60, minutes % 60);
        return L10n.TrL(lang, "overview.quota.rel_dh", minutes / 1440, minutes % 1440 / 60);
    }

    public static QuotaLevel Level(double? percent)
    {
        if (percent is not { } p) return QuotaLevel.Normal;
        return p >= 95 ? QuotaLevel.Critical : p >= 80 ? QuotaLevel.Warning : QuotaLevel.Normal;
    }

    private static double? ClampPercent(double? p)
    {
        if (p is not { } value || double.IsNaN(value) || double.IsInfinity(value)) return null;
        return Math.Min(Math.Max(value, 0), 100);
    }

    /// <summary>用量 ÷ 月费。月费为空或不是正数时为 null（界面显示「—」，不显示倍数）。</summary>
    public static double? Multiplier(double usage, double? monthlyPriceUsd)
    {
        if (monthlyPriceUsd is not { } price || price <= 0) return null;
        if (double.IsNaN(usage) || double.IsInfinity(usage)) return null;
        var m = usage / price;
        return double.IsFinite(m) ? m : null;
    }

    /// <summary>本项目账期用量 ÷ 该 agent 全部账期用量。总量为 0 时没有占比（调用方跳过这一行）。</summary>
    public static double? Share(double part, double total)
    {
        if (!(total > 0)) return null;
        if (double.IsNaN(part) || double.IsInfinity(part) || double.IsNaN(total) || double.IsInfinity(total)) return null;
        return part / total;
    }

    /// <summary>每个有订阅的 agent 一行，按账期用量降序。</summary>
    public static IReadOnlyList<SubscriptionRow> Rows(UsageReport report, DateTimeOffset? now = null)
    {
        var subs = report.Subscriptions;
        if (subs is null || subs.Count == 0) return [];
        var n = now ?? DateTimeOffset.UtcNow;
        var usage = CycleUsageOf(report, n);
        return subs
            .Select(kv =>
            {
                var cost = usage.Total(kv.Key);
                return new SubscriptionRow(
                    kv.Key, kv.Value.PlanLabel, kv.Value.MonthlyPriceUsd, cost,
                    Multiplier(cost, kv.Value.MonthlyPriceUsd), kv.Value.ExtraUsageEnabled, kv.Value.Account);
            })
            .OrderByDescending(r => r.Usage)
            .ThenBy(r => r.Agent, StringComparer.Ordinal)
            .ToList();
    }

    /// <summary>这个项目里、有订阅且账期总量 &gt; 0 的 agent。占比 = 本项目账期 cost ÷ 该 agent 全部账期 cost。</summary>
    public static IReadOnlyList<CycleShare> Shares(string projectId, UsageReport report, DateTimeOffset? now = null)
    {
        var subs = report.Subscriptions;
        if (subs is null || subs.Count == 0) return [];
        var n = now ?? DateTimeOffset.UtcNow;
        var usage = CycleUsageOf(report, n);
        var result = new List<CycleShare>();
        foreach (var (agent, sub) in subs)
        {
            var total = usage.Total(agent);
            var part = usage.Cost(projectId, agent);
            if (Share(part, total) is not { } share) continue;
            result.Add(new CycleShare(agent, sub.PlanLabel, share, part));
        }
        return result
            .OrderByDescending(s => s.Share)
            .ThenBy(s => s.Agent, StringComparer.Ordinal)
            .ToList();
    }

    /// <summary>按各 agent 自己的 cycle_start 过滤后的金额。项目走 by_day，两个桶走 sessions_detail。</summary>
    public static CycleUsage CycleUsageOf(UsageReport report, DateTimeOffset? now = null)
    {
        var spec = RangeEngine.Spec(TimeRange.BillingCycle, report, now);
        var filtered = RangeEngine.Filtered(report, spec, FallbackAgent);
        var totals = new Dictionary<string, double>(StringComparer.Ordinal);
        var byProject = new Dictionary<string, IReadOnlyDictionary<string, double>>(StringComparer.Ordinal);

        foreach (var p in filtered.Projects)
        {
            var costs = new Dictionary<string, double>(StringComparer.Ordinal);
            foreach (var a in p.ByAgent.Where(a => a.Cost != 0))
            {
                costs[a.Agent] = a.Cost;
                totals[a.Agent] = totals.GetValueOrDefault(a.Agent) + a.Cost;
            }
            if (costs.Count > 0) byProject[p.Id] = costs;
        }

        foreach (var s in filtered.Unattributed.SessionsDetail.Concat(filtered.Excluded.SessionsDetail))
        {
            var (c, _) = spec.InRangeCostAndTokens(s);
            totals[s.Agent] = totals.GetValueOrDefault(s.Agent) + c;
        }

        return new CycleUsage(totals, byProject);
    }

    /// <summary>和总览 RangeContext 一样：缺 by_agent 时记到项目的主力 agent。</summary>
    private static string FallbackAgent(Project p) =>
        DominantAgent.Of(p.ByAgent)?.Agent ?? p.ByAgent.FirstOrDefault()?.Agent ?? "unknown";
}

/// <summary>提醒按 agent 记住关闭状态；新出现的未知续费日仍会提醒。</summary>
public static class RenewalNudge
{
    public static HashSet<string> ParseDismissed(string raw)
    {
        var set = new HashSet<string>(StringComparer.Ordinal);
        foreach (var item in raw.Split(',').Select(x => x.Trim()).Where(x => x.Length > 0)) set.Add(item);
        return set;
    }

    public static string SerializeDismissed(IEnumerable<string> agents) =>
        string.Join(",", agents.OrderBy(a => a, StringComparer.Ordinal));

    public static List<string> PendingAgents(
        IReadOnlyDictionary<string, Subscription> subscriptions, ISet<string> dismissed) =>
        subscriptions
            .Where(kv => SubscriptionValue.NeedsRenewalDay(kv.Value) && !dismissed.Contains(kv.Key))
            .Select(kv => kv.Key)
            .OrderBy(a => a, StringComparer.Ordinal)
            .ToList();
}

/// <summary>设置行的导航字符串同时作为滚动锚点，不依赖报告是否加载。</summary>
public static class SubscriptionSettingsRoute
{
    public static string Anchor(string agent) => $"settings:subscriptions:{agent}";

    public static (string Agent, bool IsEdit)? Parse(string raw)
    {
        var parts = raw.Split(':');
        if (parts.Length is not (3 or 4)) return null;
        if (!string.Equals(parts[0], "settings", StringComparison.OrdinalIgnoreCase)) return null;
        if (!string.Equals(parts[1], "subscriptions", StringComparison.OrdinalIgnoreCase)) return null;
        if (parts[2].Length == 0) return null;
        if (parts.Length == 4)
        {
            if (!string.Equals(parts[3], "edit", StringComparison.OrdinalIgnoreCase)) return null;
            return (parts[2].ToLowerInvariant(), true);
        }
        return (parts[2].ToLowerInvariant(), false);
    }

    public static string? Agent(string raw) => Parse(raw) is { IsEdit: false } p ? p.Agent : null;

    public static string? EditAgent(string raw) => Parse(raw) is { IsEdit: true } p ? p.Agent : null;
}
