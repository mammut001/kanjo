import Foundation

/// 总览「本周 token」：从参考时刻所在周的周一 00:00 起，把各项目 `by_day` 的 token 加起来。
/// 一周固定从周一开始，不跟日历的 `firstWeekday` 走。纯函数，时区由传入的 `Calendar` 决定。
public enum WeeklyTokens {
    /// 参考时刻：报告生成时间比现在旧就用它，否则用现在。
    /// 样本数据和过期导出因此落在报告那一周，而不是按墙钟算出 0。
    public static func reference(now: Date, generatedAt: Date?) -> Date {
        guard let generatedAt, generatedAt < now else { return now }
        return generatedAt
    }

    /// `now` 所在周的周一 00:00（`calendar` 的时区）及之后的 token 之和。没有上界。
    public static func since(mondayOfWeekContaining now: Date, projects: [Project], calendar: Calendar) -> Int {
        let start = RangeEngine.mondayOnOrBefore(now, calendar: calendar)
        var total = 0
        for project in projects {
            for day in project.byDay {
                guard let date = HeatStrip.parseDay(day.day, calendar: calendar), date >= start else { continue }
                total += day.tokens
            }
        }
        return total
    }
}
