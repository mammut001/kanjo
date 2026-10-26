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

    /// 验证模型聚合在多项目之间正确求和，且正确包含缓存读取和写入。
    func testSumsAcrossProjectsAndIncludesCacheTokens() {
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

        let result = ModelAggregation.aggregate([p1, p2])

        XCTAssertEqual(result.count, 2)
        // opus 排序第一：总 token = 1000 + 1000 = 2000，包含 cacheRead (300+500=800) 与 cacheWrite (400+400=800)
        let opus = try? XCTUnwrap(result.first { $0.model == "opus" })
        XCTAssertEqual(opus?.tokens.total, 2000)
        XCTAssertEqual(opus?.tokens.cacheRead, 800)
        XCTAssertEqual(opus?.tokens.cacheWrite, 800)
        XCTAssertEqual(opus?.cost ?? 0, 25.0, accuracy: 1e-9)

        // haiku 排序第二：总 token = 100
        let haiku = try? XCTUnwrap(result.first { $0.model == "haiku" })
        XCTAssertEqual(haiku?.tokens.total, 100)
        XCTAssertEqual(haiku?.tokens.cacheRead, 30)
        XCTAssertEqual(haiku?.tokens.cacheWrite, 50)
        XCTAssertEqual(haiku?.cost ?? 0, 1.0, accuracy: 1e-9)
    }

    /// 验证聚合结果严格按总 token 数降序排列。
    func testSortedByTotalTokensDesc() {
        let p = makeProject(id: "p", models: [
            ModelCost(model: "small", agent: "claude", cost: 5.0, tokens: makeTokens(input: 10, output: 10, cacheRead: 10, cacheWrite: 10)), // 40
            ModelCost(model: "huge", agent: "claude", cost: 50.0, tokens: makeTokens(input: 1000, output: 1000, cacheRead: 1000, cacheWrite: 1000)), // 4000
            ModelCost(model: "medium", agent: "claude", cost: 20.0, tokens: makeTokens(input: 200, output: 200, cacheRead: 200, cacheWrite: 200)) // 800
        ])

        let result = ModelAggregation.aggregate([p])
        XCTAssertEqual(result.map(\.model), ["huge", "medium", "small"])
        XCTAssertEqual(result.map(\.tokens.total), [4000, 800, 40])
    }

    /// 验证聚合遵循时间范围：不在范围内的项目被剔除，在范围内的项目仅聚合范围中活跃的模型。
    func testRespectsTimeRange() {
        let sIn = Session(id: "s1", agent: "claude", label: "Claude Code", started: "2026-10-22T10:00:00Z",
                          ended: "2026-10-22T10:30:00Z", cwd: nil, branch: nil, models: ["sonnet"],
                          cost: 10.0, tokens: Tokens(total: 1000), share: 1, attribution: "dominant",
                          subagents: 0, title: "in-range session")
        let sOut = Session(id: "s2", agent: "claude", label: "Claude Code", started: "2026-08-01T10:00:00Z",
                           ended: "2026-08-01T10:30:00Z", cwd: nil, branch: nil, models: ["opus"],
                           cost: 20.0, tokens: Tokens(total: 2000), share: 1, attribution: "dominant",
                           subagents: 0, title: "out-of-range session")

        // 项目 1：在当前范围内活跃，活跃会话仅使用 sonnet
        let p1 = makeProject(id: "p1", models: [
            ModelCost(model: "sonnet", agent: "claude", cost: 10.0, tokens: Tokens(total: 1000)),
            ModelCost(model: "opus", agent: "claude", cost: 20.0, tokens: Tokens(total: 2000))
        ], sessions: [sIn, sOut])

        // 项目 2：在当前范围外（历史项目）
        let p2 = makeProject(id: "p2", models: [
            ModelCost(model: "gpt-4", agent: "codex", cost: 30.0, tokens: Tokens(total: 3000))
        ], sessions: [sOut])

        let fp1 = FilteredProject(
            project: p1,
            cost: 10.0,
            tokens: 1000,
            sessions: 1,
            byAgent: [],
            byDay: [],
            sessionsDetail: [sIn],
            firstActive: "2026-10-22",
            lastActive: "2026-10-22"
        )
        let fp2 = FilteredProject(
            project: p2,
            cost: 0,
            tokens: 0,
            sessions: 0,
            byAgent: [],
            byDay: [],
            sessionsDetail: [],
            firstActive: nil,
            lastActive: nil
        )

        // isAll = true 时，所有项目的全部模型均计入
        let allResult = ModelAggregation.aggregate(projects: [fp1, fp2], isAll: true)
        XCTAssertEqual(Set(allResult.map(\.model)), ["gpt-4", "opus", "sonnet"])

        // isAll = false 时：
        // 1. fp2 无用量，完全排除（gpt-4 不出现）
        // 2. fp1 仅 sonnet 在范围内的会话中出现，历史模型 opus 被排除
        let filteredResult = ModelAggregation.aggregate(projects: [fp1, fp2], isAll: false)
        XCTAssertEqual(filteredResult.count, 1)
        XCTAssertEqual(filteredResult.first?.model, "sonnet")
        XCTAssertEqual(filteredResult.first?.tokens.total, 1000)
        XCTAssertEqual(filteredResult.first?.cost ?? 0, 10.0, accuracy: 1e-9)
    }
}
