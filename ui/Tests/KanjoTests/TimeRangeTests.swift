import XCTest
@testable import KanjoCore

final class TimeRangeTests: KanjoTestCase {
    private let shanghai = TimeZone(identifier: "Asia/Shanghai")!
    private var cal: Calendar { RangeEngine.calendar(timezone: shanghai) }

    private func ts(_ s: String) -> Date { ReportDates.parseTimestamp(s)! }
    private func day(_ s: String) -> Date { HeatStrip.parseDay(s, calendar: cal)! }

    // 2026-10-24 是周六。now = 上海时间 Oct 24 15:00。
    private let now = ReportDates.parseTimestamp("2026-10-24T07:00:00Z")!

    func testMenuBarPrefix() {
        XCTAssertEqual(TimeRange.allCases.map(\.menuBarSuffix), [nil, "today", "7d", "30d", nil, nil, nil])
        XCTAssertEqual(TimeRange.today.shortLabel, "Today")
        XCTAssertEqual(TimeRange.today.longLabel, "Today")
        XCTAssertEqual(TimeRange.today.menuBarSuffix, "today")
        XCTAssertEqual(TimeRange.billingCycle.shortLabel, "Cycle")
        XCTAssertEqual(TimeRange.billingCycle.longLabel, "Billing cycle")
        XCTAssertNil(TimeRange.billingCycle.menuBarSuffix)
    }

    private func spec(_ r: TimeRange, quota: [String: QuotaWindow]? = nil,
                      subscriptions: [String: Subscription]? = nil, now: Date? = nil) -> RangeSpec {
        RangeEngine.dateInterval(for: r, now: now ?? self.now, timezone: shanghai, quota: quota,
                                 subscriptions: subscriptions)
    }

    private func sub(plan: String = "max_5x", label: String = "Claude Max 5x", price: Double? = 100,
                     start: String, anchor: Int? = 25, cycleSource: String = "subscription_date") -> Subscription {
        Subscription(plan: plan, planLabel: label, monthlyPriceUsd: price, cycleStart: start,
                     cycleEnd: "2026-11-25T00:00:00Z", anchorDay: anchor, cycleSource: cycleSource,
                     extraUsageEnabled: false, source: "detected")
    }

    // MARK: - 区间

    func testAllIsUnbounded() {
        let s = spec(.all)
        XCTAssertTrue(s.isAll)
        XCTAssertNil(s.start); XCTAssertNil(s.end)
        XCTAssertTrue(s.includes(.distantPast, agent: "anything"))
    }

    func testToday() {
        let s = spec(.today)
        XCTAssertEqual(s.start, day("2026-10-24"))
        XCTAssertEqual(s.end, now)
        // 边界日：Oct 24 算，Oct 23 不算。
        XCTAssertTrue(s.includes(dayStart: day("2026-10-24"), dayEnd: day("2026-10-25"), agent: "claude"))
        XCTAssertFalse(s.includes(dayStart: day("2026-10-23"), dayEnd: day("2026-10-24"), agent: "claude"))
        // 上海 Oct 24 00:00 = UTC Oct 23 16:00。
        // 包括当天启动的 session
        XCTAssertTrue(s.includes(ts("2026-10-23T16:00:00Z"), agent: "claude"))
        XCTAssertTrue(s.includes(ts("2026-10-24T06:59:59Z"), agent: "claude"))
        // 排除昨天 23:59 (上海 Oct 23 23:59:00 = UTC Oct 23 15:59:00，23:59:59 = UTC Oct 23 15:59:59)
        XCTAssertFalse(s.includes(ts("2026-10-23T15:59:00Z"), agent: "claude"))
        XCTAssertFalse(s.includes(ts("2026-10-23T15:59:59Z"), agent: "claude"))
        // 排除 end 及未来
        XCTAssertFalse(s.includes(now, agent: "claude"))
    }

    func testSevenAndThirtyDays() {
        let s7 = spec(.days7)
        XCTAssertEqual(s7.start, day("2026-10-18"))
        XCTAssertEqual(s7.end, now)
        let s30 = spec(.days30)
        XCTAssertEqual(s30.start, day("2026-09-25"))
        // 边界日：Oct 18 算，Oct 17 不算。
        XCTAssertTrue(s7.includes(dayStart: day("2026-10-18"), dayEnd: day("2026-10-19"), agent: "claude"))
        XCTAssertFalse(s7.includes(dayStart: day("2026-10-17"), dayEnd: day("2026-10-18"), agent: "claude"))
        XCTAssertTrue(s7.includes(dayStart: day("2026-10-24"), dayEnd: day("2026-10-25"), agent: "claude"))
        // 上海 Oct 18 00:00 = UTC Oct 17 16:00。
        XCTAssertTrue(s7.includes(ts("2026-10-17T16:00:00Z"), agent: "x"))
        XCTAssertFalse(s7.includes(ts("2026-10-17T15:59:59Z"), agent: "x"))
    }

    func testLastWeekIsPreviousMondayToSunday() {
        let s = spec(.lastWeek)
        XCTAssertEqual(s.start, day("2026-10-12"))
        XCTAssertEqual(s.end, day("2026-10-19"))
        XCTAssertTrue(s.includes(dayStart: day("2026-10-18"), dayEnd: day("2026-10-19"), agent: "c"))   // 周日
        XCTAssertFalse(s.includes(dayStart: day("2026-10-19"), dayEnd: day("2026-10-20"), agent: "c"))  // 本周一
        XCTAssertFalse(s.includes(dayStart: day("2026-10-11"), dayEnd: day("2026-10-12"), agent: "c"))
    }

    func testMondayAlgorithmOnEveryWeekday() {
        // Oct 19 (Mon) … Oct 25 (Sun) 都属于同一周，上周是 Oct 12–18。
        for d in 19...25 {
            let n = ts(String(format: "2026-10-%02dT04:00:00Z", d))
            XCTAssertEqual(spec(.lastWeek, now: n).start, day("2026-10-12"), "Oct \(d)")
            XCTAssertEqual(RangeEngine.mondayOnOrBefore(cal.startOfDay(for: n), calendar: cal), day("2026-10-19"))
        }
        // 周一凌晨（上海 00:30）：本周就是这周，上周是前一周。
        XCTAssertEqual(spec(.lastWeek, now: ts("2026-10-25T16:30:00Z")).start, day("2026-10-19"))
        // 时区决定是哪一天：UTC 周日 20:00 在上海已是周一。
        let utcSpec = RangeEngine.dateInterval(for: .lastWeek, now: ts("2026-10-25T20:00:00Z"),
                                               timezone: TimeZone(identifier: "UTC")!, quota: nil)
        XCTAssertEqual(utcSpec.start, ts("2026-10-12T00:00:00Z"))
        XCTAssertEqual(spec(.lastWeek, now: ts("2026-10-25T20:00:00Z")).start, day("2026-10-19"))
    }

    func testSinceResetPerAgentStarts() {
        let quota = ["claude": QuotaWindow(weeklyResetsAt: "2026-10-27T10:00:00Z"),
                     "codex": QuotaWindow(weeklyResetsAt: "2026-10-28T08:00:00Z", source: "manual"),
                     "grok": QuotaWindow(weeklyResetsAt: "2026-10-27T05:00:00Z", source: "tokei")]
        let s = spec(.sinceReset, quota: quota)
        XCTAssertEqual(s.agentStarts["claude"], ts("2026-10-20T10:00:00Z"))
        XCTAssertEqual(s.agentStarts["codex"], ts("2026-10-21T08:00:00Z"))
        XCTAssertEqual(s.agentStarts["grok"], ts("2026-10-20T05:00:00Z"))
        XCTAssertNil(s.window(for: "antigravity"))
        XCTAssertFalse(s.includes(now, agent: "antigravity"))
        XCTAssertTrue(s.includes(ts("2026-10-20T10:00:00Z"), agent: "claude"))
        XCTAssertFalse(s.includes(ts("2026-10-20T10:00:00Z"), agent: "codex"))
        // Oct 20（上海）与 claude 的窗口相交，与 codex 的不相交。
        XCTAssertTrue(s.includes(dayStart: day("2026-10-20"), dayEnd: day("2026-10-21"), agent: "claude"))
        XCTAssertFalse(s.includes(dayStart: day("2026-10-20"), dayEnd: day("2026-10-21"), agent: "codex"))
    }

    func testWindowStartRollsBackAndForward() {
        // 下次重置在一个多窗口之后（起点仍在未来）→ 再往前推一个窗口。
        let far = QuotaWindow(weeklyResetsAt: "2026-11-02T07:00:00Z")    // now + 9 天
        XCTAssertEqual(RangeEngine.windowStart(far, now: now), ts("2026-10-19T07:00:00Z"))
        // 缓存过期：重置时间已过去 → 当前窗口从那次重置开始。
        let stale = QuotaWindow(weeklyResetsAt: "2026-10-22T07:00:00Z")
        XCTAssertEqual(RangeEngine.windowStart(stale, now: now), ts("2026-10-22T07:00:00Z"))
        let fiveHour = QuotaWindow(weeklyResetsAt: "2026-10-24T09:00:00Z", weeklyWindowHours: 5)
        XCTAssertEqual(RangeEngine.windowStart(fiveHour, now: now), ts("2026-10-24T04:00:00Z"))
        let grokDay = QuotaWindow(weeklyResetsAt: "2026-10-25T05:00:00Z", weeklyWindowHours: 24)
        XCTAssertEqual(RangeEngine.windowStart(grokDay, now: now), ts("2026-10-24T05:00:00Z"))
        XCTAssertNil(RangeEngine.windowStart(QuotaWindow(weeklyResetsAt: "garbage"), now: now))
        XCTAssertNil(RangeEngine.windowStart(QuotaWindow(weeklyResetsAt: "2026-10-27T10:00:00Z", weeklyWindowHours: 0), now: now))
    }

    func testWindowStartAcrossDST() {
        let ny = TimeZone(identifier: "America/New_York")!
        let calNY = RangeEngine.calendar(timezone: ny)

        // 1. Spring forward: 2026-03-08 02:00 NY turns UTC-5 into UTC-4.
        // Stale reset is Sunday 10:00 AM EST (15:00:00Z).
        // 1 calendar week later is Sunday 10:00 AM EDT (14:00:00Z).
        // A fixed 168h step would drift to 15:00:00Z (11:00 AM EDT).
        let staleSpring = QuotaWindow(weeklyResetsAt: "2026-03-01T15:00:00Z")
        let nowSpring = ts("2026-03-10T15:00:00Z") // Tuesday after DST
        let startSpring = RangeEngine.windowStart(staleSpring, now: nowSpring, calendar: calNY)
        XCTAssertEqual(startSpring, ts("2026-03-08T14:00:00Z"))

        // Date interval with report timezone flows to windowStart
        let specSpring = RangeEngine.dateInterval(for: .sinceReset, now: nowSpring, timezone: ny,
                                                  quota: ["claude": staleSpring])
        XCTAssertEqual(specSpring.agentStarts["claude"], ts("2026-03-08T14:00:00Z"))

        // 2. Fall back: 2026-11-01 02:00 NY turns UTC-4 into UTC-5.
        // Stale reset is Sunday 10:00 AM EDT (14:00:00Z).
        // 1 calendar week later is Sunday 10:00 AM EST (15:00:00Z).
        // A fixed 168h step would drift to 14:00:00Z (09:00 AM EST).
        let staleFall = QuotaWindow(weeklyResetsAt: "2026-10-25T14:00:00Z")
        let nowFall = ts("2026-11-04T15:00:00Z") // Wednesday after DST
        let startFall = RangeEngine.windowStart(staleFall, now: nowFall, calendar: calNY)
        XCTAssertEqual(startFall, ts("2026-11-01T15:00:00Z"))

        // 3. Non-168h window keeps fixed steps
        let dayWindow = QuotaWindow(weeklyResetsAt: "2026-03-08T06:00:00Z", weeklyWindowHours: 24)
        let dayStart = RangeEngine.windowStart(dayWindow, now: ts("2026-03-09T08:00:00Z"), calendar: calNY)
        XCTAssertEqual(dayStart, ts("2026-03-09T06:00:00Z"))
    }

    func testBillingCyclePerAgentStarts() {
        let subs = ["claude": sub(start: "2026-09-24T16:00:00Z"),
                    "codex": sub(plan: "plus", label: "ChatGPT Plus", price: 20,
                                 start: "2026-09-30T16:00:00Z", anchor: nil, cycleSource: "rolling_30d")]
        let s = spec(.billingCycle, subscriptions: subs)
        XCTAssertEqual(s.agentStarts["claude"], ts("2026-09-24T16:00:00Z"))
        XCTAssertEqual(s.agentStarts["codex"], ts("2026-09-30T16:00:00Z"))
        XCTAssertNil(s.window(for: "antigravity"))
        XCTAssertFalse(s.includes(now, agent: "antigravity"))
        // 上海 9 月 25 日零点起算 claude；前一天整天不相交。
        XCTAssertFalse(s.includes(dayStart: day("2026-09-24"), dayEnd: day("2026-09-25"), agent: "claude"))
        XCTAssertTrue(s.includes(dayStart: day("2026-09-25"), dayEnd: day("2026-09-26"), agent: "claude"))
        // codex 从上海 10 月 1 日零点起；9 月 30 日整天不相交。
        XCTAssertFalse(s.includes(dayStart: day("2026-09-30"), dayEnd: day("2026-10-01"), agent: "codex"))
        XCTAssertTrue(s.includes(dayStart: day("2026-10-01"), dayEnd: day("2026-10-02"), agent: "codex"))
        XCTAssertTrue(s.includes(ts("2026-09-24T16:00:00Z"), agent: "claude"))
        XCTAssertFalse(s.includes(ts("2026-09-24T16:00:00Z"), agent: "codex"))
    }

    func testBillingCycleUsesEachAgentsOwnStart() {
        let subs = ["claude": sub(start: "2026-10-17T16:00:00Z"),   // 上海 10 月 18 日
                    "codex": sub(plan: "plus", label: "ChatGPT Plus", price: 20,
                                 start: "2026-10-21T16:00:00Z", anchor: nil, cycleSource: "rolling_30d")]
        let f = RangeEngine.filter(project(), range: spec(.billingCycle, subscriptions: subs), fallbackAgent: "claude")
        // claude：Oct 18（2）+ Oct 20（4）；codex：只有 Oct 22（6）；antigravity 无订阅，不计入。
        XCTAssertEqual(f.cost, 12, accuracy: 1e-9)
        XCTAssertEqual(f.tokens, 1200)
        XCTAssertEqual(Set(f.byAgent.map(\.agent)), ["claude", "codex"])
        XCTAssertEqual(f.byDay.map(\.day), ["2026-10-18", "2026-10-20", "2026-10-22"])
        XCTAssertEqual(f.byDay.first { $0.day == "2026-10-20" }?.byAgent, ["claude": 4])
        XCTAssertEqual(f.sessions, 3)
        XCTAssertEqual(f.byAgent.first { $0.agent == "claude" }?.sessions, 2)
        XCTAssertEqual(f.byAgent.first { $0.agent == "codex" }?.sessions, 1)
    }

    func testBillingCycleWithoutSubscriptionIncludesNothing() {
        for subs in [nil, [String: Subscription]()] {
            let s = spec(.billingCycle, subscriptions: subs)
            XCTAssertTrue(s.agentStarts.isEmpty)
            XCTAssertFalse(s.includes(now, agent: "claude"))
            let f = RangeEngine.filter(project(), range: s, fallbackAgent: "claude")
            XCTAssertEqual(f.cost, 0)
            XCTAssertFalse(f.hasUsage)
        }
    }

    func testBillingCycleIgnoresUnparseableStart() {
        let s = spec(.billingCycle, subscriptions: ["claude": sub(start: "not-a-date")])
        XCTAssertNil(s.window(for: "claude"))
        XCTAssertFalse(s.includes(now, agent: "claude"))
    }

    func testSinceResetWithoutQuotaIncludesNothing() {
        let s = spec(.sinceReset, quota: nil)
        XCTAssertTrue(s.agentStarts.isEmpty)
        let f = RangeEngine.filter(project(), range: s, fallbackAgent: "claude")
        XCTAssertEqual(f.cost, 0); XCTAssertEqual(f.tokens, 0); XCTAssertEqual(f.sessions, 0)
        XCTAssertFalse(f.hasUsage)
    }

    // MARK: - 过滤

    private func session(_ agent: String, _ started: String, cost: Double = 1) -> Session {
        Session(id: UUID().uuidString, agent: agent, label: agent.capitalized, started: started, ended: started,
                cwd: nil, branch: nil, models: [], cost: cost, tokens: Tokens(total: 10), share: 1,
                attribution: "dominant", subagents: 0, title: nil)
    }

    /// 上海时区的天：Oct 12、Oct 18、Oct 20、Oct 22。
    private func project(byAgentTokens: Bool = true) -> Project {
        func d(_ day: String, _ split: [String: Double], _ toks: [String: Int]) -> DayCost {
            DayCost(day: day, cost: split.values.reduce(0, +), tokens: toks.values.reduce(0, +),
                    byAgent: split, byAgentTokens: byAgentTokens ? toks : nil)
        }
        let days = [d("2026-10-12", ["claude": 1], ["claude": 100]),
                    d("2026-10-18", ["claude": 2, "codex": 3], ["claude": 200, "codex": 300]),
                    d("2026-10-20", ["claude": 4, "antigravity": 5], ["claude": 400, "antigravity": 500]),
                    d("2026-10-22", ["codex": 6], ["codex": 600])]
        let sessions = [session("codex", "2026-10-22T03:00:00Z", cost: 6),
                        session("antigravity", "2026-10-20T05:00:00Z", cost: 5),
                        session("claude", "2026-10-20T05:00:00Z", cost: 4),    // claude 重置（10:00Z）之前
                        session("codex", "2026-10-18T03:00:00Z", cost: 3),
                        session("claude", "2026-10-18T02:00:00Z", cost: 2),
                        session("claude", "2026-10-12T02:00:00Z", cost: 1)]
        let agents = ["claude": 7.0, "codex": 9.0, "antigravity": 5.0]
        return Project(id: "p", name: "p", remote: nil, paths: [], pathMissing: false,
                       cost: 21, tokens: Tokens(total: 2100), sessions: 6,
                       firstActive: "2026-10-12", lastActive: "2026-10-22",
                       byAgent: agents.sorted { $0.value > $1.value }.map { kv in
                           AgentCost(agent: kv.key, label: kv.key.capitalized, cost: kv.value,
                                     tokens: Tokens(total: Int(kv.value * 100)),
                                     sessions: sessions.filter { $0.agent == kv.key }.count)
                       },
                       byModel: [], byDay: days, byBranch: [], sessionsDetail: sessions)
    }

    func testSevenDaysFilter() {
        let f = RangeEngine.filter(project(), range: spec(.days7), fallbackAgent: "claude")
        XCTAssertEqual(f.cost, 20, accuracy: 1e-9)
        XCTAssertEqual(f.tokens, 2000)
        XCTAssertEqual(f.sessions, 5)
        XCTAssertEqual(f.byDay.map(\.day), ["2026-10-18", "2026-10-20", "2026-10-22"])
        XCTAssertEqual(f.firstActive, "2026-10-18"); XCTAssertEqual(f.lastActive, "2026-10-22")
        XCTAssertEqual(f.byAgent.map(\.agent), ["codex", "claude", "antigravity"])
        XCTAssertEqual(f.byAgent.first?.tokens.total, 900)
        XCTAssertEqual(f.byAgent.first?.sessions, 2)
        XCTAssertEqual(f.projected.cost, 20, accuracy: 1e-9)
        XCTAssertEqual(f.projected.sessionsDetail.count, 5)
    }

    func testLastWeekFilter() {
        let f = RangeEngine.filter(project(), range: spec(.lastWeek), fallbackAgent: "claude")
        XCTAssertEqual(f.cost, 6, accuracy: 1e-9)       // Oct 12 + Oct 18
        XCTAssertEqual(f.tokens, 600)
        XCTAssertEqual(f.sessions, 3)
    }

    func testSinceResetFilterPerAgent() {
        let quota = ["claude": QuotaWindow(weeklyResetsAt: "2026-10-27T10:00:00Z"),
                     "codex": QuotaWindow(weeklyResetsAt: "2026-10-28T08:00:00Z")]
        let f = RangeEngine.filter(project(), range: spec(.sinceReset, quota: quota), fallbackAgent: "claude")
        // claude：Oct 20 那天与窗口相交（4）；codex：只有 Oct 22（6）；antigravity 无 quota，不计入。
        XCTAssertEqual(f.cost, 10, accuracy: 1e-9)
        XCTAssertEqual(f.tokens, 1000)
        XCTAssertEqual(Set(f.byAgent.map(\.agent)), ["claude", "codex"])
        XCTAssertEqual(f.byDay.map(\.day), ["2026-10-20", "2026-10-22"])
        XCTAssertEqual(f.byDay.first?.byAgent, ["claude": 4])
        XCTAssertEqual(f.byDay.first?.cost ?? 0, 4, accuracy: 1e-9)
        // 会话按精确时刻：claude 那条 05:00Z 早于重置，不算；codex Oct 22 算。
        XCTAssertEqual(f.sessions, 1)
        XCTAssertEqual(f.sessionsDetail.map(\.agent), ["codex"])
        XCTAssertEqual(f.byAgent.first { $0.agent == "claude" }?.sessions, 0)
    }

    func testMissingByAgentTokensFallsBackToFallbackAgent() {
        let quota = ["codex": QuotaWindow(weeklyResetsAt: "2026-10-28T08:00:00Z")]
        let p = project(byAgentTokens: false)
        let all7 = RangeEngine.filter(p, range: spec(.days7), fallbackAgent: "codex")
        XCTAssertEqual(all7.tokens, 2000)
        XCTAssertEqual(all7.byAgent.first { $0.agent == "codex" }?.tokens.total, 2000)
        XCTAssertEqual(all7.byAgent.first { $0.agent == "claude" }?.tokens.total, 0)
        // sinceReset 下只有 codex 有 quota：回退到 codex 的 tokens 按 codex 的窗口算（Oct 22 一天 600）。
        let sr = RangeEngine.filter(p, range: spec(.sinceReset, quota: quota), fallbackAgent: "codex")
        XCTAssertEqual(sr.tokens, 600)
        XCTAssertEqual(sr.cost, 6, accuracy: 1e-9)
        // 缺 by_agent（cost）同样回退。
        var old = p
        old.byDay = old.byDay.map { DayCost(day: $0.day, cost: $0.cost, tokens: $0.tokens) }
        let f = RangeEngine.filter(old, range: spec(.days7), fallbackAgent: "claude")
        XCTAssertEqual(f.byAgent.map(\.agent).first, "claude")
        XCTAssertEqual(f.byAgent.first?.cost ?? 0, 20, accuracy: 1e-9)
    }

    func testSessionCountingRangeOverlap() {
        let todaySpec = spec(.today)

        // 1. 会话昨天开始、今天仍在用 -> 计入 Today
        let sessionActiveToday = Session(
            id: "s1", agent: "claude", label: "Claude Code",
            started: "2026-10-23T10:00:00Z", ended: "2026-10-24T02:00:00Z",
            cost: 5, tokens: Tokens(total: 50), share: 1, attribution: "dominant", subagents: 0
        )
        XCTAssertTrue(todaySpec.includes(sessionActiveToday))

        // 2. 会话在范围前已结束 -> 不计入 Today
        let sessionEndedBefore = Session(
            id: "s2", agent: "claude", label: "Claude Code",
            started: "2026-10-23T10:00:00Z", ended: "2026-10-23T15:59:00Z",
            cost: 5, tokens: Tokens(total: 50), share: 1, attribution: "dominant", subagents: 0
        )
        XCTAssertFalse(todaySpec.includes(sessionEndedBefore))

        // 3. 有按日数据：优先使用按日数据
        // 跨天会话，但按日数据表明今天没有用量（仅昨天有用量） -> 不计入 Today
        let sessionWithYesterdayOnly = Session(
            id: "s3", agent: "claude", label: "Claude Code",
            started: "2026-10-23T10:00:00Z", ended: "2026-10-24T02:00:00Z",
            cost: 5, tokens: Tokens(total: 50), share: 1, attribution: "dominant", subagents: 0,
            byDay: [DayCost(day: "2026-10-23", cost: 5, tokens: 50)]
        )
        XCTAssertFalse(todaySpec.includes(sessionWithYesterdayOnly))

        // 有今天用量 -> 计入 Today
        let sessionWithTodayUsage = Session(
            id: "s4", agent: "claude", label: "Claude Code",
            started: "2026-10-23T10:00:00Z", ended: "2026-10-24T02:00:00Z",
            cost: 5, tokens: Tokens(total: 50), share: 1, attribution: "dominant", subagents: 0,
            byDay: [
                DayCost(day: "2026-10-23", cost: 3, tokens: 30),
                DayCost(day: "2026-10-24", cost: 2, tokens: 20)
            ]
        )
        XCTAssertTrue(todaySpec.includes(sessionWithTodayUsage))

        // 4. 项目过滤验证（project row / overview summary）
        let dayToday = DayCost(day: "2026-10-24", cost: 2, tokens: 20, byAgent: ["claude": 2], byAgentTokens: ["claude": 20])
        let p = Project(
            id: "proj1", name: "proj1", remote: nil, paths: [], pathMissing: false,
            cost: 7, tokens: Tokens(total: 70), sessions: 2,
            firstActive: "2026-10-23", lastActive: "2026-10-24",
            byAgent: [AgentCost(agent: "claude", label: "Claude", cost: 7, tokens: Tokens(total: 70), sessions: 2)],
            byModel: [], byDay: [dayToday], byBranch: [],
            sessionsDetail: [sessionActiveToday, sessionEndedBefore]
        )
        let filteredProject = RangeEngine.filter(p, range: todaySpec, fallbackAgent: "claude")
        XCTAssertEqual(filteredProject.sessions, 1)
        XCTAssertEqual(filteredProject.sessionsDetail.count, 1)
        XCTAssertEqual(filteredProject.sessionsDetail.first?.id, "s1")

        // 5. 桶过滤验证
        let bucket = SessionBucket(
            cost: 10, tokens: Tokens(total: 100), sessions: 2,
            firstActive: "2026-10-23", lastActive: "2026-10-24",
            sessionsDetail: [sessionActiveToday, sessionEndedBefore]
        )
        let filteredBucket = RangeEngine.filter(bucket, range: todaySpec)
        XCTAssertEqual(filteredBucket.sessions, 1)
        XCTAssertEqual(filteredBucket.sessionsDetail.count, 1)
        XCTAssertEqual(filteredBucket.sessionsDetail.first?.id, "s1")
    }

    // MARK: - 夹具

    private func fixture() throws -> UsageReport {
        try ReportDecoder.decode(Data(contentsOf: DefaultPaths.sampleFixture))
    }

    private func fallback(_ p: Project) -> String { dominantAgent(p.byAgent)?.agent ?? "unknown" }

    func testAllEqualsReport() throws {
        let r = try fixture()
        let f = RangeEngine.filtered(r, range: RangeEngine.spec(.all, report: r, now: now), fallbackAgentFor: fallback)
        XCTAssertEqual(f.cost, r.totals.cost)
        XCTAssertEqual(f.tokens, r.totals.tokens.total)
        XCTAssertEqual(f.sessions, r.totals.sessions)
        XCTAssertEqual(f.firstActive, r.totals.firstActive)
        XCTAssertEqual(f.lastActive, r.totals.lastActive)
        XCTAssertEqual(f.projects.map(\.id), r.projects.map(\.id))
        for (fp, p) in zip(f.projects, r.projects) {
            XCTAssertEqual(fp.projected, p, p.id)
            XCTAssertEqual(fp.cost, p.cost); XCTAssertEqual(fp.tokens, p.tokens.total); XCTAssertEqual(fp.sessions, p.sessions)
        }
        XCTAssertEqual(f.unattributed.cost, r.buckets.unattributed.cost)
        XCTAssertEqual(f.excluded.sessions, r.buckets.excluded.sessions)
    }

    /// 走累加路径但区间无界：结果与报告原值一致（金额容忍 0.01）。
    func testUnboundedIntervalMatchesReport() throws {
        let r = try fixture()
        let cal = RangeEngine.calendar(timezone: RangeEngine.timezone(of: r))
        let spec = RangeSpec(range: .days30, calendar: cal, start: .distantPast, end: .distantFuture)
        let f = RangeEngine.filtered(r, range: spec, fallbackAgentFor: fallback)
        XCTAssertEqual(f.cost, r.totals.cost, accuracy: 0.01)
        XCTAssertEqual(f.tokens, r.totals.tokens.total)
        XCTAssertEqual(f.sessions, r.totals.sessions)
        for p in r.projects {
            let fp = try XCTUnwrap(f.project(p.id))
            XCTAssertEqual(fp.cost, p.cost, accuracy: 0.01, p.id)
            XCTAssertEqual(fp.tokens, p.tokens.total, p.id)
            XCTAssertEqual(fp.sessions, p.sessions, p.id)
            XCTAssertEqual(fp.byDay.map(\.day), p.byDay.map(\.day), p.id)
            for a in p.byAgent {
                let fa = try XCTUnwrap(fp.byAgent.first { $0.agent == a.agent }, "\(p.id) \(a.agent)")
                XCTAssertEqual(fa.cost, a.cost, accuracy: 0.01)
                XCTAssertEqual(fa.tokens.total, a.tokens.total)
                XCTAssertEqual(fa.sessions, a.sessions)
            }
        }
    }

    func testFixtureRangesAreConsistent() throws {
        let r = try fixture()
        XCTAssertEqual(r.quotaWindows?["claude"]?.source, "tokei")
        XCTAssertNil(r.quotaWindows?["antigravity"])
        XCTAssertEqual(r.subscriptions?["claude"]?.plan, "max_5x")
        XCTAssertNil(r.subscriptions?["antigravity"])
        for range in TimeRange.allCases {
            let f = RangeEngine.filtered(r, range: RangeEngine.spec(range, report: r, now: now), fallbackAgentFor: fallback)
            XCTAssertLessThanOrEqual(f.cost, r.totals.cost + 0.01, range.rawValue)
            XCTAssertEqual(f.projects.map(\.cost), f.projects.map(\.cost).sorted(by: >), range.rawValue)
            let sum = f.projects.reduce(0) { $0 + $1.cost } + f.unattributed.cost + f.excluded.cost
            XCTAssertEqual(f.cost, sum, accuracy: 0.01, range.rawValue)
            for p in f.projects {
                XCTAssertEqual(p.byDay.reduce(0) { $0 + $1.cost }, p.cost, accuracy: 1e-6)
                XCTAssertEqual(p.byAgent.reduce(0) { $0 + $1.cost }, p.cost, accuracy: 1e-6)
                if range == .sinceReset || range == .billingCycle {
                    XCTAssertFalse(p.byAgent.contains { $0.agent == "antigravity" })
                }
            }
        }
    }

    func testFilterSessionBucketUsesInRangeShare() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(secondsFromGMT: 0)!

        let todayStart = cal.date(from: DateComponents(year: 2026, month: 10, day: 22, hour: 0, minute: 0, second: 0))!
        let todayEnd = cal.date(from: DateComponents(year: 2026, month: 10, day: 23, hour: 0, minute: 0, second: 0))!
        let todaySpec = RangeSpec(range: .today, calendar: cal, start: todayStart, end: todayEnd)

        // 会话 1：带 byDay，跨两天（昨天 $30/3000 tokens，今天 $10/1000 tokens）
        let sWithByDay = Session(
            id: "s1", agent: "claude", label: "Claude Code",
            started: "2026-10-21T18:00:00Z", ended: "2026-10-22T06:00:00Z",
            cwd: nil, branch: nil, models: ["opus"],
            cost: 40.0, tokens: Tokens(total: 4000), share: 1, attribution: "none", subagents: 0,
            byDay: [
                DayCost(day: "2026-10-21", cost: 30.0, tokens: 3000),
                DayCost(day: "2026-10-22", cost: 10.0, tokens: 1000)
            ]
        )

        // 会话 2：不带 byDay，跨 12 小时（昨天 18:00 到今天 06:00，刚好今天占 50%）
        let sOverlap = Session(
            id: "s2", agent: "codex", label: "Codex CLI",
            started: "2026-10-21T18:00:00Z", ended: "2026-10-22T06:00:00Z",
            cwd: nil, branch: nil, models: ["codex"],
            cost: 20.0, tokens: Tokens(total: 2000), share: 1, attribution: "none", subagents: 0
        )

        let bucket = SessionBucket(
            cost: 60.0, tokens: Tokens(total: 6000), sessions: 2,
            firstActive: "2026-10-21", lastActive: "2026-10-22",
            sessionsDetail: [sWithByDay, sOverlap]
        )

        let filtered = RangeEngine.filter(bucket, range: todaySpec)
        XCTAssertEqual(filtered.sessions, 2)
        // sWithByDay 的今天份额为 $10 / 1000 tokens；sOverlap 的今天时间重叠份额为 50% = $10 / 1000 tokens
        // 合计在 Today 下应为 $20.00 / 2000 tokens，而非全量的 $60.00 / 6000 tokens
        XCTAssertEqual(filtered.cost, 20.0, accuracy: 1e-4)
        XCTAssertEqual(filtered.tokens, 2000)
    }
}
