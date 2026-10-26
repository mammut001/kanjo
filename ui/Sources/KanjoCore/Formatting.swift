import Foundation

public enum Fmt {
    /// 金额：0 < v < 0.01 显示 "<$0.01"，其余两位小数并带千分位。
    public static func money(_ v: Double, currency: String = "USD") -> String {
        let symbol = currency.uppercased() == "USD" ? "$" : currency.uppercased() + " "
        if v > 0 && v < 0.01 { return "<\(symbol)0.01" }
        if v < 0 && v > -0.01 { return "-<\(symbol)0.01" }
        let f = NumberFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.numberStyle = .decimal
        f.usesGroupingSeparator = true
        f.groupingSeparator = ","
        f.groupingSize = 3
        f.minimumFractionDigits = 2
        f.maximumFractionDigits = 2
        f.roundingMode = .halfUp
        let body = f.string(from: NSNumber(value: abs(v))) ?? String(format: "%.2f", abs(v))
        return (v < 0 ? "-" : "") + symbol + body
    }

    /// 菜单栏金额：< 100 两位小数（如 `<$0.01`、`$12.34`）；100..<10,000 不带小数并带千分位（`$3,057`）；>= 10,000 紧凑 K/M 一位小数并去尾部 `.0`（`$12.3K`、`$10K`、`$1.2M`）。
    public static func menuBarMoney(_ v: Double, currency: String = "USD") -> String {
        let mag = abs(v)
        let symbol = currency.uppercased() == "USD" ? "$" : currency.uppercased() + " "
        let sign = v < 0 ? "-" : ""

        if mag < 100 {
            return money(v, currency: currency)
        } else if mag.rounded() < 10_000 {
            let f = NumberFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.numberStyle = .decimal
            f.usesGroupingSeparator = true
            f.groupingSeparator = ","
            f.groupingSize = 3
            f.minimumFractionDigits = 0
            f.maximumFractionDigits = 0
            f.roundingMode = .halfUp
            let body = f.string(from: NSNumber(value: mag.rounded())) ?? String(Int(mag.rounded()))
            return sign + symbol + body
        } else {
            let units: [(Double, String)] = [(1e3, "K"), (1e6, "M"), (1e9, "B"), (1e12, "T")]
            for (i, (base, suffix)) in units.enumerated() {
                let scaled = mag / base
                let rounded = (scaled * 10).rounded() / 10
                if rounded < 1000 || i == units.count - 1 {
                    let s = String(format: "%.1f", locale: Locale(identifier: "en_US_POSIX"), rounded)
                    let body = s.hasSuffix(".0") ? String(s.dropLast(2)) : s
                    return sign + symbol + body + suffix
                }
            }
            return sign + symbol + String(Int(mag))
        }
    }

    /// token：按语言本地化单位。
    /// en: k / M / B 缩写，一位小数（如 1.0k、12.3k、188.0M、23.5B）。
    /// zh-Hans: 万 / 亿 / 万亿 进位，<10,000 无分组纯数字，一位小数去尾部 .0（如 9999、1.2万、1.9亿、235亿、1.2万亿）。
    /// fr: k / M / Md 缩写，逗号小数，单位前无空格，去尾部 ,0（如 12,3k、188M、23,5Md）。
    public static func tokens(_ n: Int) -> String {
        tokens(n, language: L10n.currentLanguage)
    }

    public static func tokens(_ n: Int, language: String) -> String {
        let v = abs(Double(n))
        let sign = n < 0 ? "-" : ""

        if language.hasPrefix("zh") {
            if v < 10_000 { return sign + String(Int(v)) }
            let units: [(Double, String)] = [(1e4, "万"), (1e8, "亿"), (1e12, "万亿")]
            for (i, (base, suffix)) in units.enumerated() {
                let scaled = v / base
                let rounded = (scaled * 10).rounded() / 10
                if rounded < 10_000 || i == units.count - 1 {
                    let s = String(format: "%.1f", locale: Locale(identifier: "en_US_POSIX"), rounded)
                    let body = s.hasSuffix(".0") ? String(s.dropLast(2)) : s
                    return sign + body + suffix
                }
            }
            return sign + String(Int(v))
        } else if language.hasPrefix("fr") {
            if v < 1000 { return sign + String(Int(v)) }
            let units: [(Double, String)] = [(1e3, "k"), (1e6, "M"), (1e9, "Md")]
            for (i, (base, suffix)) in units.enumerated() {
                let scaled = v / base
                let rounded = (scaled * 10).rounded() / 10
                if rounded < 1000 || i == units.count - 1 {
                    let s = String(format: "%.1f", locale: Locale(identifier: "en_US_POSIX"), rounded)
                    let withComma = s.replacingOccurrences(of: ".", with: ",")
                    let body = withComma.hasSuffix(",0") ? String(withComma.dropLast(2)) : withComma
                    return sign + body + suffix
                }
            }
            return sign + String(Int(v))
        } else {
            if v < 1000 { return sign + String(Int(v)) }
            let units: [(Double, String)] = [(1e3, "k"), (1e6, "M"), (1e9, "B")]
            for (i, (base, suffix)) in units.enumerated() {
                let scaled = v / base
                let rounded = (scaled * 10).rounded() / 10
                if rounded < 1000 || i == units.count - 1 {
                    return sign + String(format: "%.1f", locale: Locale(identifier: "en_US_POSIX"), rounded) + suffix
                }
            }
            return sign + String(Int(v))
        }
    }

    /// 月费：`$100/mo`。整数美元不带小数；价格未知时为「—」。
    public static func perMonth(_ v: Double?, currency: String = "USD") -> String {
        guard let v, v.isFinite else { return "—" }
        let suffix = L10n.tr("fmt.per_month_suffix")
        if currency.uppercased() == "USD", v == v.rounded(), abs(v) < 1e12 {
            return "$\(Int(v.rounded()))" + suffix
        }
        return money(v, currency: currency) + suffix
    }

    /// 字节：1000 进位，B / KB / MB / GB / TB。一位小数，去掉末尾的 `.0`（`1.1 GB`、`626 MB`）。
    public static func bytes(_ n: Int) -> String {
        let sign = n < 0 ? "-" : ""
        let v = Double(abs(n))
        if v < 1000 { return sign + String(Int(v.rounded(.towardZero))) + " B" }
        let units: [(Double, String)] = [(1e3, "KB"), (1e6, "MB"), (1e9, "GB"), (1e12, "TB"), (1e15, "PB")]
        for (i, (base, suffix)) in units.enumerated() {
            let scaled = v / base
            let rounded = (scaled * 10).rounded() / 10
            if rounded < 1000 || i == units.count - 1 {
                let body = rounded == rounded.rounded()
                    ? String(Int(rounded))
                    : String(format: "%.1f", locale: Locale(identifier: "en_US_POSIX"), rounded)
                return sign + body + " " + suffix
            }
        }
        return sign + String(Int(v)) + " B"
    }

    /// 用量 ÷ 月费，一位小数：`15.7×`。算不出来（月费为空或不是正数）时为「—」。
    public static func multiple(_ m: Double?) -> String {
        guard let m, m.isFinite else { return "—" }
        return String(format: "%.1f×", locale: Locale(identifier: "en_US_POSIX"), m)
    }

    public static func percent(_ share: Double) -> String {
        let p = share * 100
        if p >= 99.95 { return "100%" }
        if p < 1 { return String(format: "%.1f%%", p) }
        return String(format: "%.0f%%", p)
    }

    /// 账期时间戳按报告时区显示；倒计时按自然日计算，跨夏令时也不会少一天。
    public static func cycleDates(_ sub: Subscription, timezone: TimeZone) -> String {
        guard let start = ReportDates.parseTimestamp(sub.cycleStart),
              let end = ReportDates.parseTimestamp(sub.cycleEnd) else { return L10n.tr("fmt.cycle_dates_unavailable") }
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.currentLanguage)
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = timezone
        f.setLocalizedDateFormatFromTemplate("MMMd")
        return "\(f.string(from: start)) – \(f.string(from: end))"
    }

    public static func renewal(_ cycleEnd: String, timezone: TimeZone, now: Date = Date()) -> String {
        guard let end = ReportDates.parseTimestamp(cycleEnd) else { return L10n.tr("fmt.renewal_date_unavailable") }
        let cal = RangeEngine.calendar(timezone: timezone)
        let days = cal.dateComponents([.day], from: cal.startOfDay(for: now), to: cal.startOfDay(for: end)).day ?? 0
        switch days {
        case ..<0: return L10n.tr("fmt.renewal_date_passed")
        case 0: return L10n.tr("fmt.renews_today")
        case 1: return L10n.tr("fmt.renews_tomorrow")
        default: return L10n.tr("fmt.renews_in_days", days)
        }
    }

    public static func cycleCaption(_ sub: Subscription, timezone: TimeZone, now: Date = Date()) -> String {
        if SubscriptionValue.needsRenewalDay(sub) {
            return L10n.tr("fmt.cycle_needs_renewal_day")
        }
        return cycleDates(sub, timezone: timezone) + " · " + renewal(sub.cycleEnd, timezone: timezone, now: now)
    }

    public static func cycleRangeCaption(_ sub: Subscription, timezone: TimeZone) -> String {
        if SubscriptionValue.needsRenewalDay(sub) {
            return L10n.tr("fmt.cycle_range_needs_renewal_day", sub.planLabel)
        }
        guard let start = ReportDates.parseTimestamp(sub.cycleStart) else { return sub.planLabel }
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.currentLanguage)
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = timezone
        f.setLocalizedDateFormatFromTemplate("MMMd")
        return L10n.tr("fmt.cycle_range_since", sub.planLabel, f.string(from: start))
    }

    private static let shortDay: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MMM d, yyyy"
        return f
    }()
    private static let dateTime: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd HH:mm"
        return f
    }()
    private static let time: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    /// "2026-10-22" → "Oct 22, 2026"；nil 或无法解析时原样/占位。
    public static func day(_ s: String?) -> String {
        guard let s else { return "—" }
        guard let d = ReportDates.parseDay(s) else { return s }
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.currentLanguage)
        f.calendar = Calendar(identifier: .gregorian)
        f.setLocalizedDateFormatFromTemplate("yMMMd")
        return f.string(from: d)
    }

    /// ISO 时间戳 → 本地 "yyyy-MM-dd HH:mm"。
    public static func timestamp(_ s: String) -> String {
        guard let d = ReportDates.parseTimestamp(s) else { return s }
        return dateTime.string(from: d)
    }

    public static func clock(_ d: Date) -> String { time.string(from: d) }
}

/// 菜单栏文本生成器：纯逻辑，方便测试。
public enum MenuBarText {
    /// 菜单栏文本（金额）：金额优先，固定窗口显示后缀（如 `$3,057 · 30d`）；其他范围无后缀。
    public static func make(cost: Double, currency: String = "USD", range: TimeRange) -> String {
        let amount = Fmt.menuBarMoney(cost, currency: currency)
        guard let suffix = range.menuBarSuffix, !suffix.isEmpty else {
            return amount
        }
        return "\(amount) · \(suffix)"
    }

    /// 菜单栏文本（Token）：Token 优先，固定窗口显示后缀（如 `23.5B · 30d`）；其他范围无后缀。
    public static func make(tokens: Int, range: TimeRange, language: String? = nil) -> String {
        let formatted = language.map { Fmt.tokens(tokens, language: $0) } ?? Fmt.tokens(tokens)
        guard let suffix = range.menuBarSuffix, !suffix.isEmpty else {
            return formatted
        }
        return "\(formatted) · \(suffix)"
    }

    /// 统一入口，支持按模式格式化。
    public static func make(mode: MenuBarMode, cost: Double, tokens: Int, currency: String = "USD", range: TimeRange, language: String? = nil) -> String {
        switch mode {
        case .cost:
            return make(cost: cost, currency: currency, range: range)
        case .tokens:
            return make(tokens: tokens, range: range, language: language)
        }
    }
}
