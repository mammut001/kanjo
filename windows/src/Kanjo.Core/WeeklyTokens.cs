namespace Kanjo.Core;

/// <summary>
/// 总览「本周 token」：从参考时刻所在周的周一 00:00 起，把各项目 <c>by_day</c> 的 token 加起来。
/// 一周固定从周一开始。时区由传入的 <see cref="TimeZoneInfo"/> 决定（对应用户日历）。
/// </summary>
public static class WeeklyTokens
{
    /// <summary>
    /// 参考时刻：报告生成时间比现在旧就用它，否则用现在。
    /// 样本数据和过期导出因此落在报告那一周，而不是按墙钟算出 0。
    /// </summary>
    public static DateTimeOffset Reference(DateTimeOffset now, DateTimeOffset? generatedAt) =>
        generatedAt is { } generated && generated < now ? generated : now;

    /// <summary>
    /// <paramref name="now"/> 所在周的周一 00:00（<paramref name="timeZone"/>）及之后的 token 之和。没有上界。
    /// </summary>
    public static long Since(DateTimeOffset now, IReadOnlyList<Project> projects, TimeZoneInfo timeZone)
    {
        var monday = Time.MondayOnOrBefore(timeZone, Time.LocalDate(timeZone, now));
        long total = 0;
        foreach (var project in projects)
        {
            foreach (var day in project.ByDay)
            {
                var date = ReportDates.ParseDay(day.Day);
                if (date is null || date.Value < monday) continue;
                total += day.Tokens;
            }
        }
        return total;
    }
}
