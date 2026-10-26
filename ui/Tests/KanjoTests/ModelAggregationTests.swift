import XCTest
@testable import KanjoCore

final class ModelAggregationTests: KanjoTestCase {
    private func makeTokens(input: Int = 10, output: Int = 20, cacheRead: Int = 30, cacheWrite: Int = 40) -> Tokens {
        Tokens(input: input, output: output, cacheRead: cacheRead, cacheWrite: cacheWrite,
               thinking: 5, total: input + output + cacheRead + cacheWrite)
    }

    private func makeProject(id: String, models: [ModelCost], sessions: [Session] = []) -> Project {
        let totalCost = models.reduce(0.0) { $0 + $1.cost }
        let totalTokens = models.reduce(0) { $0 + $1.tokens.total }
        return Project(
            id: id,
            name: id,
            remote: nil,
            paths: ["/path/\(id)"],
            pathMissing: false,
            cost: totalCost,
            tokens: Tokens(total: totalTokens),
            sessions: sessions.count,
            firstActive: "2026-10-10",
            lastActive: "2026-10-24",
            byAgent: [],
            byModel: models,
            byDay: [],
            byBranch: [],
            sessionsDetail: sessions
        )
    }

    private func makeFilteredReport(
        projects: [FilteredProject],
        unattributed: FilteredBucket = FilteredBucket(cost: 0, tokens: 0, sessions: 0, sessionsDetail: []),
        excluded: FilteredBucket = FilteredBucket(cost: 0, tokens: 0, sessions: 0, sessionsDetail: []),
        isAll: Bool = false
    ) -> FilteredReport {
        let range: TimeRange = isAll ? .all : .days7
        let spec = RangeSpec(range: range, calendar: Calendar(identifier: .gregorian))
        let totalCost = projects.reduce(0.0) { $0 + $1.cost } + unattributed.cost + excluded.cost
        let totalTokens = projects.reduce(0) { $0 + $1.tokens } + unattributed.tokens + excluded.tokens
        let totalSessions = projects.reduce(0) { $0 + $1.sessions } + unattributed.sessions + excluded.sessions
        return FilteredReport(
            spec: spec,
            projects: projects,
            unattributed: unattributed,
            excluded: excluded,
            cost: totalCost,
            tokens: totalTokens,
            sessions: totalSessions,
            firstActive: "2026-10-18",
            lastActive: "2026-10-24"
        )
    }

    /// 验证 All 范围：直接汇总各项目的 by_model（精确值），且正确包含缓存读取和写入并按总 token 降序排序。
    func testAllRangeUsesProjectByModelExact() {
        let t1 = makeTokens(input: 100, output: 200, cacheRead: 300, cacheWrite: 400) // total = 1000
        let t2 = makeTokens(input: 50, output: 50, cacheRead: 500, cacheWrite: 400)   // total = 1000
        let t3 = makeTokens(input: 10, output: 10, cacheRead: 30, cacheWrite: 50)     // total = 100

        let p1 = makeProject(id: "p1", models: [
            ModelCost(model: "opus", agent: "claude", cost: 15.0, tokens: t1),
            ModelCost(model: "haiku", agent: "claude", cost: 1.0, tokens: t3)
        ])
        let p2 = makeProject(id: "p2", models: [
            ModelCost(model: "opus", agent: "claude", cost: 10.0, tokens: t2)
        ])

        let fp1 = FilteredProject(project: p1, cost: p1.cost, tokens: p1.tokens.total, sessions: 0,
                                  byAgent: [], byDay: [], sessionsDetail: [])
        let fp2 = FilteredProject(project: p2, cost: p2.cost, tokens: p2.tokens.total, sessions: 0,
                                  byAgent: [], byDay: [], sessionsDetail: [])

        let report = makeFilteredReport(projects: [fp1, fp2], isAll: true)
        let result = ModelAggregation.aggregate(in: report)

        XCTAssertEqual(result.count, 2)
        // opus 排序第一：总 token = 1000 + 1000 = 2000，包含 cacheRead (300+500=800) 与 cacheWrite (400+400=800)
        let opus = try? XCTUnwrap(result.first { $0.model == "opus" })
        XCTAssertEqual(opus?.tokens.total, 2000)
        XCTAssertEqual(opus?.tokens.cacheRead, 800)
        XCTAssertEqual(opus?.tokens.cacheWrite, 800)
        XCTAssertEqual(opus?.cost ?? 0, 25.0, accuracy: 1e-9)
        XCTAssertFalse(opus?.estimated ?? true)

        // haiku 排序第二：总 token = 100
        let haiku = try? XCTUnwrap(result.first { $0.model == "haiku" })
        XCTAssertEqual(haiku?.tokens.total, 100)
        XCTAssertEqual(haiku?.tokens.cacheRead, 30)
        XCTAssertEqual(haiku?.tokens.cacheWrite, 50)
        XCTAssertEqual(haiku?.cost ?? 0, 1.0, accuracy: 1e-9)
    }

    /// 验证非 All 范围：不使用各项目全量 by_model 的累计值，仅从当前范围过滤后的会话中汇总。
    func testNonAllRangeAggregatesOnlyFromInRangeSessions() {
        // 项目的全量历史 by_model：opus 拥有 100,000 token 与 $100 花费
        let historicalOpus = ModelCost(model: "opus", agent: "claude", cost: 100.0, tokens: Tokens(total: 100_000))
        let historicalSonnet = ModelCost(model: "sonnet", agent: "claude", cost: 50.0, tokens: Tokens(total: 50_000))
        let p = makeProject(id: "p", models: [historicalOpus, historicalSonnet])

        // 但在当前 7 天范围内，仅发生了一次 1,200 token 的 sonnet 会话
        let inRangeSession = Session(
            id: "s1",
            agent: "claude",
            label: "Claude Code",
            started: "2026-10-22T10:00:00Z",
            ended: "2026-10-22T10:30:00Z",
            cwd: nil,
            branch: nil,
            models: ["sonnet"],
            cost: 1.2,
            tokens: makeTokens(input: 200, output: 200, cacheRead: 400, cacheWrite: 400), // total = 1200
            share: 1,
            attribution: "dominant",
            subagents: 0,
            title: "recent session"
        )

        let fp = FilteredProject(
            project: p,
            cost: inRangeSession.cost,
            tokens: inRangeSession.tokens.total,
            sessions: 1,
            byAgent: [],
            byDay: [],
            sessionsDetail: [inRangeSession]
        )

        let report = makeFilteredReport(projects: [fp], isAll: false)
        let result = ModelAggregation.aggregate(in: report)

        // 仅出现 sonnet，不出现历史的 opus；且 sonnet 的数值为 1200 / $1.2，绝非全量 50,000 / $50
        XCTAssertEqual(result.count, 1)
        XCTAssertEqual(result.first?.model, "sonnet")
        XCTAssertEqual(result.first?.tokens.total, 1200)
        XCTAssertEqual(result.first?.cost ?? 0, 1.2, accuracy: 1e-9)
        XCTAssertFalse(result.first?.estimated ?? true)
    }

    /// 验证多模型会话平分 token，整除余数给首个模型，且标记 estimated=true；单模型会话标记 estimated=false。
    func testMultiModelSessionSplitsEvenlyWithRemainderToFirstModel() {
        // 会话总 token = 100 (input: 10, output: 20, cacheRead: 30, cacheWrite: 40)
        // 3 个模型平分：
        // input 10 / 3 = 3，余 1 -> m0: 4, m1: 3, m2: 3 (和 10)
        // output 20 / 3 = 6，余 2 -> m0: 8, m1: 6, m2: 6 (和 20)
        // cacheRead 30 / 3 = 10，余 0 -> m0: 10, m1: 10, m2: 10 (和 30)
        // cacheWrite 40 / 3 = 13，余 1 -> m0: 14, m1: 13, m2: 13 (和 40)
        // total: m0: 36, m1: 32, m2: 32 (和 100)
        let multiSession = Session(
            id: "s_multi",
            agent: "claude",
            label: "Claude Code",
            started: "2026-10-22T10:00:00Z",
            ended: "2026-10-22T10:30:00Z",
            cwd: nil,
            branch: nil,
            models: ["m0", "m1", "m2"],
            cost: 30.0,
            tokens: makeTokens(input: 10, output: 20, cacheRead: 30, cacheWrite: 40),
            share: 1,
            attribution: "dominant",
            subagents: 0,
            title: nil
        )

        let fp = FilteredProject(
            project: makeProject(id: "p", models: []),
            cost: multiSession.cost,
            tokens: multiSession.tokens.total,
            sessions: 1,
            byAgent: [],
            byDay: [],
            sessionsDetail: [multiSession]
        )

        let report = makeFilteredReport(projects: [fp], isAll: false)
        let result = ModelAggregation.aggregate(in: report)

        XCTAssertEqual(result.count, 3)
        let m0 = try? XCTUnwrap(result.first { $0.model == "m0" })
        let m1 = try? XCTUnwrap(result.first { $0.model == "m1" })
        let m2 = try? XCTUnwrap(result.first { $0.model == "m2" })

        // 验证整除余数分配与不丢失任何 token
        XCTAssertEqual(m0?.tokens.input, 4)
        XCTAssertEqual(m1?.tokens.input, 3)
        XCTAssertEqual(m2?.tokens.input, 3)

        XCTAssertEqual(m0?.tokens.output, 8)
        XCTAssertEqual(m1?.tokens.output, 6)
        XCTAssertEqual(m2?.tokens.output, 6)

        XCTAssertEqual(m0?.tokens.total, 36)
        XCTAssertEqual(m1?.tokens.total, 32)
        XCTAssertEqual(m2?.tokens.total, 32)

        XCTAssertEqual((m0?.tokens.total ?? 0) + (m1?.tokens.total ?? 0) + (m2?.tokens.total ?? 0), 100)
        XCTAssertEqual(m0?.cost ?? 0, 10.0, accuracy: 1e-9)
        XCTAssertEqual(m1?.cost ?? 0, 10.0, accuracy: 1e-9)
        XCTAssertEqual(m2?.cost ?? 0, 10.0, accuracy: 1e-9)

        // 多模型会话标记为 estimated = true
        XCTAssertTrue(m0?.estimated ?? false)
        XCTAssertTrue(m1?.estimated ?? false)
        XCTAssertTrue(m2?.estimated ?? false)
    }

    /// 验证范围报告下模型行总 token 之和严格等于总览 hero 总 token 数（包含项目会话与未归属/已排除会话）。
    func testSumInvariantMatchesHeroTotalTokens() {
        let sProjSingle = Session(
            id: "s1", agent: "claude", label: "Claude Code", started: "2026-10-22T08:00:00Z",
            ended: "2026-10-22T08:10:00Z", cwd: nil, branch: nil, models: ["opus"],
            cost: 5.0, tokens: makeTokens(input: 100, output: 200, cacheRead: 300, cacheWrite: 400), // 1000
            share: 1, attribution: "dominant", subagents: 0, title: nil
        )
        let sProjMulti = Session(
            id: "s2", agent: "claude", label: "Claude Code", started: "2026-10-22T09:00:00Z",
            ended: "2026-10-22T09:10:00Z", cwd: nil, branch: nil, models: ["sonnet", "haiku", "opus"],
            cost: 9.0, tokens: makeTokens(input: 77, output: 88, cacheRead: 99, cacheWrite: 111), // 375
            share: 1, attribution: "dominant", subagents: 0, title: nil
        )
        let sUnattributed = Session(
            id: "s3", agent: "codex", label: "Codex CLI", started: "2026-10-22T10:00:00Z",
            ended: "2026-10-22T10:10:00Z", cwd: nil, branch: nil, models: ["gpt-4o", "gpt-4o-mini"],
            cost: 4.0, tokens: makeTokens(input: 15, output: 25, cacheRead: 35, cacheWrite: 45), // 120
            share: 1, attribution: "cwd", subagents: 0, title: nil
        )
        let sExcluded = Session(
            id: "s4", agent: "antigravity", label: "Antigravity", started: "2026-10-22T11:00:00Z",
            ended: "2026-10-22T11:10:00Z", cwd: nil, branch: nil, models: ["gemini-pro"],
            cost: 2.0, tokens: makeTokens(input: 50, output: 50, cacheRead: 50, cacheWrite: 50), // 200
            share: 1, attribution: "override", subagents: 0, title: nil
        )

        let fp = FilteredProject(
            project: makeProject(id: "p1", models: []),
            cost: sProjSingle.cost + sProjMulti.cost,
            tokens: sProjSingle.tokens.total + sProjMulti.tokens.total,
            sessions: 2,
            byAgent: [],
            byDay: [],
            sessionsDetail: [sProjSingle, sProjMulti]
        )
        let u = FilteredBucket(
            cost: sUnattributed.cost,
            tokens: sUnattributed.tokens.total,
            sessions: 1,
            sessionsDetail: [sUnattributed]
        )
        let e = FilteredBucket(
            cost: sExcluded.cost,
            tokens: sExcluded.tokens.total,
            sessions: 1,
            sessionsDetail: [sExcluded]
        )

        let report = makeFilteredReport(projects: [fp], unattributed: u, excluded: e, isAll: false)

        // 总览 hero 展示的总 token 数
        let heroTokens = report.tokens
        XCTAssertEqual(heroTokens, 1000 + 375 + 120 + 200)

        // 模型聚合列表
        let models = ModelAggregation.aggregate(in: report)
        let sumOfModelTokens = models.reduce(0) { $0 + $1.tokens.total }

        // 不变量：模型行的总 token 数严格等于总览 hero 的总 token 数
        XCTAssertEqual(sumOfModelTokens, heroTokens)
    }

    /// 验证跨天（例如昨天 -> 今天）会话在非 All 范围下只计入范围内的份额，不变量依然严格成立且不会把历史全量带入。
    func testSumInvariantHoldsWithSessionSpanningYesterdayToToday() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(secondsFromGMT: 0)!

        let todayStart = cal.date(from: DateComponents(year: 2026, month: 10, day: 22, hour: 0, minute: 0, second: 0))!
        let todayEnd = cal.date(from: DateComponents(year: 2026, month: 10, day: 23, hour: 0, minute: 0, second: 0))!
        let todaySpec = RangeSpec(range: .today, calendar: cal, start: todayStart, end: todayEnd)

        // 会话从昨天 18:00 到今天 06:00，全量历史数值非常大（$558.42, 1,880,000 token）
        let spanningSession = Session(
            id: "s_spanning",
            agent: "claude",
            label: "Claude Code",
            started: "2026-10-21T18:00:00Z",
            ended: "2026-10-22T06:00:00Z",
            cwd: nil,
            branch: nil,
            models: ["claude-opus-5-5"],
            cost: 558.42,
            tokens: makeTokens(input: 400_000, output: 480_000, cacheRead: 500_000, cacheWrite: 500_000), // total = 1,880,000
            share: 1,
            attribution: "dominant",
            subagents: 0,
            title: "spanning session"
        )

        // 今天在项目按日数据中，该项目今天的实际用量只有 $91.00 与 91,000 token
        let todayDayCost = DayCost(day: "2026-10-22", cost: 91.00, tokens: 91_000)
        let fp = FilteredProject(
            project: makeProject(id: "p_today", models: []),
            cost: todayDayCost.cost,
            tokens: todayDayCost.tokens,
            sessions: 1,
            byAgent: [AgentCost(agent: "claude", label: "Claude Code", cost: 91.00, tokens: Tokens(total: 91_000), sessions: 1)],
            byDay: [todayDayCost],
            sessionsDetail: [spanningSession]
        )

        let report = FilteredReport(
            spec: todaySpec,
            projects: [fp],
            unattributed: FilteredBucket(cost: 0, tokens: 0, sessions: 0, sessionsDetail: []),
            excluded: FilteredBucket(cost: 0, tokens: 0, sessions: 0, sessionsDetail: []),
            cost: 91.00,
            tokens: 91_000,
            sessions: 1,
            firstActive: "2026-10-22",
            lastActive: "2026-10-22"
        )

        let models = ModelAggregation.aggregate(in: report)
        XCTAssertEqual(models.count, 1)

        let opus = try? XCTUnwrap(models.first { $0.model == "claude-opus-5-5" })
        // 绝不能是全量 1,880,000 / $558.42，而必须严格等于今天范围内的 hero 总额 91,000 / $91.00
        XCTAssertEqual(opus?.tokens.total, 91_000)
        XCTAssertEqual(opus?.cost ?? 0, 91.00, accuracy: 1e-4)

        let sumOfModelTokens = models.reduce(0) { $0 + $1.tokens.total }
        XCTAssertEqual(sumOfModelTokens, report.tokens)

        // 进一步验证：若会话自带 per-session byDay 数据
        let sessionWithByDay = Session(
            id: "s_by_day",
            agent: "claude",
            label: "Claude Code",
            started: "2026-10-21T18:00:00Z",
            ended: "2026-10-22T06:00:00Z",
            cwd: nil,
            branch: nil,
            models: ["claude-opus-5-5"],
            cost: 50.0,
            tokens: makeTokens(input: 1000, output: 1000, cacheRead: 1000, cacheWrite: 1000), // total 4000
            share: 1,
            attribution: "dominant",
            subagents: 0,
            title: "session with by day",
            byDay: [
                DayCost(day: "2026-10-21", cost: 40.0, tokens: 3200),
                DayCost(day: "2026-10-22", cost: 10.0, tokens: 800)
            ]
        )

        let fpWithByDay = FilteredProject(
            project: makeProject(id: "p_by_day", models: []),
            cost: 10.0,
            tokens: 800,
            sessions: 1,
            byAgent: [],
            byDay: [DayCost(day: "2026-10-22", cost: 10.0, tokens: 800)],
            sessionsDetail: [sessionWithByDay]
        )

        let reportWithByDay = FilteredReport(
            spec: todaySpec,
            projects: [fpWithByDay],
            unattributed: FilteredBucket(cost: 0, tokens: 0, sessions: 0, sessionsDetail: []),
            excluded: FilteredBucket(cost: 0, tokens: 0, sessions: 0, sessionsDetail: []),
            cost: 10.0,
            tokens: 800,
            sessions: 1,
            firstActive: "2026-10-22",
            lastActive: "2026-10-22"
        )

        let modelsWithByDay = ModelAggregation.aggregate(in: reportWithByDay)
        XCTAssertEqual(modelsWithByDay.count, 1)
        XCTAssertEqual(modelsWithByDay.first?.tokens.total, 800)
        XCTAssertEqual(modelsWithByDay.first?.cost ?? 0, 10.0, accuracy: 1e-4)
        XCTAssertEqual(modelsWithByDay.reduce(0) { $0 + $1.tokens.total }, reportWithByDay.tokens)
    }
}
