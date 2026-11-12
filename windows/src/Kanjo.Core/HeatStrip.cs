namespace Kanjo.Core;

/// <summary>一周的花费：总额 + 各 agent 之和（缺 by_agent 的天记到回退 agent）。</summary>
public sealed record WeekCost(
    DateTimeOffset Start,
    double Cost,
    long Tokens,
    IReadOnlyDictionary<string, double> ByAgent,
    IReadOnlyDictionary<string, long> ByAgentTokens)
{
    /// <summary>按 cost 降序（相同 cost 按 key 排，保证稳定）。</summary>
    public IReadOnlyList<(string Agent, double Cost)> Ranked =>
        ByAgent.OrderByDescending(kv => kv.Value).ThenBy(kv => kv.Key, StringComparer.Ordinal)
            .Select(kv => (kv.Key, kv.Value)).ToList();

    /// <summary>包含 tokens 的排序列表（按 cost 降序，相同 cost 按 tokens 降序，再按 key 排）。</summary>
    public IReadOnlyList<(string Agent, double Cost, long Tokens)> RankedWithTokens =>
        ByAgent.Keys.Union(ByAgentTokens.Keys, StringComparer.Ordinal)
            .Select(a => (Agent: a, Cost: ByAgent.GetValueOrDefault(a), Tokens: ByAgentTokens.GetValueOrDefault(a)))
            .OrderByDescending(t => t.Cost)
            .ThenByDescending(t => t.Tokens)
            .ThenBy(t => t.Agent, StringComparer.Ordinal)
            .ToList();

    /// <summary>那周花费最多的 agent；没有正花费时为 null。</summary>
    public string? TopAgent => Ranked.Count > 0 && Ranked[0].Cost > 0 ? Ranked[0].Agent : null;
}

/// <summary>8 周燃烧热力条：把 by_day 按周（周一到周日）累加。纯函数，不依赖 UI。</summary>
public static class HeatStrip
{
    public const int DefaultWeeks = 8;
    public const int Levels = 5;

    /// <summary>结束日期所在周（周一开始）往前共 `weeks` 周的起始日（本地零点），最早的在前。</summary>
    public static IReadOnlyList<DateTimeOffset> WeekStarts(
        DateTimeOffset end, int weeks = DefaultWeeks, TimeZoneInfo? timezone = null)
    {
        if (weeks <= 0) return [];
        var tz = timezone ?? TimeZoneInfo.Local;
        var day = Time.LocalDate(tz, end);
        var monday = Time.MondayOnOrBefore(tz, day);
        var result = new List<DateTimeOffset>(weeks);
        for (var i = 0; i < weeks; i++)
        {
            result.Add(Time.AtDay(tz, monday.AddDays(-7 * (weeks - 1 - i))));
        }
        return result;
    }

    /// <summary>
    /// 最近 `weeks` 周每周的花费及其按 agent 的拆分，最早的周在前。窗口外（更早或结束周之后）的日子被丢弃。
    /// 某天缺 `by_agent`（旧数据）或为空时，那天的 cost 全部记到 fallbackAgent（项目级主力 agent）。
    /// </summary>
    public static IReadOnlyList<WeekCost> Weekly(
        IReadOnlyList<DayCost> days,
        DateTimeOffset endingOn,
        string fallbackAgent,
        int weeks = DefaultWeeks,
        TimeZoneInfo? timezone = null)
    {
        var tz = timezone ?? TimeZoneInfo.Local;
        var starts = WeekStarts(endingOn, weeks, tz);
        var outList = starts
            .Select(s => new WeekCost(s, 0, 0,
                new Dictionary<string, double>(StringComparer.Ordinal),
                new Dictionary<string, long>(StringComparer.Ordinal)))
            .ToList();
        if (starts.Count == 0) return outList;
        var first = Time.LocalDate(tz, starts[0]);

        foreach (var d in days)
        {
            var date = ReportDates.ParseDay(d.Day);
            if (date is null) continue;
            var n = date.Value.DayNumber - first.DayNumber;
            if (n < 0) continue;
            var idx = n / 7;
            if (idx >= outList.Count) continue;

            var w = outList[idx];
            var byAgent = new Dictionary<string, double>(w.ByAgent, StringComparer.Ordinal);
            var byAgentTokens = new Dictionary<string, long>(w.ByAgentTokens, StringComparer.Ordinal);

            if (d.ByAgent is { Count: > 0 } split)
            {
                foreach (var (agent, cost) in split) byAgent[agent] = byAgent.GetValueOrDefault(agent) + cost;
            }
            else
            {
                byAgent[fallbackAgent] = byAgent.GetValueOrDefault(fallbackAgent) + d.Cost;
            }

            if (d.ByAgentTokens is { Count: > 0 } tokenSplit)
            {
                foreach (var (agent, tokens) in tokenSplit) byAgentTokens[agent] = byAgentTokens.GetValueOrDefault(agent) + tokens;
            }
            else
            {
                byAgentTokens[fallbackAgent] = byAgentTokens.GetValueOrDefault(fallbackAgent) + d.Tokens;
            }

            outList[idx] = w with
            {
                Cost = w.Cost + d.Cost,
                Tokens = w.Tokens + d.Tokens,
                ByAgent = byAgent,
                ByAgentTokens = byAgentTokens,
            };
        }
        return outList;
    }

    /// <summary>
    /// 一格的纵向色带：按 cost 降序最多 `maxSegments` 段，份额小于 `minShare` 的（以及超出段数的）
    /// 并进最大的那段，避免出碎条。份额之和为 1；没有正花费时为空。
    /// </summary>
    public static IReadOnlyList<(string Agent, double Share)> Segments(
        WeekCost week, double minShare = 0.1, int maxSegments = 3)
    {
        var ranked = week.Ranked.Where(r => r.Cost > 0).ToList();
        var total = ranked.Sum(r => r.Cost);
        if (total <= 0 || maxSegments <= 0) return [];

        var result = new List<(string Agent, double Share)>();
        var merged = 0.0;
        for (var i = 0; i < ranked.Count; i++)
        {
            var (agent, cost) = ranked[i];
            var share = cost / total;
            if (i == 0 || (share >= minShare && result.Count < maxSegments))
            {
                result.Add((agent, share));
            }
            else
            {
                merged += share;
            }
        }
        if (result.Count == 0) return [];
        result[0] = (result[0].Agent, result[0].Share + merged);
        return result;
    }

    /// <summary>深浅档位：0 = 无花费；1…levels-1 按 value / max 等分（向上取整）。</summary>
    public static int Level(double value, double max, int levels = Levels)
    {
        if (!(value > 0) || !(max > 0) || levels <= 1) return 0;
        var steps = levels - 1;
        var r = Math.Min(value / max, 1);
        return Math.Min(Math.Max((int)Math.Ceiling(r * steps), 1), levels - 1);
    }

    /// <summary>"Oct 13–19"；跨月 "Sep 29–Oct 5"；跨年 "Dec 29, 2025–Jan 4, 2026"。</summary>
    public static string WeekLabel(DateTimeOffset start, TimeZoneInfo? timezone = null)
    {
        var tz = timezone ?? TimeZoneInfo.Local;
        var lang = L10n.CurrentLanguage;
        var startLocal = TimeZoneInfo.ConvertTime(start, tz).Date;
        var endLocal = startLocal.AddDays(6);

        if (startLocal.Year != endLocal.Year)
        {
            return $"{FullDay(startLocal, lang)}–{FullDay(endLocal, lang)}";
        }
        var a = MonthDay(startLocal, lang);
        if (startLocal.Month != endLocal.Month) return $"{a}–{MonthDay(endLocal, lang)}";
        return $"{a}–{endLocal.Day}";
    }

    private static string MonthDay(DateTime d, string lang)
    {
        var culture = Fmt.CultureFor(lang);
        return lang.StartsWith("zh", StringComparison.Ordinal)
            ? $"{d.Month}月{d.Day}日"
            : $"{culture.DateTimeFormat.GetAbbreviatedMonthName(d.Month)} {d.Day}";
    }

    private static string FullDay(DateTime d, string lang) =>
        Fmt.DayFormatter(lang)(d);

    /// <summary>"YYYY-MM-DD" → 该日期（时区无关）。</summary>
    public static DateOnly? ParseDay(string s) => ReportDates.ParseDay(s);
}
