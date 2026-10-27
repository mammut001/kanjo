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

    /// DateFormatter 在 AM/PM 前用窄不换行空格，断言时统一成普通空格。
    private func plain(_ lines: [String]) -> [String] {
        lines.map { $0.replacingOccurrences(of: "\u{202F}", with: " ").replacingOccurrences(of: "\u{00A0}", with: " ") }
    }

    func testQuotaRows() {
        let utc = TimeZone(secondsFromGMT: 0)!
        let now = ReportDates.parseTimestamp("2026-10-24T12:00:00Z")!
        let codex = QuotaWindow(weeklyResetsAt: "2026-10-31T04:53:24Z", weeklyUsedPercent: 24.4,
                                fiveHourResetsAt: "2026-10-24T17:05:49Z", fiveHourWindowHours: 5, fiveHourUsedPercent: 108)
        let rows = SubscriptionValue.quotaRows(codex, timezone: utc, now: now, language: "en_US")
        XCTAssertEqual(rows.map(\.title), ["5-hour", "Weekly"])
        XCTAssertEqual(rows.map(\.percent), [100, 24.4])
        XCTAssertEqual(plain(rows.map(\.detail)), ["Resets in 5h 6m · 5:05 PM", "Resets in 6d 16h · Sat 4:53 AM"])
        // 5 小时窗口已结束 → 「—」+ Window ended；没有 5 小时窗口（Grok）→ 只有周一行
        let ended = QuotaWindow(weeklyResetsAt: "2026-10-27T05:00:00Z", weeklyUsedPercent: 40,
                                fiveHourResetsAt: nil, fiveHourWindowHours: 5)
        let e = SubscriptionValue.quotaRows(ended, timezone: utc, now: now, language: "en_US")
        XCTAssertEqual(e.first?.percent, nil)
        XCTAssertEqual(e.first?.detail, "Window ended")
        let grok = QuotaWindow(weeklyResetsAt: "2026-10-27T05:00:00Z", weeklyUsedPercent: 42)
        XCTAssertEqual(SubscriptionValue.quotaRows(grok, timezone: utc, now: now).map(\.id), ["weekly"])
        // 周重置已过（导出旧了）→ 也是已结束
        let stale = QuotaWindow(weeklyResetsAt: "2026-10-24T11:00:00Z", weeklyUsedPercent: 90)
        XCTAssertEqual(SubscriptionValue.quotaRows(stale, timezone: utc, now: now).first?.percent, nil)
        XCTAssertEqual(SubscriptionValue.quotaRows(nil, timezone: utc), [])

        // Extra windows (e.g. Antigravity 3p Claude/GPT group)
        let extra = [
            ExtraQuotaWindow(id: "antigravity-3p-weekly", title: "Claude/GPT 周", usedPercent: 10.0,
                             resetsAt: "2026-10-31T04:53:24Z", windowHours: 168),
            ExtraQuotaWindow(id: "antigravity-3p-5h", title: "Claude/GPT 5h", usedPercent: 50.0,
                             resetsAt: "2026-10-24T11:00:00Z", windowHours: 5),  // expired -> ended
        ]
        let agy = QuotaWindow(weeklyResetsAt: "2026-10-31T04:53:24Z", weeklyUsedPercent: 80.1,
                              fiveHourResetsAt: "2026-10-24T17:05:49Z", fiveHourWindowHours: 5, fiveHourUsedPercent: 25.0,
                              extraWindows: extra)
        let agyRows = SubscriptionValue.quotaRows(agy, timezone: utc, now: now, language: "en_US")
        XCTAssertEqual(agyRows.map(\.id), ["five_hour", "weekly", "antigravity-3p-weekly", "antigravity-3p-5h"])
        XCTAssertEqual(agyRows.map(\.title), ["5-hour", "Weekly", "Claude/GPT 周", "Claude/GPT 5h"])
        XCTAssertEqual(agyRows.map(\.percent), [25.0, 80.1, 10.0, nil])
        XCTAssertEqual(agyRows[2].detail.contains("Resets in"), true)
        XCTAssertEqual(agyRows[3].detail, "Window ended")
    }

    func testExtraWindowsDecoding() throws {
        // Backward compatibility: decoding without extra_windows
        let jsonWithout = """
        {
            "weekly_resets_at": "2026-10-31T04:53:24Z",
            "weekly_window_hours": 168,
            "source": "tokei"
        }
        """.data(using: .utf8)!
        let decodedWithout = try JSONDecoder().decode(QuotaWindow.self, from: jsonWithout)
        XCTAssertNil(decodedWithout.extraWindows)

        // Decoding with extra_windows
        let jsonWith = """
        {
            "weekly_resets_at": "2026-10-31T04:53:24Z",
            "weekly_window_hours": 168,
            "source": "tokei",
            "extra_windows": [
                {
                    "id": "antigravity-3p-weekly",
                    "title": "Claude/GPT 周",
                    "used_percent": 12.5,
                    "resets_at": "2026-10-31T04:53:24Z",
                    "window_hours": 168
                }
            ]
        }
        """.data(using: .utf8)!
        let decodedWith = try JSONDecoder().decode(QuotaWindow.self, from: jsonWith)
        XCTAssertEqual(decodedWith.extraWindows?.count, 1)
        XCTAssertEqual(decodedWith.extraWindows?.first?.id, "antigravity-3p-weekly")
        XCTAssertEqual(decodedWith.extraWindows?.first?.title, "Claude/GPT 周")
        XCTAssertEqual(decodedWith.extraWindows?.first?.usedPercent, 12.5)

        // Decoding with source: "live"
        let jsonLive = """
        {
            "weekly_resets_at": "2026-10-31T04:53:24Z",
            "weekly_window_hours": 168,
            "source": "live"
        }
        """.data(using: .utf8)!
        let decodedLive = try JSONDecoder().decode(QuotaWindow.self, from: jsonLive)
        XCTAssertEqual(decodedLive.source, "live")
    }

    func testRelativeResetAndLevels() {
        let now = ReportDates.parseTimestamp("2026-10-24T12:00:00Z")!
        XCTAssertEqual(SubscriptionValue.relative(from: now, to: now.addingTimeInterval(10)), "1 min")
        XCTAssertEqual(SubscriptionValue.relative(from: now, to: now.addingTimeInterval(59 * 60)), "59 min")
        XCTAssertEqual(SubscriptionValue.relative(from: now, to: now.addingTimeInterval(3600)), "1h 0m")
        XCTAssertEqual(SubscriptionValue.relative(from: now, to: now.addingTimeInterval(86400 + 2 * 3600)), "1d 2h")
        XCTAssertEqual(SubscriptionValue.level(nil), .normal)
        XCTAssertEqual(SubscriptionValue.level(79.9), .normal)
        XCTAssertEqual(SubscriptionValue.level(80), .warning)
        XCTAssertEqual(SubscriptionValue.level(94.9), .warning)
        XCTAssertEqual(SubscriptionValue.level(95), .critical)
    }

    func testResetTextZhHans() {
        AppDefaults.store.set(AppLanguage.zhHans.rawValue, forKey: SettingsKeys.appLanguage)
        let tz = TimeZone(identifier: "Asia/Shanghai")!
        let now = ReportDates.parseTimestamp("2026-10-24T12:00:00Z")!
        let reset = ReportDates.parseTimestamp("2026-10-27T02:00:00Z")!
        XCTAssertEqual(plain([SubscriptionValue.resetText(reset, timezone: tz, now: now, language: "zh-Hans")]),
                       ["2 天 14 小时后重置 · 周二 10:00"])
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
        for agent in ["claude", "codex", "grok", "antigravity", "copilot"] {
            let fromProjects = filtered.projects.reduce(0.0) { acc, p in
                acc + (p.byAgent.first { $0.agent == agent }?.cost ?? 0)
            }
            let fromBuckets = (filtered.unattributed.sessionsDetail + filtered.excluded.sessionsDetail)
                .filter { $0.agent == agent }
                .reduce(0.0) { $0 + $1.cost }
            XCTAssertEqual(usage.total(for: agent), fromProjects + fromBuckets, accuracy: 0.01, agent)
            XCTAssertGreaterThan(usage.total(for: agent), 0, agent)
        }
        XCTAssertEqual(usage.total(for: "qwen"), 0)

        let rows = SubscriptionValue.rows(of: r, now: now)
        XCTAssertEqual(rows.map(\.agent), rows.sorted { $0.usage > $1.usage }.map(\.agent))
        XCTAssertEqual(Set(rows.map(\.agent)), ["claude", "codex", "grok", "antigravity", "copilot"])
        for row in rows {
            let price = r.subscriptions?[row.agent]?.monthlyPriceUsd
            XCTAssertEqual(row.multiplier, SubscriptionValue.multiplier(usage: row.usage, monthlyPriceUsd: price))
            XCTAssertFalse(row.extraUsageEnabled)
        }

        let top = r.projects[0]
        let shares = SubscriptionValue.shares(project: top.id, report: r, now: now)
        XCTAssertFalse(shares.isEmpty)
        XCTAssertFalse(shares.contains { $0.agent == "qwen" })
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
