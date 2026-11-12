using System.Globalization;

namespace Kanjo.Core;

/// <summary>
/// 当前生效的时间范围：存储值 + 报告 → 区间、过滤结果、说明文字。
/// 「Since reset」在报告没有 quota_windows 时不可用，「Billing cycle」在没有 subscriptions 时不可用；
/// 存储值是它们也按 All 显示。
/// </summary>
public sealed class RangeContext
{
    public UsageReport Report { get; }
    public TimeRange Range { get; }
    public RangeSpec Spec { get; }
    public bool ResetAvailable { get; }
    public bool CycleAvailable { get; }

    public RangeContext(UsageReport report, string? raw, DateTimeOffset? now = null)
    {
        Report = report;
        var reset = report.QuotaWindows is { Count: > 0 };
        var cycle = report.Subscriptions is { Count: > 0 };
        var wanted = TimeRanges.Parse(raw) ?? TimeRange.All;
        if (wanted == TimeRange.SinceReset && !reset) wanted = TimeRange.All;
        if (wanted == TimeRange.BillingCycle && !cycle) wanted = TimeRange.All;
        Range = wanted;
        ResetAvailable = reset;
        CycleAvailable = cycle;
        Spec = RangeEngine.Spec(Range, report, now);
    }

    public bool IsAll => Range == TimeRange.All;

    /// <summary>缺 by_day.by_agent / by_agent_tokens 时的回退：项目级主力 agent。</summary>
    public static string FallbackAgent(Project p) =>
        DominantAgent.Of(p.ByAgent)?.Agent ?? p.ByAgent.FirstOrDefault()?.Agent ?? "unknown";

    public FilteredReport Filtered() => RangeEngine.Filtered(Report, Spec, FallbackAgent);

    public FilteredProject Filter(Project p) => RangeEngine.Filter(p, Spec, FallbackAgent(p));

    /// <summary>范围说明结果（仅 Since reset / Billing cycle 有值）。</summary>
    public RangeCaptionResult? CaptionResult => RangeCaptionBuilder.Caption(
        Range, Spec, RangeCaptionBuilder.AgentOrder(Report), Report.AgentLabels(), Report.Subscriptions);

    public string? Caption => CaptionResult?.Text;

    public string? CaptionHelp => CaptionResult?.Help;

    public IReadOnlyList<string> AgentOrder => RangeCaptionBuilder.AgentOrder(Report);

    public string ShortName(string agent) => RangeCaptionBuilder.ShortName(agent, Report.AgentLabels());
}

/// <summary>范围说明结果：Text 为显示的说明文字；Help 为悬浮提示（当有多个未计入的 agent 时，列出其短名）。</summary>
public sealed record RangeCaptionResult(string Text, string? Help = null);

public static class RangeCaptionBuilder
{
    /// <summary>报告里出现的 agent（按总花费降序），后面接只在 quota_windows / subscriptions 里出现的（按 key 升序）。</summary>
    public static IReadOnlyList<string> AgentOrder(UsageReport report)
    {
        var cost = new Dictionary<string, double>(StringComparer.Ordinal);
        foreach (var p in report.Projects)
        {
            foreach (var a in p.ByAgent) cost[a.Agent] = cost.GetValueOrDefault(a.Agent) + a.Cost;
        }
        var used = cost
            .OrderByDescending(kv => kv.Value)
            .ThenBy(kv => kv.Key, StringComparer.Ordinal)
            .Select(kv => kv.Key)
            .ToList();

        var extraKeys = new HashSet<string>(StringComparer.Ordinal);
        if (report.QuotaWindows is { } q) extraKeys.UnionWith(q.Keys);
        if (report.Subscriptions is { } s) extraKeys.UnionWith(s.Keys);
        var extra = extraKeys.Where(k => !cost.ContainsKey(k)).OrderBy(k => k, StringComparer.Ordinal).ToList();
        return used.Concat(extra).ToList();
    }

    /// <summary>"Claude Code" → "Claude"；未知 agent 用 key。</summary>
    public static string ShortName(string agent, IReadOnlyDictionary<string, string>? labels = null)
    {
        var label = labels?.GetValueOrDefault(agent)
                    ?? AgentColors.DefaultLabels.GetValueOrDefault(agent)
                    ?? Capitalize(agent);
        var space = label.IndexOf(' ');
        return space > 0 ? label[..space] : label;
    }

    private static string Capitalize(string s)
    {
        // Swift 的 `String.capitalized`：每个「词」首字母大写，其余小写（`_`、空格等都算分隔符）。
        var chars = s.ToCharArray();
        var startOfWord = true;
        for (var i = 0; i < chars.Length; i++)
        {
            var c = chars[i];
            if (char.IsLetter(c))
            {
                chars[i] = startOfWord ? char.ToUpperInvariant(c) : char.ToLowerInvariant(c);
                startOfWord = false;
            }
            else
            {
                startOfWord = true;
            }
        }
        return new string(chars);
    }

    /// <summary>范围说明纯函数（仅 Since reset / Billing cycle 有值；其它范围为 null）。</summary>
    public static RangeCaptionResult? Caption(
        TimeRange range,
        RangeSpec spec,
        IReadOnlyList<string> agentOrder,
        IReadOnlyDictionary<string, string>? agentLabels = null,
        IReadOnlyDictionary<string, Subscription>? subscriptions = null,
        string? language = null)
    {
        var lang = language ?? L10n.CurrentLanguage;
        var tz = spec.Timezone;

        switch (range)
        {
            case TimeRange.All:
            case TimeRange.Today:
            case TimeRange.Days7:
            case TimeRange.Days30:
            case TimeRange.LastWeek:
                return null;

            case TimeRange.SinceReset:
            {
                var withReset = agentOrder.Where(a => spec.AgentStarts.ContainsKey(a)).ToList();
                var without = agentOrder.Where(a => !spec.AgentStarts.ContainsKey(a)).ToList();

                string Stamp(string agent) =>
                    Fmt.MonthDay(spec.AgentStarts[agent], tz, lang) + " " +
                    TimeZoneInfo.ConvertTime(spec.AgentStarts[agent], tz).ToString("HH:mm", CultureInfo.InvariantCulture);

                var parts = withReset.Select(agent =>
                    L10n.TrL(lang, "timerange.caption.reset", ShortName(agent, agentLabels), Stamp(agent))).ToList();
                if (parts.Count > 0)
                {
                    parts[0] = L10n.TrL(lang, "timerange.caption.since", ShortName(withReset[0], agentLabels), Stamp(withReset[0]));
                }

                string? help = null;
                if (without.Count == 1)
                {
                    var name = ShortName(without[0], agentLabels);
                    parts.Add(L10n.TrL(lang, "timerange.caption.no_reset_info", name));
                }
                else if (without.Count > 1)
                {
                    parts.Add(L10n.TrL(lang, "timerange.caption.no_reset_info_others", without.Count));
                    help = string.Join(", ", without.Select(a => ShortName(a, agentLabels)));
                }

                if (parts.Count == 0) return new RangeCaptionResult(L10n.TrL(lang, "timerange.sinceReset.long"));
                return new RangeCaptionResult(string.Join(" · ", parts), help);
            }

            default:
            {
                var withCycle = agentOrder.Where(a => spec.AgentStarts.ContainsKey(a)).ToList();
                var without = agentOrder.Where(a => !spec.AgentStarts.ContainsKey(a)).ToList();

                var cycleParts = withCycle.Select(agent =>
                {
                    if (subscriptions is null || !subscriptions.TryGetValue(agent, out var sub))
                    {
                        return ShortName(agent, agentLabels);
                    }
                    return Fmt.CycleRangeCaption(sub, tz, lang);
                }).ToList();

                var parts = new List<string> { L10n.TrL(lang, "timerange.billingCycle.long") };
                parts.AddRange(cycleParts);

                string? help = null;
                if (without.Count == 1)
                {
                    var name = ShortName(without[0], agentLabels);
                    parts.Add(L10n.TrL(lang, "timerange.caption.no_subscription", name));
                }
                else if (without.Count > 1)
                {
                    parts.Add(L10n.TrL(lang, "timerange.caption.no_subscription_others", without.Count));
                    help = string.Join(", ", without.Select(a => ShortName(a, agentLabels)));
                }

                return new RangeCaptionResult(string.Join(" · ", parts), help);
            }
        }
    }

    public static RangeCaptionResult? Caption(
        TimeRange range, UsageReport report, DateTimeOffset? now = null, string? language = null)
    {
        var spec = RangeEngine.Spec(range, report, now);
        return Caption(range, spec, AgentOrder(report), report.AgentLabels(), report.Subscriptions, language);
    }
}
