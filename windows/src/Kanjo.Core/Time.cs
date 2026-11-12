using System.Globalization;

namespace Kanjo.Core;

/// <summary>
/// 报告时区的公历日历运算（周一为一周开始）。对应 Swift 版 RangeEngine.calendar(timezone:)。
/// 所有日期都按报告时区的本地自然日推进，跨夏令时也按日历周/天移动，不会 168 小时硬加。
/// </summary>
public static class Time
{
    public static TimeZoneInfo Zone(TimeZoneInfo timezone) => timezone;

    /// <summary>报告时区的公历日历（周一为一周开始）。</summary>
    public static Calendar Calendar(TimeZoneInfo timezone) =>
        new GregorianCalendar { TwoDigitYearMax = 2049 };

    public static DateTimeOffset StartOfDay(TimeZoneInfo tz, DateTimeOffset instant)
    {
        var local = TimeZoneInfo.ConvertTime(instant, tz);
        var date = local.Date;
        return FromLocal(tz, date);
    }

    /// <summary>本地日期（00:00）→ 该时区下的时刻。</summary>
    public static DateTimeOffset FromLocal(TimeZoneInfo tz, DateTime local)
    {
        var unspecified = DateTime.SpecifyKind(local, DateTimeKind.Unspecified);
        var utc = TimeZoneInfo.ConvertTimeToUtc(unspecified, tz);
        return new DateTimeOffset(utc, TimeSpan.Zero);
    }

    public static DateTimeOffset AddDays(TimeZoneInfo tz, DateTimeOffset instant, int days)
    {
        var local = TimeZoneInfo.ConvertTime(instant, tz);
        return FromLocal(tz, local.Date.AddDays(days).Add(local.TimeOfDay));
    }

    /// <summary>按日历周移动（保持本地钟点与星期几），用于 168 小时窗口的 DST 处理。</summary>
    public static DateTimeOffset AddWeeks(TimeZoneInfo tz, DateTimeOffset instant, int weeks)
    {
        var local = TimeZoneInfo.ConvertTime(instant, tz);
        return FromLocal(tz, local.Date.AddDays(7 * weeks).Add(local.TimeOfDay));
    }

    public static DateTimeOffset AddHours(TimeZoneInfo tz, DateTimeOffset instant, double hours) =>
        instant.AddHours(hours);

    /// <summary>DateOnly → 本地零点时刻。</summary>
    public static DateTimeOffset AtDay(TimeZoneInfo tz, DateOnly day) =>
        FromLocal(tz, day.ToDateTime(TimeOnly.MinValue));

    /// <summary>距本周一的天数：周日 = 1 … 周六 = 7 → 0…6。</summary>
    public static int MondayOffset(DateOnly day)
    {
        var weekday = (int)day.DayOfWeek; // Sunday = 0
        return (weekday + 6) % 7;
    }

    public static DateOnly MondayOnOrBefore(TimeZoneInfo tz, DateOnly day)
    {
        var local = day;
        return local.AddDays(-MondayOffset(local));
    }

    public static DateOnly LocalDate(TimeZoneInfo tz, DateTimeOffset instant) =>
        DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(instant, tz).Date);

    /// <summary>本地自然日相差的天数（b - a）。</summary>
    public static int DaysBetween(TimeZoneInfo tz, DateTimeOffset a, DateTimeOffset b)
    {
        var da = LocalDate(tz, a);
        var db = LocalDate(tz, b);
        return db.DayNumber - da.DayNumber;
    }

    /// <summary>时刻 → 该时区下的 "YYYY-MM-DD"。</summary>
    public static string DayString(TimeZoneInfo tz, DateTimeOffset instant)
    {
        var d = LocalDate(tz, instant);
        return DayString(d);
    }

    public static string DayString(DateOnly d) =>
        d.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
}
