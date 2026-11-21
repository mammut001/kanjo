import XCTest
@testable import KanjoCore

/// 「本周 token」与热力条按报告时区的公历划周，不受本机日历 / 时区影响。
final class PanelDataCalendarTests: KanjoTestCase {
    private var priorZone: TimeZone!

    override func setUp() {
        super.setUp()
        priorZone = NSTimeZone.default
    }

    override func tearDown() {
        NSTimeZone.default = priorZone
        super.tearDown()
    }

    func testWeeklyTokensAndHeatUseReportCalendar() throws {
        var report = try ReportDecoder.decode(Data(contentsOf: DefaultPaths.sampleFixture))
        report.timezone = "America/Los_Angeles"
        // 报告时区的周一 00:30；本机（UTC-11）此刻还是周日晚上。
        report.generatedAt = "2026-11-16T08:30:00Z"
        for i in report.projects.indices { report.projects[i].byDay = [] }
        report.projects[0].byDay = [
            DayCost(day: "2026-11-15", cost: 50, tokens: 5000),
            DayCost(day: "2026-11-16", cost: 5, tokens: 500),
        ]
        NSTimeZone.default = TimeZone(identifier: "Pacific/Pago_Pago")!

        let now = ReportDates.parseTimestamp(report.generatedAt)!
        let data = try XCTUnwrap(PanelData.compute(report: report, rangeRaw: "all", now: now))
        let cal = RangeEngine.calendar(timezone: TimeZone(identifier: "America/Los_Angeles")!)
        XCTAssertEqual(data.weeklyTokens, 500)
        let p = report.projects[0]
        let expected = HeatStrip.weekly(p.byDay, endingOn: now, fallbackAgent: RangeEngine.fallbackAgent(for: p), calendar: cal)
        XCTAssertEqual(data.heatWeeks[p.id], expected)
        XCTAssertEqual(data.heatWeeks[p.id]?.last?.tokens, 500)
    }

}
