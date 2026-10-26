import XCTest
@testable import KanjoCore

final class HeatStripTests: KanjoTestCase {
    private var cal: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "UTC")!
        return c
    }()

    private func date(_ s: String) -> Date { HeatStrip.parseDay(s, calendar: cal)! }
    private func day(_ d: String, _ cost: Double, _ split: [String: Double]? = nil) -> DayCost {
        DayCost(day: d, cost: cost, tokens: 0, byAgent: split)
    }
    private func weekly(_ days: [DayCost], fallback: String = "claude") -> [WeekCost] {
        HeatStrip.weekly(days, endingOn: end, fallbackAgent: fallback, calendar: cal)
    }
    private func week(_ split: [String: Double]) -> WeekCost {
        WeekCost(start: end, cost: split.values.reduce(0, +), byAgent: split)
    }

    // 2026-10-24 是周六；它所在的周是 Oct 19 (Mon) – Oct 25 (Sun)。
    private var end: Date { date("2026-10-24") }

    func testWeekStartsAreMondaysOldestFirst() {
        let starts = HeatStrip.weekStarts(endingOn: end, calendar: cal)
        XCTAssertEqual(starts.count, 8)
        XCTAssertEqual(starts.last, date("2026-10-19"))
        XCTAssertEqual(starts.first, date("2026-08-31"))
        XCTAssertTrue(starts.allSatisfy { cal.component(.weekday, from: $0) == 2 })
    }

    func testEndOnSundayAndMonday() {
        XCTAssertEqual(HeatStrip.weekStarts(endingOn: date("2026-10-25"), calendar: cal).last, date("2026-10-19"))
        XCTAssertEqual(HeatStrip.weekStarts(endingOn: date("2026-10-26"), calendar: cal).last, date("2026-10-26"))
    }

    func testEmptyInputGivesEightZeros() {
        let w = weekly([])
        XCTAssertEqual(w.map(\.cost), [Double](repeating: 0, count: 8))
        XCTAssertEqual(w.map(\.start), HeatStrip.weekStarts(endingOn: end, calendar: cal))
        XCTAssertTrue(w.allSatisfy { $0.byAgent.isEmpty && $0.topAgent == nil })
    }

    func testSumsWithinWeeksAndSplitsAcrossWeekBoundary() {
        let days = [day("2026-10-18", 1), day("2026-10-19", 2), day("2026-10-24", 3),   // Sun | Mon, Sat
                    day("2026-10-12", 4), day("2026-10-13", 0.5)]
        let w = weekly(days).map(\.cost)
        XCTAssertEqual(w.count, 8)
        XCTAssertEqual(w[7], 5, accuracy: 1e-9)       // Oct 19 + Oct 24
        XCTAssertEqual(w[6], 5.5, accuracy: 1e-9)     // Oct 12 + Oct 13 + Oct 18
        XCTAssertEqual(w[0..<6].reduce(0, +), 0)
    }

    func testDropsDaysOlderThanEightWeeksAndAfterEndWeek() {
        let days = [day("2026-08-30", 100),   // 周日，第 1 周之前一天
                    day("2026-08-31", 1),     // 第 1 周周一
                    day("2026-10-26", 50),    // 结束周之后
                    day("garbage", 7)]
        XCTAssertEqual(weekly(days).map(\.cost), [1, 0, 0, 0, 0, 0, 0, 0])
    }

    func testAccumulatesByAgentAcrossDaysAndWeeks() {
        let days = [day("2026-10-12", 3, ["claude": 2, "codex": 1]),
                    day("2026-10-14", 4, ["codex": 4]),
                    day("2026-10-18", 1, ["antigravity": 0.5, "claude": 0.5]),   // 周日，仍是 Oct 12 那周
                    day("2026-10-19", 6, ["antigravity": 6])]                    // 下一周
        let w = weekly(days)
        XCTAssertEqual(w[6].cost, 8, accuracy: 1e-9)
        XCTAssertEqual(w[6].byAgent, ["claude": 2.5, "codex": 5, "antigravity": 0.5])
        XCTAssertEqual(w[6].topAgent, "codex")
        XCTAssertEqual(w[6].ranked.map(\.agent), ["codex", "claude", "antigravity"])
        XCTAssertEqual(w[7].byAgent, ["antigravity": 6])
        XCTAssertEqual(w[7].topAgent, "antigravity")
    }

    func testMissingByAgentFallsBackToProjectAgent() {
        let days = [day("2026-10-19", 5),                          // 旧数据：没有 by_agent
                    day("2026-10-20", 2, [:]),                     // 空字典同样回退
                    day("2026-10-21", 1, ["claude": 1])]
        let w = weekly(days, fallback: "codex")
        XCTAssertEqual(w[7].cost, 8, accuracy: 1e-9)
        XCTAssertEqual(w[7].byAgent, ["codex": 7, "claude": 1])
        XCTAssertEqual(w[7].topAgent, "codex")
        XCTAssertEqual(weekly([day("2026-10-13", 4)], fallback: "antigravity")[6].byAgent, ["antigravity": 4])
    }

    func testSegmentsOrderedByCostAndSharesSumToOne() {
        let s = HeatStrip.segments(week(["claude": 354, "antigravity": 164]))
        XCTAssertEqual(s.map(\.agent), ["claude", "antigravity"])
        XCTAssertEqual(s[0].share, 354.0 / 518, accuracy: 1e-9)
        XCTAssertEqual(s.reduce(0) { $0 + $1.share }, 1, accuracy: 1e-9)
    }

    func testSegmentsMergeSmallSharesIntoLargest() {
        // codex 5% < 10%：并进 claude
        let s = HeatStrip.segments(week(["claude": 60, "antigravity": 35, "codex": 5]))
        XCTAssertEqual(s.map(\.agent), ["claude", "antigravity"])
        XCTAssertEqual(s[0].share, 0.65, accuracy: 1e-9)
        XCTAssertEqual(s[1].share, 0.35, accuracy: 1e-9)
    }

    func testSegmentsCapAtThree() {
        let s = HeatStrip.segments(week(["a": 30, "b": 25, "c": 25, "d": 20]))
        XCTAssertEqual(s.map(\.agent), ["a", "b", "c"])
        XCTAssertEqual(s[0].share, 0.5, accuracy: 1e-9)
        XCTAssertEqual(s.reduce(0) { $0 + $1.share }, 1, accuracy: 1e-9)
    }

    func testSegmentsEmptyAndSingle() {
        XCTAssertTrue(HeatStrip.segments(week([:])).isEmpty)
        XCTAssertTrue(HeatStrip.segments(week(["claude": 0])).isEmpty)
        let one = HeatStrip.segments(week(["codex": 2]))
        XCTAssertEqual(one.map(\.agent), ["codex"])
        XCTAssertEqual(one[0].share, 1, accuracy: 1e-9)
    }

    func testLevels() {
        XCTAssertEqual(HeatStrip.level(0, max: 10), 0)
        XCTAssertEqual(HeatStrip.level(5, max: 0), 0)
        XCTAssertEqual(HeatStrip.level(0.01, max: 10), 1)
        XCTAssertEqual(HeatStrip.level(2.5, max: 10), 1)
        XCTAssertEqual(HeatStrip.level(2.6, max: 10), 2)
        XCTAssertEqual(HeatStrip.level(7.5, max: 10), 3)
        XCTAssertEqual(HeatStrip.level(10, max: 10), 4)
        XCTAssertEqual(HeatStrip.level(20, max: 10), 4)
    }

    func testWeekLabel() {
        XCTAssertEqual(HeatStrip.weekLabel(start: date("2026-10-12"), calendar: cal), "Oct 12–18")
        XCTAssertEqual(HeatStrip.weekLabel(start: date("2026-09-28"), calendar: cal), "Sep 28–Oct 4")
        XCTAssertEqual(HeatStrip.weekLabel(start: date("2025-12-29"), calendar: cal), "Dec 29, 2025–Jan 4, 2026")
    }

    func testDominantAgent() {
        let t = Tokens.zero
        let agents = [AgentCost(agent: "codex", label: "Codex CLI", cost: 1, tokens: t, sessions: 1),
                      AgentCost(agent: "claude", label: "Claude Code", cost: 3, tokens: t, sessions: 1)]
        let d = dominantAgent(agents)
        XCTAssertEqual(d?.agent, "claude")
        XCTAssertEqual(d?.share ?? 0, 0.75, accuracy: 1e-9)
        XCTAssertNil(dominantAgent([]))
        XCTAssertNil(dominantAgent([AgentCost(agent: "x", label: "X", cost: 0, tokens: t, sessions: 0)]))
    }
}
