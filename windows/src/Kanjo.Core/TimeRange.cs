namespace Kanjo.Core;

/// <summary>时间范围（CONTRACT.md 6.1）：纯函数，不依赖 UI。</summary>
public enum TimeRange
{
    All,
    Today,
    Days7,
    Days30,
    LastWeek,
    SinceReset,
    BillingCycle,
}

public static class TimeRanges
{
    public static readonly IReadOnlyList<TimeRange> All =
    [
        TimeRange.All, TimeRange.Today, TimeRange.Days7, TimeRange.Days30,
        TimeRange.LastWeek, TimeRange.SinceReset, TimeRange.BillingCycle,
    ];

    public static string RawValue(this TimeRange r) => r switch
    {
        TimeRange.All => "all",
        TimeRange.Today => "today",
        TimeRange.Days7 => "days7",
        TimeRange.Days30 => "days30",
        TimeRange.LastWeek => "lastWeek",
        TimeRange.SinceReset => "sinceReset",
        _ => "billingCycle",
    };

    public static TimeRange? Parse(string? raw)
    {
        foreach (var r in All)
        {
            if (r.RawValue() == raw) return r;
        }
        return null;
    }

    /// <summary>分段控件上的短名。</summary>
    public static string ShortLabel(this TimeRange r) => L10n.Tr(r switch
    {
        TimeRange.All => "timerange.all.short",
        TimeRange.Today => "timerange.today.short",
        TimeRange.Days7 => "timerange.days7.short",
        TimeRange.Days30 => "timerange.days30.short",
        TimeRange.LastWeek => "timerange.lastWeek.short",
        TimeRange.SinceReset => "timerange.sinceReset.short",
        _ => "timerange.billingCycle.short",
    });

    /// <summary>菜单栏范围后缀：固定时间窗口（Today / 7d / 30d）显示本地化后缀，其他范围无后缀。</summary>
    public static string? MenuBarSuffix(this TimeRange r) => r switch
    {
        TimeRange.Today => L10n.Tr("timerange.today.suffix"),
        TimeRange.Days7 or TimeRange.Days30 => r.ShortLabel(),
        _ => null,
    };

    public static string LongLabel(this TimeRange r) => L10n.Tr(r switch
    {
        TimeRange.All => "timerange.all.long",
        TimeRange.Today => "timerange.today.long",
        TimeRange.Days7 => "timerange.days7.long",
        TimeRange.Days30 => "timerange.days30.long",
        TimeRange.LastWeek => "timerange.lastWeek.long",
        TimeRange.SinceReset => "timerange.sinceReset.long",
        _ => "timerange.billingCycle.long",
    });
}

/// <summary>
/// 一个范围的具体区间。区间一律半开 [start, end)；null 端表示无界。
/// `sinceReset` / `billingCycle` 下每个 agent 有自己的起点（<see cref="AgentStarts"/>），不在字典里的 agent 不计入。
/// </summary>
public sealed record RangeSpec(
    TimeRange Range,
    TimeZoneInfo Timezone,
    DateTimeOffset? Start,
    DateTimeOffset? End,
    IReadOnlyDictionary<string, DateTimeOffset> AgentStarts)
{
    public bool IsAll => Range == TimeRange.All;

    /// <summary>某 agent 的有效区间；null = 该 agent 在此范围下不计入。</summary>
    public (DateTimeOffset? Start, DateTimeOffset? End)? Window(string agent) => Range switch
    {
        TimeRange.All => (null, null),
        TimeRange.SinceReset or TimeRange.BillingCycle =>
            AgentStarts.TryGetValue(agent, out var s) ? (s, End) : null,
        _ => (Start, End),
    };

    /// <summary>某天 [dayStart, dayEnd) 与该 agent 的区间相交即算。</summary>
    public bool IncludesDay(DateTimeOffset dayStart, DateTimeOffset dayEnd, string agent)
    {
        if (Window(agent) is not { } w) return false;
        if (w.Start is { } s && dayEnd <= s) return false;
        if (w.End is { } e && dayStart >= e) return false;
        return true;
    }

    /// <summary>时刻落在该 agent 的区间内。</summary>
    public bool Includes(DateTimeOffset instant, string agent)
    {
        if (Window(agent) is not { } w) return false;
        if (w.Start is { } s && instant < s) return false;
        if (w.End is { } e && instant >= e) return false;
        return true;
    }

    /// <summary>会话是否计入此范围：在范围内有用量（优先按日数据，否则按 [started, ended] 重叠）。</summary>
    public bool Includes(Session session)
    {
        if (Window(session.Agent) is not { } w) return false;
        if (session.ByDay is { Count: > 0 } byDay)
        {
            foreach (var d in byDay)
            {
                if (DayRange(d.Day) is not { } range) continue;
                if (IncludesDay(range.Start, range.End, session.Agent))
                {
                    if (d.Cost > 0 || d.Tokens > 0) return true;
                }
            }
            foreach (var d in byDay)
            {
                if (DayRange(d.Day) is not { } range) continue;
                if (IncludesDay(range.Start, range.End, session.Agent)) return true;
            }
            return false;
        }
        var s = session.StartedDate ?? session.EndedDate;
        var e = session.EndedDate ?? session.StartedDate;
        if (s is null || e is null) return false;
        var sessionStart = s.Value <= e.Value ? s.Value : e.Value;
        var sessionEnd = s.Value <= e.Value ? e.Value : s.Value;
        if (w.Start is { } start && sessionEnd < start) return false;
        if (w.End is { } end && sessionStart >= end) return false;
        return true;
    }

    /// <summary>
    /// 计算会话在当前范围内的花费与 token 份额：优先按日数据；否则按时间区间重叠比例缩放。
    /// </summary>
    public (double Cost, long Tokens) InRangeCostAndTokens(Session session)
    {
        if (IsAll) return (session.Cost, session.Tokens.Total);
        if (!Includes(session)) return (0, 0);

        if (session.ByDay is { Count: > 0 } byDay)
        {
            double c = 0;
            long t = 0;
            foreach (var d in byDay)
            {
                if (DayRange(d.Day) is not { } range) continue;
                if (IncludesDay(range.Start, range.End, session.Agent))
                {
                    c += d.Cost;
                    t += d.Tokens;
                }
            }
            return (c, t);
        }

        var s = session.StartedDate ?? session.EndedDate;
        var e = session.EndedDate ?? session.StartedDate;
        if (s is null || e is null) return (session.Cost, session.Tokens.Total);
        var s0 = s.Value <= e.Value ? s.Value : e.Value;
        var s1 = s.Value <= e.Value ? e.Value : s.Value;
        var dur = s1 - s0;
        if (dur <= TimeSpan.Zero) return (session.Cost, session.Tokens.Total);
        if (Window(session.Agent) is not { } w) return (0, 0);
        var r0 = w.Start ?? s0;
        var r1 = w.End ?? s1;
        var overlap0 = s0 > r0 ? s0 : r0;
        var overlap1 = s1 < r1 ? s1 : r1;
        if (overlap1 <= overlap0) return (0, 0);
        var share = Math.Min(1.0, Math.Max(0.0, (overlap1 - overlap0).TotalSeconds / dur.TotalSeconds));
        return (session.Cost * share, (long)Math.Round(session.Tokens.Total * share, MidpointRounding.AwayFromZero));
    }

    /// <summary>"YYYY-MM-DD" → 该时区的 [零点, 次日零点)。</summary>
    public (DateTimeOffset Start, DateTimeOffset End)? DayRange(string day)
    {
        var d = ReportDates.ParseDay(day);
        if (d is null) return null;
        var tz = Timezone;
        var start = Time.FromLocal(tz, d.Value.ToDateTime(TimeOnly.MinValue, DateTimeKind.Unspecified));
        var end = Time.FromLocal(tz, d.Value.AddDays(1).ToDateTime(TimeOnly.MinValue, DateTimeKind.Unspecified));
        return (start, end);
    }
}

/// <summary>一个项目在范围内的数字；<see cref="Projected"/> 把这些数字填回去，方便交给只认 Project 的视图。</summary>
public sealed record FilteredProject(
    Project Project,
    double Cost,
    long Tokens,
    int Sessions,
    RoList<AgentCost> ByAgent,
    RoList<DayCost> ByDay,
    RoList<Session> SessionsDetail,
    string? FirstActive,
    string? LastActive)
{
    public string Id => Project.Id;

    public bool HasUsage => Cost > 0 || Tokens > 0 || Sessions > 0;

    public Project Projected
    {
        get
        {
            var p = Project with
            {
                Cost = Cost,
                Sessions = Sessions,
                ByAgent = ByAgent,
                ByDay = ByDay,
                SessionsDetail = SessionsDetail,
                FirstActive = FirstActive,
                LastActive = LastActive,
            };
            if (Tokens != Project.Tokens.Total) p = p with { Tokens = Core.Tokens.WithTotal(Tokens) };
            return p;
        }
    }
}

/// <summary>unattributed / excluded 在范围内：只能按 sessions_detail 计（桶没有 by_day）。</summary>
public sealed record FilteredBucket(
    double Cost,
    long Tokens,
    int Sessions,
    RoList<Session> SessionsDetail,
    string? FirstActive,
    string? LastActive);

public sealed record FilteredReport(
    RangeSpec Spec,
    RoList<FilteredProject> Projects,
    FilteredBucket Unattributed,
    FilteredBucket Excluded,
    double Cost,
    long Tokens,
    int Sessions,
    string? FirstActive,
    string? LastActive)
{
    public FilteredProject? Project_(string id) => Projects.FirstOrDefault(p => p.Id == id);
}

public static class RangeEngine
{
    /// <summary>报告时区；时区名无效时用本机时区。</summary>
    public static TimeZoneInfo TimezoneOf(UsageReport report)
    {
        if (report.Timezone is { Length: > 0 } name)
        {
            try
            {
                return TimeZoneInfo.FindSystemTimeZoneById(name);
            }
            catch (Exception)
            {
                var converted = TryIanaToWindows(name);
                if (converted is not null)
                {
                    try
                    {
                        return TimeZoneInfo.FindSystemTimeZoneById(converted);
                    }
                    catch (Exception)
                    {
                        // 落到本机时区
                    }
                }
            }
        }
        return TimeZoneInfo.Local;
    }

    private static readonly Dictionary<string, string> IanaToWindows = new(StringComparer.Ordinal)
    {
        ["Asia/Shanghai"] = "China Standard Time",
        ["Asia/Hong_Kong"] = "China Standard Time",
        ["Asia/Taipei"] = "Taipei Standard Time",
        ["Asia/Tokyo"] = "Tokyo Standard Time",
        ["Asia/Seoul"] = "Korea Standard Time",
        ["Asia/Singapore"] = "Singapore Standard Time",
        ["Asia/Kolkata"] = "India Standard Time",
        ["Europe/London"] = "GMT Standard Time",
        ["Europe/Paris"] = "Romance Standard Time",
        ["Europe/Berlin"] = "W. Europe Standard Time",
        ["Europe/Madrid"] = "Romance Standard Time",
        ["Europe/Amsterdam"] = "W. Europe Standard Time",
        ["Europe/Moscow"] = "Russian Standard Time",
        ["America/New_York"] = "Eastern Standard Time",
        ["America/Toronto"] = "Eastern Standard Time",
        ["America/Chicago"] = "Central Standard Time",
        ["America/Denver"] = "Mountain Standard Time",
        ["America/Los_Angeles"] = "Pacific Standard Time",
        ["America/Vancouver"] = "Pacific Standard Time",
        ["America/Sao_Paulo"] = "E. South America Standard Time",
        ["Australia/Sydney"] = "AUS Eastern Standard Time",
        ["Australia/Melbourne"] = "AUS Eastern Standard Time",
        ["Pacific/Auckland"] = "New Zealand Standard Time",
        ["UTC"] = "UTC",
        ["Etc/UTC"] = "UTC",
    };

    private static string? TryIanaToWindows(string iana) =>
        IanaToWindows.TryGetValue(iana, out var win) ? win : null;

    /// <summary>范围 → 区间。</summary>
    public static RangeSpec DateInterval(
        TimeRange range,
        DateTimeOffset now,
        TimeZoneInfo timezone,
        IReadOnlyDictionary<string, QuotaWindow>? quota,
        IReadOnlyDictionary<string, Subscription>? subscriptions = null)
    {
        var today = Time.StartOfDay(timezone, now);
        DateTimeOffset DaysBack(int n) => Time.AddDays(timezone, today, -n);

        switch (range)
        {
            case TimeRange.All:
                return new RangeSpec(range, timezone, null, null, new Dictionary<string, DateTimeOffset>());
            case TimeRange.Today:
                return new RangeSpec(range, timezone, DaysBack(0), now, new Dictionary<string, DateTimeOffset>());
            case TimeRange.Days7:
                return new RangeSpec(range, timezone, DaysBack(6), now, new Dictionary<string, DateTimeOffset>());
            case TimeRange.Days30:
                return new RangeSpec(range, timezone, DaysBack(29), now, new Dictionary<string, DateTimeOffset>());
            case TimeRange.LastWeek:
            {
                var thisMonday = Time.MondayOnOrBefore(timezone, Time.LocalDate(timezone, today));
                var lastMonday = thisMonday.AddDays(-7);
                return new RangeSpec(
                    range, timezone,
                    Time.AtDay(timezone, lastMonday),
                    Time.AtDay(timezone, thisMonday),
                    new Dictionary<string, DateTimeOffset>());
            }
            case TimeRange.SinceReset:
            {
                var starts = new Dictionary<string, DateTimeOffset>(StringComparer.Ordinal);
                foreach (var (agent, q) in quota ?? new Dictionary<string, QuotaWindow>())
                {
                    if (WindowStart(q, now, timezone) is { } s) starts[agent] = s;
                }
                return new RangeSpec(range, timezone, null, now, starts);
            }
            default:
            {
                var starts = new Dictionary<string, DateTimeOffset>(StringComparer.Ordinal);
                foreach (var (agent, sub) in subscriptions ?? new Dictionary<string, Subscription>())
                {
                    if (ReportDates.ParseTimestamp(sub.CycleStart) is { } s) starts[agent] = s;
                }
                return new RangeSpec(range, timezone, null, now, starts);
            }
        }
    }

    /// <summary>报告上的便捷入口：时区、quota、订阅都取自报告。</summary>
    public static RangeSpec Spec(TimeRange range, UsageReport report, DateTimeOffset? now = null) =>
        DateInterval(range, now ?? DateTimeOffset.UtcNow, TimezoneOf(report), report.QuotaWindows, report.Subscriptions);

    /// <summary>
    /// 当前周窗口的起点：weekly_resets_at - window。起点在未来就再往前推整窗口；
    /// weekly_resets_at 已经过去（缓存过期）就往后推到最近一个 ≤ now 的起点。
    /// </summary>
    public static DateTimeOffset? WindowStart(QuotaWindow q, DateTimeOffset now, TimeZoneInfo? timezone = null)
    {
        if (q.WeeklyWindowHours <= 0) return null;
        var reset = ReportDates.ParseTimestamp(q.WeeklyResetsAt);
        if (reset is null) return null;

        if (q.WeeklyWindowHours == 168 && timezone is { } tz)
        {
            var k = (int)Math.Floor((now - reset.Value).TotalDays / 7);
            var start = Time.AddWeeks(tz, reset.Value, k);
            while (start > now)
            {
                k -= 1;
                start = Time.AddWeeks(tz, reset.Value, k);
            }
            while (Time.AddWeeks(tz, reset.Value, k + 1) <= now)
            {
                k += 1;
                start = Time.AddWeeks(tz, reset.Value, k);
            }
            return start;
        }

        var w = TimeSpan.FromHours(q.WeeklyWindowHours);
        var kk = Math.Floor((now - reset.Value).TotalSeconds / w.TotalSeconds);
        return reset.Value.AddSeconds(kk * w.TotalSeconds);
    }

    // MARK: - 过滤

    public delegate string FallbackAgentFor(Project project);

    public static FilteredReport Filtered(UsageReport report, RangeSpec spec, FallbackAgentFor fallbackAgentFor)
    {
        var projects = report.Projects.Select(p => Filter(p, spec, fallbackAgentFor(p))).ToList();
        var u = Filter(report.Buckets.Unattributed, spec);
        var e = Filter(report.Buckets.Excluded, spec);

        if (spec.IsAll)
        {
            var t = report.Totals;
            return new FilteredReport(spec, projects, u, e, t.Cost, t.Tokens.Total, t.Sessions, t.FirstActive, t.LastActive);
        }

        var sorted = projects
            .Select((p, i) => (p, i))
            .OrderByDescending(x => x.p.Cost)
            .ThenBy(x => x.i)
            .Select(x => x.p)
            .ToList();

        var days = sorted.SelectMany(p => new[] { p.FirstActive, p.LastActive })
            .Concat([u.FirstActive, u.LastActive, e.FirstActive, e.LastActive])
            .Where(d => d is not null)
            .Select(d => d!)
            .ToList();

        return new FilteredReport(
            spec, sorted, u, e,
            sorted.Sum(p => p.Cost) + u.Cost + e.Cost,
            sorted.Sum(p => p.Tokens) + u.Tokens + e.Tokens,
            sorted.Sum(p => p.Sessions) + u.Sessions + e.Sessions,
            days.Count == 0 ? null : days.Min(StringComparer.Ordinal),
            days.Count == 0 ? null : days.Max(StringComparer.Ordinal));
    }

    /// <summary>单个项目。某天缺 by_agent（或为空）时那天的 cost 全记到 fallbackAgent；缺 by_agent_tokens 时 tokens 同理。</summary>
    public static FilteredProject Filter(Project p, RangeSpec spec, string fallbackAgent)
    {
        if (spec.IsAll)
        {
            return new FilteredProject(p, p.Cost, p.Tokens.Total, p.Sessions, p.ByAgent, p.ByDay,
                p.SessionsDetail, p.FirstActive, p.LastActive);
        }

        var agentCost = new Dictionary<string, double>(StringComparer.Ordinal);
        var agentTokens = new Dictionary<string, long>(StringComparer.Ordinal);
        var agentSessions = new Dictionary<string, int>(StringComparer.Ordinal);
        var days = new List<DayCost>();

        foreach (var d in p.ByDay)
        {
            if (spec.DayRange(d.Day) is not { } range) continue;
            var costSplit = d.ByAgent is { Count: > 0 } ca
                ? ca
                : new Dictionary<string, double>(StringComparer.Ordinal) { [fallbackAgent] = d.Cost };
            var tokenSplit = d.ByAgentTokens is { Count: > 0 } ta
                ? ta
                : new Dictionary<string, long>(StringComparer.Ordinal) { [fallbackAgent] = d.Tokens };

            var dc = new Dictionary<string, double>(StringComparer.Ordinal);
            var dt = new Dictionary<string, long>(StringComparer.Ordinal);
            foreach (var agent in costSplit.Keys.Union(tokenSplit.Keys, StringComparer.Ordinal))
            {
                if (!spec.IncludesDay(range.Start, range.End, agent)) continue;
                if (costSplit.TryGetValue(agent, out var c)) dc[agent] = c;
                if (tokenSplit.TryGetValue(agent, out var t)) dt[agent] = t;
            }
            if (dc.Count == 0 && dt.Count == 0) continue;
            foreach (var (a, c) in dc) agentCost[a] = agentCost.GetValueOrDefault(a) + c;
            foreach (var (a, t) in dt) agentTokens[a] = agentTokens.GetValueOrDefault(a) + t;
            days.Add(new DayCost(d.Day, dc.Values.Sum(), dt.Values.Sum(), dc, dt));
        }

        var sessions = p.SessionsDetail.Where(spec.Includes).ToList();
        foreach (var s in sessions) agentSessions[s.Agent] = agentSessions.GetValueOrDefault(s.Agent) + 1;

        var labels = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var s in p.SessionsDetail) labels[s.Agent] = s.Label;
        foreach (var a in p.ByAgent) labels[a.Agent] = a.Label;

        var keys = agentCost.Keys.Union(agentTokens.Keys, StringComparer.Ordinal).Union(agentSessions.Keys, StringComparer.Ordinal);
        var byAgent = new List<AgentCost>();
        foreach (var k in keys)
        {
            var a = new AgentCost(k, labels.GetValueOrDefault(k) ?? k,
                agentCost.GetValueOrDefault(k), Core.Tokens.WithTotal(agentTokens.GetValueOrDefault(k)),
                agentSessions.GetValueOrDefault(k));
            if (a.Cost > 0 || a.Tokens.Total > 0 || a.Sessions > 0) byAgent.Add(a);
        }
        byAgent.Sort((a, b) => a.Cost != b.Cost ? b.Cost.CompareTo(a.Cost) : string.CompareOrdinal(a.Agent, b.Agent));

        return new FilteredProject(
            p,
            days.Sum(d => d.Cost),
            days.Sum(d => d.Tokens),
            sessions.Count,
            byAgent,
            days,
            sessions,
            days.Count > 0 ? days[0].Day : null,
            days.Count > 0 ? days[^1].Day : null);
    }

    public static FilteredBucket Filter(SessionBucket b, RangeSpec spec)
    {
        if (spec.IsAll)
        {
            return new FilteredBucket(b.Cost, b.Tokens.Total, b.Sessions, b.SessionsDetail, b.FirstActive, b.LastActive);
        }
        var ss = b.SessionsDetail.Where(spec.Includes).ToList();
        var days = ss.SelectMany(s => new[] { s.StartedDate, s.EndedDate })
            .Where(d => d is not null)
            .Select(d => Time.DayString(spec.Timezone, d!.Value))
            .ToList();
        double totalCost = 0;
        long totalTokens = 0;
        foreach (var s in ss)
        {
            var (c, t) = spec.InRangeCostAndTokens(s);
            totalCost += c;
            totalTokens += t;
        }
        return new FilteredBucket(
            totalCost, totalTokens, ss.Count, ss,
            days.Count == 0 ? null : days.Min(StringComparer.Ordinal),
            days.Count == 0 ? null : days.Max(StringComparer.Ordinal));
    }

    /// <summary>时刻 → 该时区下的 "YYYY-MM-DD"。</summary>
    public static string DayString(DateTimeOffset d, TimeZoneInfo timezone) => Time.DayString(timezone, d);
}
