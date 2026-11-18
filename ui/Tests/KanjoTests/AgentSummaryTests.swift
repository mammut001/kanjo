import XCTest
@testable import KanjoCore

final class AgentSummaryTests: KanjoTestCase {
    private func loadFixture() throws -> UsageReport {
        let data = try Data(contentsOf: DefaultPaths.sampleFixture)
        return try ReportDecoder.decode(data)
    }

    func testRowsOrderedByTokensDescAndSharesSumToOne() throws {
        let report = try loadFixture()
        let spec = RangeEngine.spec(.all, report: report)
        let filtered = RangeEngine.filtered(report, range: spec) {
            dominantAgent($0.byAgent)?.agent ?? $0.byAgent.first?.agent ?? "unknown"
        }
        let summary = AgentSummary.build(report: report, filtered: filtered)

        XCTAssertFalse(summary.rows.isEmpty)
        // 严格按 tokens 降序，且不含 0 token 的 agent
        let tokens = summary.rows.map(\.tokens)
        XCTAssertTrue(tokens.allSatisfy { $0 > 0 })
        XCTAssertEqual(tokens, tokens.sorted(by: >))

        // 占比之和严格为 1.0
        let totalShare = summary.rows.reduce(0.0) { $0 + $1.share }
        XCTAssertEqual(totalShare, 1.0, accuracy: 1e-9)

        // token 汇总与报告一致
        XCTAssertEqual(tokens.reduce(0, +), summary.totalTokens)
    }

    func testZeroTokenAgentsHiddenInRange() throws {
        let report = try loadFixture()
        // 使用极短窗口（今天没有历史 fixture 数据），所有 agent 在该范围下为 0 token，应全部隐藏
        let futureNow = ReportDates.parseTimestamp("2030-01-01T12:00:00Z")!
        let spec = RangeEngine.spec(.today, report: report, now: futureNow)
        let filtered = RangeEngine.filtered(report, range: spec) {
            dominantAgent($0.byAgent)?.agent ?? $0.byAgent.first?.agent ?? "unknown"
        }
        let summary = AgentSummary.build(report: report, filtered: filtered, now: futureNow)
        XCTAssertTrue(summary.rows.isEmpty)
        XCTAssertEqual(summary.totalTokens, 0)
    }

    func testWhereMoneyWentTop4PlusOthersSumToOne() throws {
        let report = try loadFixture()
        let spec = RangeEngine.spec(.all, report: report)
        let filtered = RangeEngine.filtered(report, range: spec) {
            dominantAgent($0.byAgent)?.agent ?? $0.byAgent.first?.agent ?? "unknown"
        }
        let summary = AgentSummary.build(report: report, filtered: filtered)

        // claude 在 sample.json 中出现在超过 4 个项目中，应有 top 4 + others 且占比之和为 1
        let claude = try XCTUnwrap(summary.rows.first { $0.agent == "claude" })
        XCTAssertEqual(claude.projectShares.count, 4)
        let others = try XCTUnwrap(claude.othersProjectShare)
        XCTAssertGreaterThan(others.count, 0)
        let sumProjectShares = claude.projectShares.reduce(0.0) { $0 + $1.share } + others.share
        XCTAssertEqual(sumProjectShares, 1.0, accuracy: 1e-9)

        // 降序排列
        let costs = claude.projectShares.map(\.cost)
        XCTAssertEqual(costs, costs.sorted(by: >))
        XCTAssertGreaterThanOrEqual(costs.last ?? 0, 0)
    }

    func testCacheHitRateMath() {
        XCTAssertNil(AgentSummary.cacheHitRate(for: Tokens(input: 0, output: 100, cacheRead: 0, cacheWrite: 0, total: 100)))
        let t = Tokens(input: 100, output: 50, cacheRead: 900, cacheWrite: 20, total: 1070)
        XCTAssertEqual(try! XCTUnwrap(AgentSummary.cacheHitRate(for: t)), 0.9, accuracy: 1e-9)
    }
}
