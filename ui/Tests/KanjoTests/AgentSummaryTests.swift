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

    func testAntigravityAccountSharesPopulatedForAntigravityOnly() throws {
        let report = try loadFixture()
        let spec = RangeEngine.spec(.all, report: report)
        let filtered = RangeEngine.filtered(report, range: spec) {
            dominantAgent($0.byAgent)?.agent ?? $0.byAgent.first?.agent ?? "unknown"
        }
        let summary = AgentSummary.build(report: report, filtered: filtered)

        let agy = try XCTUnwrap(summary.rows.first { $0.agent == "antigravity" })
        XCTAssertFalse(agy.antigravityAccountShares.isEmpty)
        XCTAssertEqual(agy.antigravityAccountShares.reduce(0.0) { $0 + $1.share }, 1.0, accuracy: 1e-9)
        XCTAssertTrue(agy.antigravityAccountShares.contains { $0.isUnattributed && $0.tokens > 0 })

        let claude = try XCTUnwrap(summary.rows.first { $0.agent == "claude" })
        XCTAssertTrue(claude.antigravityAccountShares.isEmpty)
    }

    func testModelsCappedAtTop8ByCostWithOthers() throws {
        var report = try loadFixture()
        // Replace projects[0]'s antigravity models (and strip any antigravity models from other projects)
        // with 10 models: 9 ranked m1..m9 by cost 9.0..1.0 plus a high-token low-cost m-cheap ($0.05, 500k tok).
        var customModels: [ModelCost] = (1...9).map { idx in
            ModelCost(
                model: "m-\(idx)",
                agent: "antigravity",
                cost: Double(10 - idx),
                tokens: Tokens(total: idx * 100)
            )
        }
        customModels.append(ModelCost(
            model: "m-cheap",
            agent: "antigravity",
            cost: 0.05,
            tokens: Tokens(total: 500_000)
        ))

        for i in report.projects.indices {
            report.projects[i].byModel.removeAll { $0.agent == "antigravity" }
        }
        report.projects[0].byModel.append(contentsOf: customModels)

        let spec = RangeEngine.spec(.all, report: report)
        let filtered = RangeEngine.filtered(report, range: spec) {
            dominantAgent($0.byAgent)?.agent ?? $0.byAgent.first?.agent ?? "unknown"
        }
        let summary = AgentSummary.build(report: report, filtered: filtered)

        let agy = try XCTUnwrap(summary.rows.first { $0.agent == "antigravity" })
        XCTAssertEqual(agy.models.count, 8)
        XCTAssertEqual(agy.models.map(\.model), (1...8).map { "m-\($0)" })
        let costs = agy.models.map(\.cost)
        XCTAssertEqual(costs, costs.sorted(by: >))

        let others = try XCTUnwrap(agy.othersModel)
        XCTAssertEqual(others.count, 2)
        XCTAssertEqual(others.tokens, 900 + 500_000)
        XCTAssertEqual(others.cost, 1.0 + 0.05, accuracy: 1e-9)

        // Agents with <= 8 models have no Others row
        let claude = try XCTUnwrap(summary.rows.first { $0.agent == "claude" })
        XCTAssertLessThanOrEqual(claude.models.count, 8)
        XCTAssertNil(claude.othersModel)

        // Localized Others (N) strings
        XCTAssertEqual(L10n.tr("agents.detail.models.others", language: "en", 2), "Others (2)")
        XCTAssertEqual(L10n.tr("agents.detail.models.others", language: "zh-Hans", 2), "其他模型 (2)")
        XCTAssertEqual(L10n.tr("agents.detail.models.others", language: "fr", 2), "Autres (2)")
    }
}
