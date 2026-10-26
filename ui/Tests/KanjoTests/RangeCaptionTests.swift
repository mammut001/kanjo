import XCTest
@testable import KanjoCore

final class RangeCaptionTests: KanjoTestCase {
    private let shanghai = TimeZone(identifier: "Asia/Shanghai")!
    private var cal: Calendar { RangeEngine.calendar(timezone: shanghai) }

    private func ts(_ s: String) -> Date { ReportDates.parseTimestamp(s)! }

    private let labels: [String: String] = [
        "claude": "Claude Code",
        "codex": "Codex CLI",
        "grok": "Grok CLI",
        "copilot": "Copilot CLI",
        "minimax": "MiniMax",
        "qwen": "Qwen Code",
        "commandcode": "Command Code",
        "opencode": "OpenCode",
        "antigravity": "Antigravity CLI",
    ]

    func testShortName() {
        XCTAssertEqual(RangeCaptionBuilder.shortName(for: "claude", labels: labels), "Claude")
        XCTAssertEqual(RangeCaptionBuilder.shortName(for: "copilot", labels: labels), "Copilot")
        XCTAssertEqual(RangeCaptionBuilder.shortName(for: "commandcode", labels: labels), "Command")
        XCTAssertEqual(RangeCaptionBuilder.shortName(for: "minimax", labels: labels), "MiniMax")
        XCTAssertEqual(RangeCaptionBuilder.shortName(for: "unknown_agent", labels: labels), "Unknown_Agent")
    }

    func testAgentOrder() throws {
        var report = try ReportDecoder.decode(Data(contentsOf: DefaultPaths.sampleFixture))
        XCTAssertEqual(RangeCaptionBuilder.agentOrder(report: report),
                       ["claude", "codex", "grok", "antigravity", "copilot", "commandcode", "qwen", "minimax", "opencode"])

        // Add extra keys not in projects
        report.quotaWindows?["future_bot"] = QuotaWindow(weeklyResetsAt: "2026-10-27T00:00:00Z", weeklyWindowHours: 168, source: "manual")
        report.subscriptions?["extra_agent"] = Subscription(plan: "pro", planLabel: "Extra Agent", monthlyPriceUsd: 10, cycleStart: "2026-10-01T00:00:00Z", cycleEnd: "2026-11-01T00:00:00Z", anchorDay: 1, cycleSource: "manual", extraUsageEnabled: false, source: "manual")
        XCTAssertEqual(RangeCaptionBuilder.agentOrder(report: report),
                       ["claude", "codex", "grok", "antigravity", "copilot", "commandcode", "qwen", "minimax", "opencode", "extra_agent", "future_bot"])
    }

    func testAllRangeReturnsNil() {
        let spec = RangeSpec(range: .all, calendar: cal)
        XCTAssertNil(RangeCaptionBuilder.caption(for: .all, spec: spec, agentOrder: ["claude"]))
    }

    func testFixedRangesReturnNil() {
        let start = ts("2026-10-24T00:00:00Z")
        let end = ts("2026-10-25T00:00:00Z")
        let todaySpec = RangeSpec(range: .today, calendar: cal, start: start, end: end)
        XCTAssertNil(RangeCaptionBuilder.caption(for: .today, spec: todaySpec, agentOrder: ["claude"], language: "en"))

        let d7Spec = RangeSpec(range: .days7, calendar: cal, start: ts("2026-10-18T00:00:00Z"), end: end)
        XCTAssertNil(RangeCaptionBuilder.caption(for: .days7, spec: d7Spec, agentOrder: ["claude"], language: "en"))

        let d30Spec = RangeSpec(range: .days30, calendar: cal, start: ts("2026-09-25T00:00:00Z"), end: end)
        XCTAssertNil(RangeCaptionBuilder.caption(for: .days30, spec: d30Spec, agentOrder: ["claude"], language: "en"))

        let lastWeekSpec = RangeSpec(range: .lastWeek, calendar: cal, start: ts("2026-10-12T00:00:00Z"), end: ts("2026-10-19T00:00:00Z"))
        XCTAssertNil(RangeCaptionBuilder.caption(for: .lastWeek, spec: lastWeekSpec, agentOrder: ["claude"], language: "en"))
    }

    func testSinceResetAllHaveReset() {
        let agentOrder = ["claude", "codex", "grok"]
        let agentStarts = [
            "claude": ts("2026-10-20T10:00:00Z"),
            "codex": ts("2026-10-26T02:10:00Z"),
            "grok": ts("2026-10-20T05:29:00Z"),
        ]
        let spec = RangeSpec(range: .sinceReset, calendar: cal, agentStarts: agentStarts)
        let result = RangeCaptionBuilder.caption(for: .sinceReset, spec: spec, agentOrder: agentOrder, agentLabels: labels, language: "en")

        XCTAssertNotNil(result)
        XCTAssertTrue(result!.text.contains("Since Claude reset"))
        XCTAssertTrue(result!.text.contains("Codex reset"))
        XCTAssertTrue(result!.text.contains("Grok reset"))
        XCTAssertFalse(result!.text.contains("others"))
        XCTAssertFalse(result!.text.contains("no reset info"))
        XCTAssertNil(result!.help)
    }

    func testSinceResetOneMissing() {
        let agentOrder = ["claude", "codex", "grok", "copilot"]
        let agentStarts = [
            "claude": ts("2026-10-20T10:00:00Z"),
            "codex": ts("2026-10-26T02:10:00Z"),
            "grok": ts("2026-10-20T05:29:00Z"),
        ]
        let spec = RangeSpec(range: .sinceReset, calendar: cal, agentStarts: agentStarts)
        let result = RangeCaptionBuilder.caption(for: .sinceReset, spec: spec, agentOrder: agentOrder, agentLabels: labels, language: "en")

        XCTAssertNotNil(result)
        XCTAssertTrue(result!.text.contains("Since Claude reset"))
        XCTAssertTrue(result!.text.contains("Codex reset"))
        XCTAssertTrue(result!.text.contains("Grok reset"))
        XCTAssertTrue(result!.text.hasSuffix("Copilot: no reset info"))
        XCTAssertFalse(result!.text.contains("others"))
        XCTAssertNil(result!.help)
    }

    func testSinceResetMultipleMissingEnglish() {
        let agentOrder = ["claude", "codex", "grok", "copilot", "minimax", "qwen", "commandcode", "opencode", "antigravity"]
        let agentStarts = [
            "claude": ts("2026-10-20T10:00:00Z"),
            "codex": ts("2026-10-26T02:10:00Z"),
            "grok": ts("2026-10-20T05:29:00Z"),
        ]
        let spec = RangeSpec(range: .sinceReset, calendar: cal, agentStarts: agentStarts)
        let result = RangeCaptionBuilder.caption(for: .sinceReset, spec: spec, agentOrder: agentOrder, agentLabels: labels, language: "en")

        XCTAssertNotNil(result)
        XCTAssertTrue(result!.text.contains("Since Claude reset"))
        XCTAssertTrue(result!.text.contains("Codex reset"))
        XCTAssertTrue(result!.text.contains("Grok reset"))
        XCTAssertTrue(result!.text.hasSuffix("6 others have no reset info (not counted)"))
        XCTAssertEqual(result!.help, "Copilot, MiniMax, Qwen, Command, OpenCode, Antigravity")
    }

    func testSinceResetMultipleMissingChineseAndFrench() {
        let agentOrder = ["claude", "codex", "grok", "copilot", "minimax", "qwen", "commandcode", "opencode", "antigravity"]
        let agentStarts = [
            "claude": ts("2026-10-20T10:00:00Z"),
            "codex": ts("2026-10-26T02:10:00Z"),
            "grok": ts("2026-10-20T05:29:00Z"),
        ]
        let spec = RangeSpec(range: .sinceReset, calendar: cal, agentStarts: agentStarts)

        // zh-Hans
        let zh = RangeCaptionBuilder.caption(for: .sinceReset, spec: spec, agentOrder: agentOrder, agentLabels: labels, language: "zh-Hans")
        XCTAssertNotNil(zh)
        XCTAssertTrue(zh!.text.contains("自 Claude 重置"))
        XCTAssertTrue(zh!.text.hasSuffix("其余 6 个无重置信息（不计入）"))
        XCTAssertEqual(zh!.help, "Copilot, MiniMax, Qwen, Command, OpenCode, Antigravity")

        // fr
        let fr = RangeCaptionBuilder.caption(for: .sinceReset, spec: spec, agentOrder: agentOrder, agentLabels: labels, language: "fr")
        XCTAssertNotNil(fr)
        XCTAssertTrue(fr!.text.contains("Depuis réinit. Claude"))
        XCTAssertTrue(fr!.text.hasSuffix("6 autres sans info de réinitialisation (non comptés)"))
        XCTAssertEqual(fr!.help, "Copilot, MiniMax, Qwen, Command, OpenCode, Antigravity")
    }

    func testBillingCycleAllHaveSubscription() {
        let agentOrder = ["claude", "codex"]
        let subs = [
            "claude": Subscription(plan: "max_5x", planLabel: "Claude Max 5x", monthlyPriceUsd: 100, cycleStart: "2026-10-25T00:00:00Z", cycleEnd: "2026-11-25T00:00:00Z", anchorDay: 25, cycleSource: "manual", extraUsageEnabled: false, source: "manual"),
            "codex": Subscription(plan: "plus", planLabel: "ChatGPT Plus", monthlyPriceUsd: 20, cycleStart: "2026-11-01T00:00:00Z", cycleEnd: "2026-12-01T00:00:00Z", anchorDay: 1, cycleSource: "manual", extraUsageEnabled: false, source: "manual"),
        ]
        let agentStarts = [
            "claude": ts("2026-10-25T00:00:00Z"),
            "codex": ts("2026-11-01T00:00:00Z"),
        ]
        let spec = RangeSpec(range: .billingCycle, calendar: cal, agentStarts: agentStarts)
        let result = RangeCaptionBuilder.caption(for: .billingCycle, spec: spec, agentOrder: agentOrder, agentLabels: labels, subscriptions: subs, language: "en")

        XCTAssertNotNil(result)
        XCTAssertTrue(result!.text.starts(with: "Billing cycle · "))
        XCTAssertTrue(result!.text.contains("Claude Max 5x since"))
        XCTAssertTrue(result!.text.contains("ChatGPT Plus since"))
        XCTAssertFalse(result!.text.contains("others"))
        XCTAssertFalse(result!.text.contains("no subscription"))
        XCTAssertNil(result!.help)
    }

    func testBillingCycleOneMissing() {
        let agentOrder = ["claude", "copilot"]
        let subs = [
            "claude": Subscription(plan: "max_5x", planLabel: "Claude Max 5x", monthlyPriceUsd: 100, cycleStart: "2026-10-25T00:00:00Z", cycleEnd: "2026-11-25T00:00:00Z", anchorDay: 25, cycleSource: "manual", extraUsageEnabled: false, source: "manual"),
        ]
        let agentStarts = [
            "claude": ts("2026-10-25T00:00:00Z"),
        ]
        let spec = RangeSpec(range: .billingCycle, calendar: cal, agentStarts: agentStarts)
        let result = RangeCaptionBuilder.caption(for: .billingCycle, spec: spec, agentOrder: agentOrder, agentLabels: labels, subscriptions: subs, language: "en")

        XCTAssertNotNil(result)
        XCTAssertTrue(result!.text.starts(with: "Billing cycle · "))
        XCTAssertTrue(result!.text.contains("Claude Max 5x since"))
        XCTAssertTrue(result!.text.hasSuffix("Copilot: no subscription"))
        XCTAssertFalse(result!.text.contains("others"))
        XCTAssertNil(result!.help)
    }

    func testBillingCycleMultipleMissing() {
        let agentOrder = ["claude", "copilot", "minimax", "antigravity"]
        let subs = [
            "claude": Subscription(plan: "max_5x", planLabel: "Claude Max 5x", monthlyPriceUsd: 100, cycleStart: "2026-10-25T00:00:00Z", cycleEnd: "2026-11-25T00:00:00Z", anchorDay: 25, cycleSource: "manual", extraUsageEnabled: false, source: "manual"),
        ]
        let agentStarts = [
            "claude": ts("2026-10-25T00:00:00Z"),
        ]
        let spec = RangeSpec(range: .billingCycle, calendar: cal, agentStarts: agentStarts)

        // English
        let en = RangeCaptionBuilder.caption(for: .billingCycle, spec: spec, agentOrder: agentOrder, agentLabels: labels, subscriptions: subs, language: "en")
        XCTAssertNotNil(en)
        XCTAssertTrue(en!.text.starts(with: "Billing cycle · "))
        XCTAssertTrue(en!.text.hasSuffix("3 others have no subscription (not counted)"))
        XCTAssertEqual(en!.help, "Copilot, MiniMax, Antigravity")

        // Chinese
        let zh = RangeCaptionBuilder.caption(for: .billingCycle, spec: spec, agentOrder: agentOrder, agentLabels: labels, subscriptions: subs, language: "zh-Hans")
        XCTAssertNotNil(zh)
        XCTAssertTrue(zh!.text.starts(with: "账单周期 · "))
        XCTAssertTrue(zh!.text.hasSuffix("其余 3 个无订阅（不计入）"))
        XCTAssertEqual(zh!.help, "Copilot, MiniMax, Antigravity")

        // French
        let fr = RangeCaptionBuilder.caption(for: .billingCycle, spec: spec, agentOrder: agentOrder, agentLabels: labels, subscriptions: subs, language: "fr")
        XCTAssertNotNil(fr)
        XCTAssertTrue(fr!.text.starts(with: "Cycle de facturation · "))
        XCTAssertTrue(fr!.text.hasSuffix("3 autres sans abonnement (non comptés)"))
        XCTAssertEqual(fr!.help, "Copilot, MiniMax, Antigravity")
    }
}
