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
        XCTAssertEqual(SubscriptionValue.billingPage(for: "copilot")?.absoluteString, "https://github.com/settings/copilot")
        XCTAssertEqual(SubscriptionValue.billingPage(for: "grok")?.absoluteString, "https://x.com/settings/premium")
        XCTAssertEqual(SubscriptionValue.billingPage(for: "minimax")?.absoluteString, "https://platform.minimax.io")
        XCTAssertEqual(SubscriptionValue.billingPage(for: "qwen")?.absoluteString, "https://dashscope.console.aliyun.com")
        XCTAssertEqual(SubscriptionValue.billingPage(for: "commandcode")?.absoluteString, "https://commandcode.ai")
        XCTAssertEqual(SubscriptionValue.billingPage(for: "opencode")?.absoluteString, "https://opencode.ai")
        XCTAssertNil(SubscriptionValue.billingPage(for: "future-agent"))
    }

    func testRowsForArbitraryAgentKeys() throws {
        var r = try ReportDecoder.decode(Data(contentsOf: DefaultPaths.sampleFixture))
        let customSubs: [String: Subscription] = [
            "grok": Subscription(plan: "supergrok", planLabel: "SuperGrok", monthlyPriceUsd: 30,
                                 cycleStart: "2026-09-24T16:00:00Z", cycleEnd: "2026-10-24T16:00:00Z",
                                 anchorDay: nil, cycleSource: "rolling_30d", extraUsageEnabled: false, source: "detected"),
            "copilot": Subscription(plan: "pro", planLabel: "Copilot Pro", monthlyPriceUsd: 10,
                                    cycleStart: "2026-09-24T16:00:00Z", cycleEnd: "2026-10-24T16:00:00Z",
                                    anchorDay: 15, cycleSource: "manual", extraUsageEnabled: false, source: "manual"),
            "minimax": Subscription(plan: "starter", planLabel: "MiniMax Coding Plan Starter", monthlyPriceUsd: 10,
                                    cycleStart: "2026-09-24T16:00:00Z", cycleEnd: "2026-10-24T16:00:00Z",
                                    anchorDay: nil, cycleSource: "rolling_30d", extraUsageEnabled: false, source: "manual"),
            "qwen": Subscription(plan: "coding_plan", planLabel: "Qwen Coding Plan Pro", monthlyPriceUsd: 50,
                                 cycleStart: "2026-09-24T16:00:00Z", cycleEnd: "2026-10-24T16:00:00Z",
                                 anchorDay: nil, cycleSource: "rolling_30d", extraUsageEnabled: false, source: "manual"),
            "custom_bot": Subscription(plan: "special", planLabel: "Custom Bot", monthlyPriceUsd: 15,
                                       cycleStart: "2026-09-24T16:00:00Z", cycleEnd: "2026-10-24T16:00:00Z",
                                       anchorDay: 1, cycleSource: "manual", extraUsageEnabled: false, source: "manual"),
        ]
        r.subscriptions = customSubs
        let rows = SubscriptionValue.rows(of: r)
        XCTAssertEqual(Set(rows.map { $0.agent }), Set(customSubs.keys))
        // Verify all 5 arbitrary agents have corresponding rows built
        XCTAssertEqual(rows.count, 5)
        for row in rows {
            let expected = customSubs[row.agent]!
            XCTAssertEqual(row.planLabel, expected.planLabel)
            XCTAssertEqual(row.monthlyPriceUsd, expected.monthlyPriceUsd)
        }
        // Unsubscribed agent is absent
        XCTAssertFalse(rows.contains { $0.agent == "unsubscribed_agent" })
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
                    "settings:subscriptions:codex:edit", "overview:subscriptions:codex"] {
            XCTAssertNil(SubscriptionSettingsRoute.agent(from: raw), raw)
        }
        XCTAssertEqual(SubscriptionSettingsRoute.editAgent(from: "settings:subscriptions:codex:edit"), "codex")
        XCTAssertEqual(SubscriptionSettingsRoute.editAgent(from: "settings:subscriptions:future-agent:edit"), "future-agent")
        XCTAssertEqual(SubscriptionSettingsRoute.parse("settings:subscriptions:minimax:edit")?.agent, "minimax")
        XCTAssertEqual(SubscriptionSettingsRoute.parse("settings:subscriptions:minimax:edit")?.isEdit, true)
        XCTAssertEqual(SubscriptionSettingsRoute.parse("settings:subscriptions:minimax")?.agent, "minimax")
        XCTAssertEqual(SubscriptionSettingsRoute.parse("settings:subscriptions:minimax")?.isEdit, false)
        for raw in ["settings", "settings-bottom", "settings:subscriptions:codex", "settings:subscriptions:codex:extra",
                    "settings:subscriptions::edit", "settings:subscriptions:codex:edit:extra"] {
            XCTAssertNil(SubscriptionSettingsRoute.editAgent(from: raw), raw)
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
