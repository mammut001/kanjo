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

    /// token：k / M / B 缩写，一位小数。
    public static func tokens(_ n: Int) -> String {
        let v = Double(abs(n))
        let sign = n < 0 ? "-" : ""
        if v < 1000 { return sign + String(Int(v)) }
        let units: [(Double, String)] = [(1e3, "k"), (1e6, "M"), (1e9, "B")]
        for (i, (base, suffix)) in units.enumerated() {
            let scaled = v / base
            let rounded = (scaled * 10).rounded() / 10
            if rounded < 1000 || i == units.count - 1 {
                return sign + String(format: "%.1f", rounded) + suffix
            }
        }
        return sign + String(Int(v))
    }

    /// 月费：`$100/mo`。整数美元不带小数；价格未知时为「—」。
    public static func perMonth(_ v: Double?, currency: String = "USD") -> String {
        guard let v, v.isFinite else { return "—" }
        if currency.uppercased() == "USD", v == v.rounded(), abs(v) < 1e12 {
            return "$\(Int(v.rounded()))/mo"
        }
        return money(v, currency: currency) + "/mo"
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
              let end = ReportDates.parseTimestamp(sub.cycleEnd) else { return "Cycle dates unavailable" }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = timezone
        f.dateFormat = "MMM d"
        return "\(f.string(from: start)) – \(f.string(from: end))"
    }

    public static func renewal(_ cycleEnd: String, timezone: TimeZone, now: Date = Date()) -> String {
        guard let end = ReportDates.parseTimestamp(cycleEnd) else { return "Renewal date unavailable" }
        let cal = RangeEngine.calendar(timezone: timezone)
        let days = cal.dateComponents([.day], from: cal.startOfDay(for: now), to: cal.startOfDay(for: end)).day ?? 0
        switch days {
        case ..<0: return "renewal date passed"
        case 0: return "renews today"
        case 1: return "renews tomorrow"
        default: return "renews in \(days) days"
        }
    }

    public static func cycleCaption(_ sub: Subscription, timezone: TimeZone, now: Date = Date()) -> String {
        if SubscriptionValue.needsRenewalDay(sub) {
            return "Last 30 days · set renewal day for exact cycle"
        }
        return cycleDates(sub, timezone: timezone) + " · " + renewal(sub.cycleEnd, timezone: timezone, now: now)
    }

    public static func cycleRangeCaption(_ sub: Subscription, timezone: TimeZone) -> String {
        if SubscriptionValue.needsRenewalDay(sub) {
            return "\(sub.planLabel) · last 30 days (day not set)"
        }
        guard let start = ReportDates.parseTimestamp(sub.cycleStart) else { return sub.planLabel }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = timezone
        f.dateFormat = "MMM d"
        return "\(sub.planLabel) since \(f.string(from: start))"
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
        return shortDay.string(from: d)
    }

    /// ISO 时间戳 → 本地 "yyyy-MM-dd HH:mm"。
    public static func timestamp(_ s: String) -> String {
        guard let d = ReportDates.parseTimestamp(s) else { return s }
        return dateTime.string(from: d)
    }

    public static func clock(_ d: Date) -> String { time.string(from: d) }
}
