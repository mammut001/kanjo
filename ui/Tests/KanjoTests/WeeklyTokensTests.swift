import XCTest
@testable import KanjoCore

/// 本周 token：周一边界、周日深夜、旧报告、空数据。日期全部写死。
final class WeeklyTokensTests: KanjoTestCase {
    private func calendar(_ id: String, firstWeekday: Int = 1) -> Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: id)!
        c.locale = Locale(identifier: "en_US_POSIX")
        // 1 = 周日。旧算法用 yearForWeekOfYear，周日深夜会落到下一周的周一。
        c.firstWeekday = firstWeekday
        return c
    }

    private func iso(_ s: String) -> Date {
        ReportDates.parseTimestamp(s)!
    }

    private func project(_ id: String, _ days: [(String, Int)]) -> Project {
        Project(id: id, name: id, remote: nil, paths: [], pathMissing: false,
                cost: 0, tokens: .zero, sessions: 0,
                byAgent: [], byModel: [],
                byDay: days.map { DayCost(day: $0.0, cost: 0, tokens: $0.1) },
                byBranch: [], sessionsDetail: [])
    }

    private func since(_ now: Date, _ projects: [Project], _ calendar: Calendar) -> Int {
        WeeklyTokens.since(mondayOfWeekContaining: now, projects: projects, calendar: calendar)
    }

    /// 上海时间 2026-10-19 00:00 整点翻周：前一秒仍算 10-12 那周。
    func testMondayBoundary() {
        let cal = calendar("Asia/Shanghai")
        let projects = [
            project("a", [("2026-10-11", 1), ("2026-10-12", 10), ("2026-10-18", 20)]),
            project("b", [("2026-10-19", 40), ("2026-10-23", 7), ("nope", 100)]),
        ]
        let monday = iso("2026-10-18T16:00:00Z")       // Mon Oct 19 00:00 CST
        let justBefore = iso("2026-10-18T15:59:59Z")   // Sun Oct 18 23:59:59 CST
        XCTAssertEqual(since(monday, projects, cal), 47)
        XCTAssertEqual(since(justBefore, projects, cal), 77)
    }

    /// 周日 23:59 仍属于上周一开的那周，不会从下一个周一开始。
    func testSundayNight() {
        let cal = calendar("UTC")
        let projects = [project("a", [
            ("2026-10-18", 5),   // 上一周的周日
            ("2026-10-19", 7),   // 本周一
            ("2026-10-25", 11),  // 本周日
        ])]
        let sundayNight = iso("2026-10-25T23:59:59Z")
        XCTAssertEqual(since(sundayNight, projects, cal), 18)
        XCTAssertEqual(calendar("UTC").component(.weekday, from: sundayNight), 1)
    }

    /// 报告比墙钟旧：按生成时间那一周算，不按「现在」算成 0。
    func testOldReportUsesGeneratedAt() {
        let cal = calendar("UTC")
        let now = iso("2026-11-20T08:00:00Z")
        let generated = iso("2026-10-23T02:00:00Z")
        let projects = [project("a", [
            ("2026-10-18", 100),  // 报告那周的周一之前
            ("2026-10-20", 200),
            ("2026-10-23", 300),
        ])]
        let reference = WeeklyTokens.reference(now: now, generatedAt: generated)
        XCTAssertEqual(reference, generated)
        XCTAssertEqual(since(reference, projects, cal), 500)
        // 同一份旧数据按墙钟（11 月）算是 0。
        XCTAssertEqual(since(now, projects, cal), 0)
        XCTAssertEqual(WeeklyTokens.reference(now: now, generatedAt: iso("2026-11-21T00:00:00Z")), now)
        XCTAssertEqual(WeeklyTokens.reference(now: now, generatedAt: nil), now)
        XCTAssertEqual(WeeklyTokens.reference(now: now, generatedAt: now), now)
    }

    func testEmpty() {
        let cal = calendar("UTC")
        let now = iso("2026-10-23T02:00:00Z")
        XCTAssertEqual(since(now, [], cal), 0)
        XCTAssertEqual(since(now, [project("a", [])], cal), 0)
        XCTAssertEqual(since(now, [project("a", [("garbage", 50), ("2026-10-18", 9)])], cal), 0)
    }
}
