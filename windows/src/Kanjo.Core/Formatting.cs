using System.Globalization;
using System.Text;

namespace Kanjo.Core;

/// <summary>金额 / token / 字节等格式化。逐条对应 Mac 版 `Fmt`。</summary>
public static class Fmt
{
    private static readonly CultureInfo Posix = CultureInfo.InvariantCulture;

    private static string Symbol(string currency) =>
        currency.ToUpperInvariant() == "USD" ? "$" : currency.ToUpperInvariant() + " ";

    /// <summary>金额：0 &lt; v &lt; 0.01 显示 "&lt;$0.01"，其余两位小数并带千分位。</summary>
    public static string Money(double v, string currency = "USD")
    {
        var symbol = Symbol(currency);
        if (v > 0 && v < 0.01) return $"<{symbol}0.01";
        if (v < 0 && v > -0.01) return $"-<{symbol}0.01";
        var body = Math.Round(Math.Abs(v), 2, MidpointRounding.AwayFromZero)
            .ToString("#,##0.00", Posix);
        return (v < 0 ? "-" : "") + symbol + body;
    }

    /// <summary>
    /// 菜单栏 / 托盘金额：&lt; 100 两位小数；100..&lt;10,000 不带小数并带千分位；&gt;= 10,000 紧凑 K/M 一位小数并去尾部 .0。
    /// </summary>
    public static string MenuBarMoney(double v, string currency = "USD")
    {
        var mag = Math.Abs(v);
        var symbol = Symbol(currency);
        var sign = v < 0 ? "-" : "";

        if (mag < 100)
        {
            return Money(v, currency);
        }
        if (Math.Round(mag, MidpointRounding.AwayFromZero) < 10_000)
        {
            var body = Math.Round(mag, MidpointRounding.AwayFromZero).ToString("#,##0", Posix);
            return sign + symbol + body;
        }

        (double Base, string Suffix)[] units = [(1e3, "K"), (1e6, "M"), (1e9, "B"), (1e12, "T")];
        for (var i = 0; i < units.Length; i++)
        {
            var (b, suffix) = units[i];
            var scaled = mag / b;
            var rounded = Math.Round(scaled * 10, MidpointRounding.AwayFromZero) / 10;
            if (rounded < 1000 || i == units.Length - 1)
            {
                var s = rounded.ToString("0.0", Posix);
                var body = s.EndsWith(".0", StringComparison.Ordinal) ? s[..^2] : s;
                return sign + symbol + body + suffix;
            }
        }
        return sign + symbol + ((long)mag).ToString(Posix);
    }

    /// <summary>token：按语言本地化单位（en: k/M/B；zh-Hans: 万/亿/万亿；fr: k/M/Md）。</summary>
    public static string Tokens(long n) => Tokens(n, L10n.CurrentLanguage);

    public static string Tokens(long n, string language)
    {
        var v = Math.Abs((double)n);
        var sign = n < 0 ? "-" : "";

        if (language.StartsWith("zh", StringComparison.Ordinal))
        {
            if (v < 10_000) return sign + ((long)v).ToString(Posix);
            (double Base, string Suffix)[] units = [(1e4, "万"), (1e8, "亿"), (1e12, "万亿")];
            for (var i = 0; i < units.Length; i++)
            {
                var (b, suffix) = units[i];
                var scaled = v / b;
                if (scaled >= 1000)
                {
                    var rounded = Math.Round(scaled, MidpointRounding.AwayFromZero);
                    if (rounded < 10_000 || i == units.Length - 1)
                    {
                        return sign + ((long)rounded).ToString(Posix) + suffix;
                    }
                    continue;
                }
                else
                {
                    var rounded = Math.Round(scaled * 10, MidpointRounding.AwayFromZero) / 10;
                    if (rounded >= 1000)
                    {
                        var roundedInt = Math.Round(scaled, MidpointRounding.AwayFromZero);
                        if (roundedInt < 10_000 || i == units.Length - 1)
                        {
                            return sign + ((long)roundedInt).ToString(Posix) + suffix;
                        }
                        continue;
                    }
                    if (rounded < 10_000 || i == units.Length - 1)
                    {
                        var s = rounded.ToString("0.0", Posix);
                        var body = s.EndsWith(".0", StringComparison.Ordinal) ? s[..^2] : s;
                        return sign + body + suffix;
                    }
                }
            }
            return sign + ((long)v).ToString(Posix);
        }

        if (language.StartsWith("fr", StringComparison.Ordinal))
        {
            if (v < 1000) return sign + ((long)v).ToString(Posix);
            (double Base, string Suffix)[] units = [(1e3, "k"), (1e6, "M"), (1e9, "Md")];
            for (var i = 0; i < units.Length; i++)
            {
                var (b, suffix) = units[i];
                var scaled = v / b;
                var rounded = Math.Round(scaled * 10, MidpointRounding.AwayFromZero) / 10;
                if (rounded < 1000 || i == units.Length - 1)
                {
                    var s = rounded.ToString("0.0", Posix).Replace('.', ',');
                    var body = s.EndsWith(",0", StringComparison.Ordinal) ? s[..^2] : s;
                    return sign + body + suffix;
                }
            }
            return sign + ((long)v).ToString(Posix);
        }

        {
            if (v < 1000) return sign + ((long)v).ToString(Posix);
            (double Base, string Suffix)[] units = [(1e3, "k"), (1e6, "M"), (1e9, "B")];
            for (var i = 0; i < units.Length; i++)
            {
                var (b, suffix) = units[i];
                var scaled = v / b;
                var rounded = Math.Round(scaled * 10, MidpointRounding.AwayFromZero) / 10;
                if (rounded < 1000 || i == units.Length - 1)
                {
                    return sign + rounded.ToString("0.0", Posix) + suffix;
                }
            }
            return sign + ((long)v).ToString(Posix);
        }
    }

    /// <summary>统一金额与 token 格式化："$12.34 · 1.2亿 token"。</summary>
    public static string CostAndTokens(double cost, long tokens, string currency = "USD", string? language = null)
    {
        var lang = language ?? L10n.CurrentLanguage;
        var c = Money(cost, currency);
        var t = L10n.TrL(lang, "overview.tokens_count", Tokens(tokens, lang));
        return $"{c} · {t}";
    }

    /// <summary>月费：`$100/mo`。整数美元不带小数；价格未知时为「—」。</summary>
    public static string PerMonth(double? v, string currency = "USD")
    {
        if (v is not { } value || double.IsNaN(value) || double.IsInfinity(value)) return "—";
        var suffix = L10n.Tr("fmt.per_month_suffix");
        if (currency.ToUpperInvariant() == "USD" && value == Math.Round(value) && Math.Abs(value) < 1e12)
        {
            return "$" + ((long)Math.Round(value)).ToString(Posix) + suffix;
        }
        return Money(value, currency) + suffix;
    }

    /// <summary>字节：1000 进位，B / KB / MB / GB / TB。一位小数，去掉末尾的 `.0`。</summary>
    public static string Bytes(long n)
    {
        var sign = n < 0 ? "-" : "";
        var v = (double)Math.Abs(n);
        if (v < 1000) return sign + ((long)Math.Truncate(v)).ToString(Posix) + " B";
        (double Base, string Suffix)[] units = [(1e3, "KB"), (1e6, "MB"), (1e9, "GB"), (1e12, "TB"), (1e15, "PB")];
        for (var i = 0; i < units.Length; i++)
        {
            var (b, suffix) = units[i];
            var scaled = v / b;
            var rounded = Math.Round(scaled * 10, MidpointRounding.AwayFromZero) / 10;
            if (rounded < 1000 || i == units.Length - 1)
            {
                var body = rounded == Math.Round(rounded, MidpointRounding.AwayFromZero)
                    ? ((long)rounded).ToString(Posix)
                    : rounded.ToString("0.0", Posix);
                return sign + body + " " + suffix;
            }
        }
        return sign + ((long)v).ToString(Posix) + " B";
    }

    /// <summary>用量 ÷ 月费，一位小数：`15.7×`。算不出来时为「—」。</summary>
    public static string Multiple(double? m)
    {
        if (m is not { } value || double.IsNaN(value) || double.IsInfinity(value)) return "—";
        return value.ToString("0.0", Posix) + "×";
    }

    public static string Percent(double share)
    {
        var p = share * 100;
        if (p >= 99.95) return "100%";
        if (p < 1) return p.ToString("0.0", Posix) + "%";
        return Math.Round(p, MidpointRounding.AwayFromZero).ToString("0", Posix) + "%";
    }

    /// <summary>账期时间戳按报告时区显示；倒计时按自然日计算，跨夏令时也不会少一天。</summary>
    public static string CycleDates(Subscription sub, TimeZoneInfo timezone) =>
        CycleDates(sub, timezone, L10n.CurrentLanguage);

    public static string CycleDates(Subscription sub, TimeZoneInfo timezone, string? language)
    {
        var start = ReportDates.ParseTimestamp(sub.CycleStart);
        var end = ReportDates.ParseTimestamp(sub.CycleEnd);
        if (start is null || end is null) return L10n.Tr("fmt.cycle_dates_unavailable");
        var lang = language ?? L10n.CurrentLanguage;
        var f = MonthDayFormatter(timezone, lang);
        return $"{f(start.Value)} – {f(end.Value)}";
    }

    public static string Renewal(string cycleEnd, TimeZoneInfo timezone, DateTimeOffset? now = null)
    {
        var end = ReportDates.ParseTimestamp(cycleEnd);
        if (end is null) return L10n.Tr("fmt.renewal_date_unavailable");
        var cal = Time.Zone(timezone);
        var n = now ?? DateTimeOffset.UtcNow;
        var days = Time.DaysBetween(cal, n, end.Value);
        return days switch
        {
            < 0 => L10n.Tr("fmt.renewal_date_passed"),
            0 => L10n.Tr("fmt.renews_today"),
            1 => L10n.Tr("fmt.renews_tomorrow"),
            _ => L10n.Tr("fmt.renews_in_days", days),
        };
    }

    public static string CycleCaption(Subscription sub, TimeZoneInfo timezone, DateTimeOffset? now = null)
    {
        if (SubscriptionValue.NeedsRenewalDay(sub)) return L10n.Tr("fmt.cycle_needs_renewal_day");
        return CycleDates(sub, timezone) + " · " + Renewal(sub.CycleEnd, timezone, now);
    }

    public static string CycleRangeCaption(Subscription sub, TimeZoneInfo timezone, string? language = null)
    {
        var lang = language ?? L10n.CurrentLanguage;
        if (SubscriptionValue.NeedsRenewalDay(sub))
        {
            return L10n.TrL(lang, "fmt.cycle_range_needs_renewal_day", sub.PlanLabel);
        }
        var start = ReportDates.ParseTimestamp(sub.CycleStart);
        if (start is null) return sub.PlanLabel;
        var f = MonthDayFormatter(timezone, lang);
        return L10n.TrL(lang, "fmt.cycle_range_since", sub.PlanLabel, f(start.Value));
    }

    /// <summary>"2026-10-22" → "Oct 22, 2026"；nil 或无法解析时原样/占位。</summary>
    public static string Day(string? s, string? language = null)
    {
        if (s is null) return "—";
        var d = ReportDates.ParseDay(s);
        if (d is null) return s;
        var lang = language ?? L10n.CurrentLanguage;
        var f = DayFormatter(lang);
        return f(d.Value.ToDateTime(TimeOnly.MinValue, DateTimeKind.Local));
    }

    /// <summary>ISO 时间戳 → 本地 "yyyy-MM-dd HH:mm"。</summary>
    public static string Timestamp(string s)
    {
        var d = ReportDates.ParseTimestamp(s);
        return d is null ? s : d.Value.ToLocalTime().ToString("yyyy-MM-dd HH:mm", Posix);
    }

    public static string Clock(DateTimeOffset d) => d.ToLocalTime().ToString("HH:mm:ss", Posix);

    // MARK: - 日期格式器（按语言本地化，与 DateFormatter 的 setLocalizedDateFormatFromTemplate 对齐）

    /// <summary>"Oct 23" / "10月23日" 这类月+日，按报告时区显示。</summary>
    public static string MonthDay(DateTimeOffset date, TimeZoneInfo timezone, string? language)
    {
        var lang = language ?? L10n.CurrentLanguage;
        return MonthDayFormatter(timezone, lang)(date);
    }

    internal static Func<DateTimeOffset, string> MonthDayFormatter(TimeZoneInfo timezone, string lang) => d =>
    {
        var local = TimeZoneInfo.ConvertTime(d, timezone);
        var culture = CultureFor(lang);
        var month = culture.DateTimeFormat.GetAbbreviatedMonthName(local.Month);
        if (lang.StartsWith("zh", StringComparison.Ordinal))
        {
            return $"{local.Month}月{local.Day}日";
        }
        return $"{month} {local.Day}";
    };

    internal static Func<DateTime, string> DayFormatter(string lang) => d =>
    {
        var culture = CultureFor(lang);
        if (lang.StartsWith("zh", StringComparison.Ordinal)) return $"{d.Year}年{d.Month}月{d.Day}日";
        var month = culture.DateTimeFormat.GetAbbreviatedMonthName(d.Month);
        return $"{month} {d.Day}, {d.Year}";
    };

    /// <summary>按语言取 CultureInfo（en / zh-Hans / fr），找不到就用不变文化。</summary>
    public static CultureInfo CultureFor(string? lang)
    {
        var l = lang ?? L10n.CurrentLanguage;
        try
        {
            if (l.StartsWith("zh", StringComparison.Ordinal)) return CultureInfo.GetCultureInfo("zh-Hans");
            if (l.StartsWith("fr", StringComparison.Ordinal)) return CultureInfo.GetCultureInfo("fr-FR");
            return CultureInfo.GetCultureInfo("en-US");
        }
        catch (CultureNotFoundException)
        {
            return CultureInfo.InvariantCulture;
        }
    }

    /// <summary>该语言的时刻格式（en 12 小时制 "5:05 PM"；zh / fr 24 小时制 "10:00"）。</summary>
    internal static string TimeOfDay(DateTimeOffset date, string lang)
    {
        var culture = CultureFor(lang);
        var pattern = culture.DateTimeFormat.ShortTimePattern;
        var uses24 = pattern.Contains('H');
        return date.ToString(uses24 ? "HH:mm" : "h:mm tt", culture);
    }

    /// <summary>星期几 + 时刻，例如 `周二 10:00` / `Sat 4:53 AM` / `sam. 10:00`。</summary>
    internal static string WeekdayTime(DateTimeOffset date, TimeZoneInfo timezone, string lang)
    {
        var local = TimeZoneInfo.ConvertTime(date, timezone);
        var culture = CultureFor(lang);
        var day = culture.DateTimeFormat.GetAbbreviatedDayName(local.DayOfWeek);
        return $"{day} {TimeOfDay(local, lang)}";
    }
}
