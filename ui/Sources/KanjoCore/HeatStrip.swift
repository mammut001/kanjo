import Foundation

// 8 周燃烧热力条：把 by_day 按周（周一到周日）累加。纯函数，不依赖 SwiftUI。

/// 一周的花费：总额 + 各 agent 之和（缺 by_agent 的天记到回退 agent）。
public struct WeekCost: Equatable {
    public var start: Date
    public var cost: Double
    public var byAgent: [String: Double]

    public init(start: Date, cost: Double, byAgent: [String: Double]) {
        self.start = start
        self.cost = cost
        self.byAgent = byAgent
    }

    /// 按 cost 降序（相同 cost 按 key 排，保证稳定）。
    public var ranked: [(agent: String, cost: Double)] {
        byAgent.map { (agent: $0.key, cost: $0.value) }
            .sorted { $0.cost != $1.cost ? $0.cost > $1.cost : $0.agent < $1.agent }
    }

    /// 那周花费最多的 agent；没有正花费时为 nil。
    public var topAgent: String? {
        ranked.first.flatMap { $0.cost > 0 ? $0.agent : nil }
    }
}

public enum HeatStrip {
    public static let defaultWeeks = 8
    public static let levels = 5

    /// 结束日期所在周（周一开始）往前共 `weeks` 周的起始日（本地零点），最早的在前。
    public static func weekStarts(endingOn end: Date, weeks: Int = defaultWeeks,
                                  calendar: Calendar = .current) -> [Date] {
        guard weeks > 0 else { return [] }
        let day = calendar.startOfDay(for: end)
        // weekday：周日 = 1 … 周六 = 7；换算成「距本周一的天数」。
        let offset = (calendar.component(.weekday, from: day) + 5) % 7
        guard let monday = calendar.date(byAdding: .day, value: -offset, to: day) else { return [] }
        return (0..<weeks).compactMap { i in
            calendar.date(byAdding: .day, value: -7 * (weeks - 1 - i), to: monday)
        }
    }

    /// 最近 `weeks` 周每周的花费及其按 agent 的拆分，最早的周在前。窗口外（更早或结束周之后）的日子被丢弃。
    /// 某天缺 `by_agent`（旧数据）或为空时，那天的 cost 全部记到 `fallbackAgent`（项目级主力 agent）。
    public static func weekly(_ days: [DayCost], endingOn end: Date, weeks: Int = defaultWeeks,
                              fallbackAgent: String, calendar: Calendar = .current) -> [WeekCost] {
        let starts = weekStarts(endingOn: end, weeks: weeks, calendar: calendar)
        var out = starts.map { WeekCost(start: $0, cost: 0, byAgent: [:]) }
        guard let first = starts.first else { return out }
        for d in days {
            guard let date = parseDay(d.day, calendar: calendar) else { continue }
            guard let n = calendar.dateComponents([.day], from: first, to: date).day, n >= 0 else { continue }
            let idx = n / 7
            guard idx < out.count else { continue }
            out[idx].cost += d.cost
            if let split = d.byAgent, !split.isEmpty {
                for (agent, cost) in split { out[idx].byAgent[agent, default: 0] += cost }
            } else {
                out[idx].byAgent[fallbackAgent, default: 0] += d.cost
            }
        }
        return out
    }

    /// 一格的纵向色带：按 cost 降序最多 `maxSegments` 段，份额小于 `minShare` 的（以及超出段数的）
    /// 并进最大的那段，避免出碎条。份额之和为 1；没有正花费时为空。
    public static func segments(_ week: WeekCost, minShare: Double = 0.1,
                                maxSegments: Int = 3) -> [(agent: String, share: Double)] {
        let ranked = week.ranked.filter { $0.cost > 0 }
        let total = ranked.reduce(0) { $0 + $1.cost }
        guard total > 0, maxSegments > 0 else { return [] }
        var out: [(agent: String, share: Double)] = []
        var merged = 0.0
        for (i, a) in ranked.enumerated() {
            let share = a.cost / total
            if i == 0 || (share >= minShare && out.count < maxSegments) {
                out.append((a.agent, share))
            } else {
                merged += share
            }
        }
        out[0].share += merged
        return out
    }

    /// 深浅档位：0 = 无花费；1…levels-1 按 value / max 等分（向上取整）。
    public static func level(_ value: Double, max: Double, levels: Int = levels) -> Int {
        guard value > 0, max > 0, levels > 1 else { return 0 }
        let steps = Double(levels - 1)
        let r = Swift.min(value / max, 1)
        return Swift.min(Swift.max(Int((r * steps).rounded(.up)), 1), levels - 1)
    }

    /// "Oct 13–19"；跨月 "Sep 29–Oct 5"；跨年 "Dec 29, 2025–Jan 4, 2026"。
    public static func weekLabel(start: Date, calendar: Calendar = .current) -> String {
        guard let end = calendar.date(byAdding: .day, value: 6, to: start) else { return "" }
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.currentLanguage)
        f.calendar = calendar
        f.timeZone = calendar.timeZone
        let c0 = calendar.dateComponents([.year, .month], from: start)
        let c1 = calendar.dateComponents([.year, .month], from: end)
        if c0.year != c1.year {
            f.setLocalizedDateFormatFromTemplate("yMMMd")
            return "\(f.string(from: start))–\(f.string(from: end))"
        }
        f.setLocalizedDateFormatFromTemplate("MMMd")
        let a = f.string(from: start)
        if c0.month != c1.month { return "\(a)–\(f.string(from: end))" }
        let dFormatter = DateFormatter()
        dFormatter.locale = Locale(identifier: L10n.currentLanguage)
        dFormatter.calendar = calendar
        dFormatter.timeZone = calendar.timeZone
        dFormatter.setLocalizedDateFormatFromTemplate("d")
        return "\(a)–\(dFormatter.string(from: end))"
    }

    /// "YYYY-MM-DD" → 该日在 `calendar` 时区的零点。
    static func parseDay(_ s: String, calendar: Calendar) -> Date? {
        let parts = s.split(separator: "-")
        guard parts.count == 3, let y = Int(parts[0]), let m = Int(parts[1]), let d = Int(parts[2]) else { return nil }
        return calendar.date(from: DateComponents(year: y, month: m, day: d))
    }
}
