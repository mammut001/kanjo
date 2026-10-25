import XCTest
@testable import KanjoCore

final class SubscriptionTests: XCTestCase {
    func testMultiplierAndShare() {
        XCTAssertEqual(SubscriptionValue.multiplier(usage: 1572, monthlyPriceUsd: 100)!, 15.72, accuracy: 1e-9)
        XCTAssertEqual(SubscriptionValue.multiplier(usage: 0, monthlyPriceUsd: 20), 0)
        XCTAssertNil(SubscriptionValue.multiplier(usage: 10, monthlyPriceUsd: nil))
        XCTAssertNil(SubscriptionValue.multiplier(usage: 10, monthlyPriceUsd: 0))
        XCTAssertNil(SubscriptionValue.multiplier(usage: 10, monthlyPriceUsd: -5))
        XCTAssertEqual(SubscriptionValue.share(part: 38, total: 100)!, 0.38, accuracy: 1e-9)
        XCTAssertEqual(SubscriptionValue.share(part: 0, total: 10), 0)
        XCTAssertNil(SubscriptionValue.share(part: 5, total: 0))
        XCTAssertNil(SubscriptionValue.share(part: 5, total: -1))
        XCTAssertEqual(subscriptionValueExplanation,
                       "You pay the flat fee on the left. The number on the right is what the same work would cost on API billing.")
    }

    func testFixtureCycleUsageMatchesFilterAndSkipsUnsubscribed() throws {
        let r = try ReportDecoder.decode(Data(contentsOf: DefaultPaths.sampleFixture))
        let now = ReportDates.parseTimestamp(r.generatedAt)!
        let usage = SubscriptionValue.cycleUsage(of: r, now: now)
        let filtered = RangeEngine.filtered(r, range: RangeEngine.spec(.billingCycle, report: r, now: now)) {
            dominantAgent($0.byAgent)?.agent ?? $0.byAgent.first?.agent ?? "unknown"
        }
        for agent in ["claude", "codex"] {
            let fromProjects = filtered.projects.reduce(0.0) { acc, p in
                acc + (p.byAgent.first { $0.agent == agent }?.cost ?? 0)
            }
            let fromBuckets = (filtered.unattributed.sessionsDetail + filtered.excluded.sessionsDetail)
                .filter { $0.agent == agent }
                .reduce(0.0) { $0 + $1.cost }
            XCTAssertEqual(usage.total(for: agent), fromProjects + fromBuckets, accuracy: 0.01, agent)
            XCTAssertGreaterThan(usage.total(for: agent), 0, agent)
        }
        XCTAssertEqual(usage.total(for: "antigravity"), 0)

        let rows = SubscriptionValue.rows(of: r, now: now)
        XCTAssertEqual(rows.map(\.agent), rows.sorted { $0.usage > $1.usage }.map(\.agent))
        XCTAssertEqual(Set(rows.map(\.agent)), ["claude", "codex"])
        for row in rows {
            let price = r.subscriptions?[row.agent]?.monthlyPriceUsd
            XCTAssertEqual(row.multiplier, SubscriptionValue.multiplier(usage: row.usage, monthlyPriceUsd: price))
            XCTAssertFalse(row.extraUsageEnabled)
        }

        let top = r.projects[0]
        let shares = SubscriptionValue.shares(project: top.id, report: r, now: now)
        XCTAssertFalse(shares.isEmpty)
        XCTAssertFalse(shares.contains { $0.agent == "antigravity" })
        for s in shares {
            let total = usage.total(for: s.agent)
            XCTAssertGreaterThan(total, 0)
            XCTAssertEqual(s.share, s.projectCost / total, accuracy: 1e-9)
            XCTAssertEqual(s.projectCost, usage.cost(project: top.id, agent: s.agent), accuracy: 1e-9)
        }
        // 总量为 0 的 agent 不出现。把 claude 的账期推到未来，它的用量变 0，行被跳过。
        var future = r
        var claude = future.subscriptions!["claude"]!
        claude.cycleStart = "2099-01-01T00:00:00Z"
        future.subscriptions!["claude"] = claude
        let skipped = SubscriptionValue.shares(project: top.id, report: future, now: now)
        XCTAssertFalse(skipped.contains { $0.agent == "claude" })
        XCTAssertEqual(SubscriptionValue.rows(of: future, now: now).first { $0.agent == "claude" }?.usage, 0)
    }
}
