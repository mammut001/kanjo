using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 视图层的短日期：同一年省略年份，今天 / 昨天用相对说法。只用于展示，不改数据。
/// <see cref="ReferenceNow"/> 留空时用本机时间；截图模式设成报告的 generated_at，保证图片可复现。
/// </summary>
public static class ShortDate
{
    public static DateTimeOffset? ReferenceNow { get; set; }

    private static DateTimeOffset Now => ReferenceNow ?? DateTimeOffset.Now;

    /// <summary>"Oct 23"（今年）或 "Oct 23, 2025"。</summary>
    public static string Day(string? s)
    {
        if (s is null) return "—";
        var d = ReportDates.ParseDay(s);
        if (d is null) return Fmt.Day(s);
        return d.Value.Year == Now.LocalDateTime.Year
            ? Fmt.MonthDay(Time.AtDay(TimeZoneInfo.Local, d.Value), TimeZoneInfo.Local, null)
            : Fmt.Day(s);
    }

    /// <summary>"today" / "yesterday" / Day()。</summary>
    public static string Relative(string? s)
    {
        if (s is null) return "—";
        var d = ReportDates.ParseDay(s);
        if (d is null) return Fmt.Day(s);
        var today = DateOnly.FromDateTime(Now.LocalDateTime);
        if (d.Value == today) return L10n.Tr("common.today");
        if (d.Value == today.AddDays(-1)) return L10n.Tr("common.yesterday");
        return Day(s);
    }

    /// <summary>
    /// "Jun 28 – Oct 23, 2026"；跨年时两端都带年份。compact 时两端都在今年就连年份也省掉。
    /// 首尾同一天时只显示单日。
    /// </summary>
    public static string Range(string? a, string? b, bool compact = false)
    {
        if (a is null || b is null || ReportDates.ParseDay(a) is not { } da || ReportDates.ParseDay(b) is not { } db)
        {
            return a == b ? Fmt.Day(a) : $"{Fmt.Day(a)} – {Fmt.Day(b)}";
        }
        if (da == db) return compact ? Day(a) : Fmt.Day(a);

        var thisYear = Now.LocalDateTime.Year;
        if (compact && da.Year == thisYear && db.Year == thisYear)
        {
            return $"{Fmt.MonthDay(Time.AtDay(TimeZoneInfo.Local, da), TimeZoneInfo.Local, null)} – " +
                   $"{Fmt.MonthDay(Time.AtDay(TimeZoneInfo.Local, db), TimeZoneInfo.Local, null)}";
        }
        if (da.Year == db.Year) return $"{Day(a)} – {Fmt.Day(b)}";
        return $"{Fmt.Day(a)} – {Fmt.Day(b)}";
    }

    public static string Clock(DateTimeOffset d) => d.ToLocalTime().ToString("HH:mm");
}
