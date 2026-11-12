using System.Globalization;

namespace Kanjo.Core;

/// <summary>清理时传给 `disk clean --older-than` 的档位，Any 不带这个参数。</summary>
public enum DiskAge
{
    Any,
    Days7,
    Days30,
    Days90,
}

public static class DiskAges
{
    public static readonly IReadOnlyList<DiskAge> All = [DiskAge.Any, DiskAge.Days7, DiskAge.Days30, DiskAge.Days90];

    public static string Label(this DiskAge age) => age switch
    {
        DiskAge.Any => L10n.Tr("disk.age.any"),
        DiskAge.Days7 => L10n.Tr("disk.age.7d"),
        DiskAge.Days30 => L10n.Tr("disk.age.30d"),
        _ => L10n.Tr("disk.age.90d"),
    };

    public static string? Argument(this DiskAge age) => age == DiskAge.Any ? null : age.Label();

    public static string Caption(this DiskAge age) => age == DiskAge.Any
        ? L10n.Tr("disk.age.caption.any")
        : L10n.TrL(null, "disk.age.caption.older", age.Label());
}

/// <summary>
/// 额度重置行的取值（QuotaResetSettingsRow）：把 `weekly_resets_at` 折成星期 key + HH:mm，
/// 以及提交给 CLI 的 `"mon 05:00"` 形式。
/// </summary>
public static class QuotaResetValue
{
    public static readonly IReadOnlyList<string> WeekdayKeys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

    /// <summary>`weekly_resets_at` →（星期 key，HH:mm）；没有额度信息时是（tue, 05:00）。</summary>
    public static (string Weekday, string Time) Parse(QuotaWindow? quota, TimeZoneInfo timezone)
    {
        if (quota is not null && ReportDates.ParseTimestamp(quota.WeeklyResetsAt) is { } date)
        {
            var local = TimeZoneInfo.ConvertTime(date, timezone);
            var key = local.DayOfWeek switch
            {
                DayOfWeek.Monday => "mon",
                DayOfWeek.Tuesday => "tue",
                DayOfWeek.Wednesday => "wed",
                DayOfWeek.Thursday => "thu",
                DayOfWeek.Friday => "fri",
                DayOfWeek.Saturday => "sat",
                _ => "sun",
            };
            return (key, local.ToString("HH:mm", CultureInfo.InvariantCulture));
        }
        return ("tue", "05:00");
    }

    /// <summary>下拉菜单里的时刻选项：每半小时一个，外加当前值。</summary>
    public static List<string> Times(string current)
    {
        var set = new SortedSet<string>(StringComparer.Ordinal);
        for (var hour = 0; hour < 24; hour++)
        {
            set.Add(hour.ToString("00", CultureInfo.InvariantCulture) + ":00");
            set.Add(hour.ToString("00", CultureInfo.InvariantCulture) + ":30");
        }
        set.Add(current);
        return set.ToList();
    }

    /// <summary>提交给 CLI 的值：`"mon 05:00"`。</summary>
    public static string Serialize(string weekday, string time) => $"{weekday} {time}";
}
