import XCTest
@testable import KanjoCore

final class TooltipBuilderTests: KanjoTestCase {
    func testCostAndTokensFormatting() {
        // zh-Hans: 万 / 亿
        XCTAssertEqual(
            TooltipBuilder.costAndTokens(cost: 12.34, tokens: 120_000_000, currency: "USD", language: "zh-Hans"),
            "$12.34 · 1.2亿 token"
        )
        XCTAssertEqual(
            TooltipBuilder.costAndTokens(cost: 10.00, tokens: 90_000_000, currency: "USD", language: "zh-Hans"),
            "$10.00 · 9000万 token"
        )
        XCTAssertEqual(
            TooltipBuilder.costAndTokens(cost: 0, tokens: 0, currency: "USD", language: "zh-Hans"),
            "$0.00 · 0 token"
        )

        // en: k / M / B
        XCTAssertEqual(
            TooltipBuilder.costAndTokens(cost: 12.34, tokens: 120_000_000, currency: "USD", language: "en"),
            "$12.34 · 120.0M tokens"
        )
        XCTAssertEqual(
            TooltipBuilder.costAndTokens(cost: 10.00, tokens: 90_000_000, currency: "USD", language: "en"),
            "$10.00 · 90.0M tokens"
        )
        XCTAssertEqual(
            TooltipBuilder.costAndTokens(cost: 0, tokens: 0, currency: "USD", language: "en"),
            "$0.00 · 0 tokens"
        )

        // fr: k / M / Md
        XCTAssertEqual(
            TooltipBuilder.costAndTokens(cost: 12.34, tokens: 120_000_000, currency: "USD", language: "fr"),
            "$12.34 · 120M tokens"
        )
        XCTAssertEqual(
            TooltipBuilder.costAndTokens(cost: 10.00, tokens: 90_000_000, currency: "USD", language: "fr"),
            "$10.00 · 90M tokens"
        )

        // Non-USD currency
        XCTAssertEqual(
            TooltipBuilder.costAndTokens(cost: 12.34, tokens: 120_000_000, currency: "EUR", language: "zh-Hans"),
            "EUR 12.34 · 1.2亿 token"
        )
    }

    func testAgentLineFormatting() {
        XCTAssertEqual(
            TooltipBuilder.agentLine(label: "Claude Code", cost: 10.00, tokens: 90_000_000, currency: "USD", language: "zh-Hans"),
            "● Claude Code  $10.00 · 9000万 token"
        )
        XCTAssertEqual(
            TooltipBuilder.agentLine(label: "Codex", cost: 2.34, tokens: 30_000_000, currency: "USD", language: "en"),
            "● Codex  $2.34 · 30.0M tokens"
        )
    }

    func testAgentLinesSortedByCostAndZeroFiltered() {
        let items: [(label: String, cost: Double, tokens: Int)] = [
            (label: "Codex", cost: 2.34, tokens: 30_000_000),
            (label: "Zero Agent", cost: 0.0, tokens: 0),
            (label: "Claude Code", cost: 10.00, tokens: 90_000_000),
            (label: "A-Free Agent", cost: 0.0, tokens: 50_000)
        ]

        let lines = TooltipBuilder.agentLines(items: items, currency: "USD", language: "zh-Hans")
        XCTAssertEqual(lines.count, 3) // Zero Agent is filtered out
        XCTAssertEqual(lines[0], "● Claude Code  $10.00 · 9000万 token")
        XCTAssertEqual(lines[1], "● Codex  $2.34 · 3000万 token")
        XCTAssertEqual(lines[2], "● A-Free Agent  $0.00 · 5万 token")
    }

    func testAgentLinesFromDictionaries() {
        let byAgent: [String: Double] = ["claude": 10.0, "codex": 2.34]
        let byAgentTokens: [String: Int] = ["claude": 90_000_000, "codex": 30_000_000]
        let labels: [String: String] = ["claude": "Claude Code", "codex": "Codex"]

        let lines = TooltipBuilder.agentLines(
            byAgent: byAgent,
            byAgentTokens: byAgentTokens,
            agentLabels: labels,
            currency: "USD",
            language: "zh-Hans"
        )
        XCTAssertEqual(lines.count, 2)
        XCTAssertEqual(lines[0], "● Claude Code  $10.00 · 9000万 token")
        XCTAssertEqual(lines[1], "● Codex  $2.34 · 3000万 token")
    }

    func testProjectTileTooltip() {
        let agents = [
            AgentCost(agent: "claude", label: "Claude Code", cost: 10.0, tokens: Tokens(total: 90_000_000), sessions: 5),
            AgentCost(agent: "codex", label: "Codex", cost: 2.34, tokens: Tokens(total: 30_000_000), sessions: 2)
        ]
        let tooltip = TooltipBuilder.projectTileTooltip(
            name: "Kanjo",
            cost: 12.34,
            tokens: 120_000_000,
            agents: agents,
            currency: "USD",
            language: "zh-Hans"
        )
        let expected = """
        Kanjo · $12.34 · 1.2亿 token
        ● Claude Code  $10.00 · 9000万 token
        ● Codex  $2.34 · 3000万 token
        """
        XCTAssertEqual(tooltip, expected)
    }

    func testMergedTileSumAndTooltip() {
        let sum = TooltipBuilder.mergedTileSum(projects: [
            (cost: 10.0, tokens: 90_000_000),
            (cost: 2.34, tokens: 30_000_000)
        ])
        XCTAssertEqual(sum.cost, 12.34, accuracy: 1e-9)
        XCTAssertEqual(sum.tokens, 120_000_000)

        let p1 = Project(id: "p1", name: "Alpha", remote: nil, paths: [], pathMissing: false,
                         cost: 10.0, tokens: Tokens(total: 90_000_000), sessions: 1,
                         byAgent: [], byModel: [], byDay: [], byBranch: [], sessionsDetail: [])
        let p2 = Project(id: "p2", name: "Beta", remote: nil, paths: [], pathMissing: false,
                         cost: 2.34, tokens: Tokens(total: 30_000_000), sessions: 1,
                         byAgent: [], byModel: [], byDay: [], byBranch: [], sessionsDetail: [])

        let tooltipZh = TooltipBuilder.mergedTileTooltip(projects: [p1, p2], currency: "USD", language: "zh-Hans")
        XCTAssertTrue(tooltipZh.contains("2 个较小项目 · $12.34 · 1.2亿 token"))
        XCTAssertTrue(tooltipZh.contains("Alpha  $10.00 · 9000万 token"))
        XCTAssertTrue(tooltipZh.contains("Beta  $2.34 · 3000万 token"))

        let tooltipEn = TooltipBuilder.mergedTileTooltip(projects: [p1, p2], currency: "USD", language: "en")
        XCTAssertTrue(tooltipEn.contains("2 smaller projects · $12.34 · 120.0M tokens"))
        XCTAssertTrue(tooltipEn.contains("Alpha  $10.00 · 90.0M tokens"))
        XCTAssertTrue(tooltipEn.contains("Beta  $2.34 · 30.0M tokens"))
    }

    func testWeekTooltip() {
        let byAgent = ["claude": 30.0, "codex": 12.10]
        let byAgentTokens = ["claude": 90_000_000, "codex": 30_000_000]
        let labels = ["claude": "Claude Code", "codex": "Codex"]

        let tooltip = TooltipBuilder.weekTooltip(
            weekLabel: "Oct 13–19",
            cost: 42.10,
            tokens: 120_000_000,
            byAgent: byAgent,
            byAgentTokens: byAgentTokens,
            agentLabels: labels,
            currency: "USD",
            language: "zh-Hans"
        )
        let expected = """
        Oct 13–19 · $42.10 · 1.2亿 token
        ● Claude Code  $30.00 · 9000万 token
        ● Codex  $12.10 · 3000万 token
        """
        XCTAssertEqual(tooltip, expected)
    }

    func testDayTooltip() {
        let byAgent = ["claude": 10.00]
        let byAgentTokens = ["claude": 90_000_000]
        let labels = ["claude": "Claude Code"]

        let tooltip = TooltipBuilder.dayTooltip(
            dayString: "2026-10-24",
            cost: 10.00,
            tokens: 90_000_000,
            byAgent: byAgent,
            byAgentTokens: byAgentTokens,
            agentLabels: labels,
            currency: "USD",
            language: "en"
        )
        XCTAssertTrue(tooltip.hasPrefix("Oct 24, 2026 · $10.00 · 90.0M tokens"))
        XCTAssertTrue(tooltip.contains("● Claude Code  $10.00 · 90.0M tokens"))
    }

    func testModelTooltip() {
        let tooltip = TooltipBuilder.modelTooltip(
            model: "claude-3-5-sonnet",
            agent: "claude",
            cost: 10.00,
            tokens: 90_000_000,
            currency: "USD",
            language: "zh-Hans"
        )
        XCTAssertEqual(tooltip, "claude-3-5-sonnet (claude) · $10.00 · 9000万 token")
    }

    func testOverviewSummaryTextDropsDateForToday() {
        // zh-Hans Today: drops the date part
        let zhToday = OverviewSummaryText.make(
            range: .today,
            dateRange: "10月26日",
            projectsCount: 5,
            sessionsCount: 16,
            tokensCount: 340_000_000,
            language: "zh-Hans"
        )
        XCTAssertEqual(zhToday, "5 个项目 · 16 次会话 · 3.4亿 token")
        XCTAssertFalse(zhToday.contains("10月26日"))

        // zh-Hans Other range (e.g. 7d): keeps the date part
        let zh7d = OverviewSummaryText.make(
            range: .days7,
            dateRange: "10月20日 – 10月26日",
            projectsCount: 5,
            sessionsCount: 16,
            tokensCount: 340_000_000,
            language: "zh-Hans"
        )
        XCTAssertEqual(zh7d, "10月20日 – 10月26日 · 5 个项目 · 16 次会话 · 3.4亿 token")

        // en Today: drops date
        let enToday = OverviewSummaryText.make(
            range: .today,
            dateRange: "Oct 26",
            projectsCount: 5,
            sessionsCount: 16,
            tokensCount: 340_000_000,
            language: "en"
        )
        XCTAssertEqual(enToday, "5 projects · 16 sessions · 340.0M tokens")

        // en Other range: keeps date
        let en7d = OverviewSummaryText.make(
            range: .days7,
            dateRange: "Oct 20 – Oct 26",
            projectsCount: 5,
            sessionsCount: 16,
            tokensCount: 340_000_000,
            language: "en"
        )
        XCTAssertEqual(en7d, "Oct 20 – Oct 26 · 5 projects · 16 sessions · 340.0M tokens")
    }

    func testProjectSubtitleTextDropsDateForToday() {
        // zh-Hans Today
        let zhToday = ProjectSubtitleText.make(
            range: .today,
            sessions: 16,
            usageDate: "10月26日",
            language: "zh-Hans"
        )
        XCTAssertEqual(zhToday, "16 次会话")

        // zh-Hans Other range
        let zh7d = ProjectSubtitleText.make(
            range: .days7,
            sessions: 16,
            usageDate: "10月20日 – 10月26日",
            language: "zh-Hans"
        )
        XCTAssertEqual(zh7d, "16 次会话 · 10月20日 – 10月26日")

        // en Today
        let enToday = ProjectSubtitleText.make(
            range: .today,
            sessions: 16,
            usageDate: "Oct 26",
            language: "en"
        )
        XCTAssertEqual(enToday, "16 sessions")

        // en Other range
        let en7d = ProjectSubtitleText.make(
            range: .days7,
            sessions: 16,
            usageDate: "Oct 20 – Oct 26",
            language: "en"
        )
        XCTAssertEqual(en7d, "16 sessions · Oct 20 – Oct 26")
    }
}
