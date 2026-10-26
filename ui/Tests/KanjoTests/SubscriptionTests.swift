import XCTest
@testable import KanjoCore

final class SubscriptionTests: KanjoTestCase {
    private func subscription(start: String = "2026-10-24T16:00:00Z", end: String = "2026-11-24T16:00:00Z",
                              cycleSource: String = "subscription_date", source: String = "detected") -> Subscription {
        Subscription(plan: "max_5x", planLabel: "Claude Max 5x", monthlyPriceUsd: 100,
                     cycleStart: start, cycleEnd: end, anchorDay: 25, cycleSource: cycleSource,
                     extraUsageEnabled: false, source: source)
    }

    func testCycleCaptionInReportTimezone() {
        let zone = TimeZone(identifier: "Asia/Shanghai")!
        let now = ReportDates.parseTimestamp("2026-10-25T10:00:00Z")!
        XCTAssertEqual(Fmt.cycleCaption(subscription(), timezone: zone, now: now),
                       "Oct 25 – Nov 25 · renews in 31 days")
        XCTAssertEqual(Fmt.cycleCaption(subscription(cycleSource: "rolling_30d"), timezone: zone, now: now),
                       "Last 30 days · set renewal day for exact cycle")
        XCTAssertEqual(Fmt.cycleCaption(subscription(cycleSource: "unknown"), timezone: zone, now: now),
                       "Oct 25 – Nov 25 · renews in 31 days")
        XCTAssertEqual(Fmt.cycleRangeCaption(subscription(cycleSource: "rolling_30d"), timezone: zone),
                       "Claude Max 5x · last 30 days (day not set)")
        XCTAssertEqual(Fmt.cycleRangeCaption(subscription(), timezone: zone), "Claude Max 5x since Oct 25")
        XCTAssertEqual(Fmt.cycleDates(subscription(), timezone: TimeZone(secondsFromGMT: 0)!), "Oct 24 – Nov 24")
        XCTAssertEqual(SubscriptionValue.assumedDayHelp, "Renewal day unknown; set it in Settings")
    }

    func testRenewalTodayTomorrowAndExpired() {
        let zone = TimeZone(identifier: "Asia/Shanghai")!
        let end = "2026-11-24T16:00:00Z"
        XCTAssertEqual(Fmt.renewal(end, timezone: zone, now: ReportDates.parseTimestamp("2026-11-24T15:59:00Z")!),
                       "renews tomorrow")
        XCTAssertEqual(Fmt.renewal(end, timezone: zone, now: ReportDates.parseTimestamp("2026-11-25T10:00:00Z")!),
                       "renews today")
        XCTAssertEqual(Fmt.renewal(end, timezone: zone, now: ReportDates.parseTimestamp("2026-11-25T16:00:00Z")!),
                       "renewal date passed")
        XCTAssertEqual(Fmt.renewal("invalid", timezone: zone), "Renewal date unavailable")
        XCTAssertEqual(Fmt.cycleDates(subscription(start: "invalid"), timezone: zone), "Cycle dates unavailable")
    }

    func testRenewalAcrossDSTAndYearBoundary() {
        let zone = TimeZone(identifier: "America/New_York")!
        // 跨春季夏令时只有 47 小时，但仍是两个自然日。
        XCTAssertEqual(Fmt.renewal("2026-03-09T04:00:00Z", timezone: zone,
                                   now: ReportDates.parseTimestamp("2026-03-07T05:00:00Z")!), "renews in 2 days")
        let sub = subscription(start: "2026-12-25T05:00:00Z", end: "2027-01-25T05:00:00Z")
        XCTAssertEqual(Fmt.cycleCaption(sub, timezone: zone, now: ReportDates.parseTimestamp("2026-12-25T23:00:00Z")!),
                       "Dec 25 – Jan 25 · renews in 31 days")
    }

    func testAnchorSource() {
        XCTAssertEqual(SubscriptionValue.anchorSource(subscription()), "detected")
        XCTAssertEqual(SubscriptionValue.anchorSource(subscription(cycleSource: "manual")), "manual")
        XCTAssertEqual(SubscriptionValue.anchorSource(subscription(cycleSource: "rolling_30d", source: "manual")),
                       "not set · using last 30 days")
        XCTAssertEqual(SubscriptionValue.anchorSource(subscription(cycleSource: "unknown", source: "manual")), "manual")
    }

    func testBillingPages() {
        XCTAssertEqual(SubscriptionValue.billingPage(for: "claude")?.absoluteString, "https://claude.ai/settings/billing")
        XCTAssertEqual(SubscriptionValue.billingPage(for: "codex")?.absoluteString, "https://chatgpt.com/settings/billing")
        XCTAssertEqual(SubscriptionValue.billingPage(for: "antigravity")?.absoluteString, "https://one.google.com/subscriptions")
        XCTAssertNil(SubscriptionValue.billingPage(for: "future-agent"))
    }

    func testNudgeDismissalAndNewRollingAgent() {
        let rolling = subscription(cycleSource: "rolling_30d")
        let subs = ["codex": rolling, "claude": subscription(), "future-agent": rolling]
        XCTAssertEqual(RenewalNudge.pendingAgents(subscriptions: subs, dismissed: []), ["codex", "future-agent"])
        let dismissed = RenewalNudge.parseDismissed(" codex, ,codex,old-agent ")
        XCTAssertEqual(dismissed, ["codex", "old-agent"])
        XCTAssertEqual(RenewalNudge.pendingAgents(subscriptions: subs, dismissed: dismissed), ["future-agent"])
        let allDismissed = dismissed.union(["future-agent"])
        XCTAssertTrue(RenewalNudge.pendingAgents(subscriptions: subs, dismissed: allDismissed).isEmpty)
        XCTAssertEqual(RenewalNudge.parseDismissed(RenewalNudge.serializeDismissed(allDismissed)), allDismissed)
        XCTAssertTrue(RenewalNudge.pendingAgents(subscriptions: [:], dismissed: []).isEmpty)
        XCTAssertTrue(RenewalNudge.pendingAgents(subscriptions: ["codex": subscription()], dismissed: []).isEmpty)
        XCTAssertTrue(RenewalNudge.pendingAgents(subscriptions: ["codex": subscription(cycleSource: "unknown")], dismissed: []).isEmpty)
    }

    func testSubscriptionSettingsRoute() {
        XCTAssertEqual(SubscriptionSettingsRoute.agent(from: "settings:subscriptions:codex"), "codex")
        XCTAssertEqual(SubscriptionSettingsRoute.anchor(for: "codex"), "settings:subscriptions:codex")
        XCTAssertEqual(SubscriptionSettingsRoute.agent(from: "settings:subscriptions:future-agent"), "future-agent")
        for raw in ["settings", "settings-bottom", "settings:subscriptions:", "settings:subscriptions:codex:extra",
                    "overview:subscriptions:codex"] {
            XCTAssertNil(SubscriptionSettingsRoute.agent(from: raw), raw)
        }
    }

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
        XCTAssertEqual(r.subscriptions?["codex"]?.cycleSource, "rolling_30d")
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
