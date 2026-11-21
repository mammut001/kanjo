import Foundation

/// Agent 视图中单条模型明细（匹配总览 ModelAggregation 口径，附带缓存命中率与输出速度）。
public struct AgentModelRow: Equatable, Identifiable {
    public var model: String
    public var agent: String
    public var tokens: Tokens
    public var cost: Double
    public var estimated: Bool
    public var cacheHitRate: Double?
    public var perf: PerfSummary?

    public var id: String { "\(agent)/\(model)" }
}

/// Agent 在单个项目上的花费占比（「Where the money went」单段）。
public struct AgentProjectShare: Equatable, Identifiable, Sendable {
    public var projectId: String
    public var projectName: String
    public var cost: Double
    public var share: Double

    public var id: String { projectId }
}

/// 超出前 4 个项目后合并为「Others」的花费占比。
public struct AgentProjectOthers: Equatable, Sendable {
    public var count: Int
    public var cost: Double
    public var share: Double
}

/// 超出前 8 个模型后合并为「Others (N)」的汇总。
public struct AgentModelOthers: Equatable, Sendable {
    public var count: Int
    public var tokens: Int
    public var cost: Double
}

/// Agent 视图单行数据。
public struct AgentSummaryRow: Equatable, Identifiable {
    public var agent: String
    public var label: String
    public var tokens: Int
    public var tokenBreakdown: Tokens
    public var cacheHitRate: Double?
    public var cost: Double
    /// 在当前范围内所有活跃 agent 总 token 中的占比（全部行之和 = 1.0）。
    public var share: Double
    public var subscription: Subscription?
    /// 账期用量 ÷ 月费（与 SubscriptionValueCard 口径一致）。
    public var multiplier: Double?
    public var quotaRows: [QuotaRow]
    public var perf: PerfSummary?
    public var models: [AgentModelRow]
    public var othersModel: AgentModelOthers? = nil
    public var projectShares: [AgentProjectShare]
    public var othersProjectShare: AgentProjectOthers?
    public var antigravityAccountShares: [AntigravityAccountShare]

    public var id: String { agent }
}

/// Agent 视图顶部汇总与行列表。
public struct AgentSummaryReport: Equatable {
    public var totalCost: Double
    public var totalTokens: Int
    public var rows: [AgentSummaryRow]
}

/// 按 agent 聚合当前范围内的用量、额度窗口、性能样本与项目流向（纯函数，无 SwiftUI 依赖）。
public enum AgentSummary {
    public static func quotaReference(report: UsageReport, now: Date, isSnapshot: Bool) -> Date {
        guard isSnapshot, let windows = report.quotaWindows, !windows.isEmpty,
              windows.values.allSatisfy({ (ReportDates.parseTimestamp($0.weeklyResetsAt) ?? .distantPast) <= now }) else { return now }
        let resets = windows.values.compactMap { $0.fiveHourResetsAt.flatMap(ReportDates.parseTimestamp) }
        return resets.min().map { $0.addingTimeInterval(-6660) } ?? ReportDates.parseTimestamp(report.generatedAt) ?? now
    }

    /// 缓存命中率：cache_read ÷ (input + cache_read)；分母为 0 时返回 nil。
    public static func cacheHitRate(for tokens: Tokens) -> Double? {
        let denom = tokens.input + tokens.cacheRead
        guard denom > 0 else { return nil }
        return Double(tokens.cacheRead) / Double(denom)
    }

    public static func build(
        report: UsageReport,
        filtered: FilteredReport,
        now: Date = Date(),
        quotaNow: Date? = nil,
        cycleUsage: CycleUsage? = nil,
        models: [ModelCost]? = nil
    ) -> AgentSummaryReport {
        var agentCost: [String: Double] = [:]
        var agentTokens: [String: Int] = [:]
        var agentLabels = report.agentLabels

        // 1. 从项目（按日过滤后）汇总每个 agent 的花费与 token
        for fp in filtered.projects {
            for a in fp.byAgent {
                agentCost[a.agent, default: 0] += a.cost
                agentTokens[a.agent, default: 0] += a.tokens.total
                if agentLabels[a.agent] == nil || agentLabels[a.agent] == a.agent {
                    agentLabels[a.agent] = a.label
                }
            }
        }

        // 2. 从 unattributed / excluded 桶中补齐对应 agent 的花费与 token
        let bucketSessions = filtered.unattributed.sessionsDetail + filtered.excluded.sessionsDetail
        for s in bucketSessions {
            let (c, t) = filtered.spec.inRangeCostAndTokens(for: s)
            agentCost[s.agent, default: 0] += c
            agentTokens[s.agent, default: 0] += t
            if agentLabels[s.agent] == nil || agentLabels[s.agent] == s.agent {
                agentLabels[s.agent] = s.label
            }
        }

        // 3. 隐藏范围内 0 token 的 agent；按 tokens 降序（平局按花费降序、agent 升序）
        let activeAgents = agentTokens.keys
            .filter { (agentTokens[$0] ?? 0) > 0 }
            .sorted { a, b in
                let ta = agentTokens[a] ?? 0
                let tb = agentTokens[b] ?? 0
                if ta != tb { return ta > tb }
                let ca = agentCost[a] ?? 0
                let cb = agentCost[b] ?? 0
                if ca != cb { return ca > cb }
                return a < b
            }

        let totalActiveTokens = activeAgents.reduce(0) { $0 + (agentTokens[$1] ?? 0) }

        // 4. 预先准备跨行共享的数据（避免重复全量计算）
        let allModels = models ?? ModelAggregation.aggregate(in: filtered)
        var modelsByAgent: [String: [ModelCost]] = [:]
        for m in allModels {
            modelsByAgent[m.agent, default: []].append(m)
        }

        let cycleUsage = cycleUsage ?? SubscriptionValue.cycleUsage(of: report, now: now)
        let tz = RangeEngine.timezone(of: report)
        let exactBreakdowns = exactAllTimeBreakdowns(report: report)
        let inRangeSessionsByAgent = collectInRangeSessions(filtered: filtered)

        // 5. 构建每个 agent 的行数据
        var rows: [AgentSummaryRow] = []
        for agent in activeAgents {
            let tokens = agentTokens[agent] ?? 0
            let cost = agentCost[agent] ?? 0
            let share = totalActiveTokens > 0 ? Double(tokens) / Double(totalActiveTokens) : 0.0

            let breakdown: Tokens
            if filtered.spec.isAll {
                if let exact = exactBreakdowns[agent], exact.total > 0 {
                    breakdown = exact
                } else {
                    breakdown = Tokens(total: tokens)
                }
            } else {
                breakdown = apportionedBreakdown(
                    targetTokens: tokens,
                    inRangeSessions: inRangeSessionsByAgent[agent] ?? [],
                    spec: filtered.spec,
                    fallbackBreakdown: exactBreakdowns[agent]
                )
            }

            let sub = report.subscriptions?[agent]
            let multiplier = sub.flatMap {
                SubscriptionValue.multiplier(usage: cycleUsage.total(for: agent), monthlyPriceUsd: $0.monthlyPriceUsd)
            }
            let quotaRows = SubscriptionValue.quotaRows(report.quotaWindows?[agent], timezone: tz, now: quotaNow ?? now)
            let perf = PerfStats.summarize(report.perfByDay, range: filtered.spec, agent: agent)
            let perfByModel = PerfStats.byModel(report.perfByDay, range: filtered.spec, agent: agent)

            let sortedAgentModels = (modelsByAgent[agent] ?? []).sorted { a, b in
                if a.cost != b.cost { return a.cost > b.cost }
                if a.tokens.total != b.tokens.total { return a.tokens.total > b.tokens.total }
                return a.model < b.model
            }
            let (agentModelRows, othersModel) = buildTopModels(sortedAgentModels, perfByModel: perfByModel)

            let (projectShares, others) = buildProjectShares(agent: agent, projects: filtered.projects)
            let agyAccountShares = agent == "antigravity"
                ? AntigravityAccountLogic.shares(from: report.antigravityAccounts, range: filtered.spec)
                : []
            let label = agentLabels[agent] ?? AgentColors.label(for: agent)

            rows.append(AgentSummaryRow(
                agent: agent,
                label: label,
                tokens: tokens,
                tokenBreakdown: breakdown,
                cacheHitRate: cacheHitRate(for: breakdown),
                cost: cost,
                share: share,
                subscription: sub,
                multiplier: multiplier,
                quotaRows: quotaRows,
                perf: perf,
                models: agentModelRows,
                othersModel: othersModel,
                projectShares: projectShares,
                othersProjectShare: others,
                antigravityAccountShares: agyAccountShares
            ))
        }

        return AgentSummaryReport(
            totalCost: filtered.cost,
            totalTokens: filtered.tokens,
            rows: rows
        )
    }

    // MARK: - Helpers

    private static func exactAllTimeBreakdowns(report: UsageReport) -> [String: Tokens] {
        var out: [String: Tokens] = [:]
        for p in report.projects {
            for a in p.byAgent {
                out[a.agent] = (out[a.agent] ?? .zero) + a.tokens
            }
        }
        for s in report.buckets.unattributed.sessionsDetail + report.buckets.excluded.sessionsDetail {
            out[s.agent] = (out[s.agent] ?? .zero) + s.tokens
        }
        return out
    }

    private static func collectInRangeSessions(filtered: FilteredReport) -> [String: [Session]] {
        var out: [String: [Session]] = [:]
        for fp in filtered.projects {
            for s in fp.sessionsDetail {
                out[s.agent, default: []].append(s)
            }
        }
        for s in filtered.unattributed.sessionsDetail + filtered.excluded.sessionsDetail {
            out[s.agent, default: []].append(s)
        }
        return out
    }

    private static func apportionedBreakdown(
        targetTokens: Int,
        inRangeSessions: [Session],
        spec: RangeSpec,
        fallbackBreakdown: Tokens?
    ) -> Tokens {
        guard targetTokens > 0 else { return .zero }
        var wInput = 0.0
        var wOutput = 0.0
        var wCacheRead = 0.0
        var wCacheWrite = 0.0
        var wThinking = 0.0

        for s in inRangeSessions {
            let (_, t) = spec.inRangeCostAndTokens(for: s)
            guard t > 0 else { continue }
            let denom = Double(max(s.tokens.input + s.tokens.output + s.tokens.cacheRead + s.tokens.cacheWrite, s.tokens.total))
            guard denom > 0 else { continue }
            let scale = Double(t) / denom
            wInput += Double(s.tokens.input) * scale
            wOutput += Double(s.tokens.output) * scale
            wCacheRead += Double(s.tokens.cacheRead) * scale
            wCacheWrite += Double(s.tokens.cacheWrite) * scale
            wThinking += Double(s.tokens.thinking) * scale
        }

        let weightedSum = wInput + wOutput + wCacheRead + wCacheWrite
        let weights: [Double]
        let thinkingRatio: Double
        if weightedSum > 0 {
            weights = [wInput, wOutput, wCacheRead, wCacheWrite]
            thinkingRatio = wOutput > 0 ? min(1.0, max(0.0, wThinking / wOutput)) : 0.0
        } else if let fb = fallbackBreakdown,
                  (fb.input + fb.output + fb.cacheRead + fb.cacheWrite) > 0 {
            weights = [Double(fb.input), Double(fb.output), Double(fb.cacheRead), Double(fb.cacheWrite)]
            thinkingRatio = fb.output > 0 ? min(1.0, max(0.0, Double(fb.thinking) / Double(fb.output))) : 0.0
        } else {
            return Tokens(total: targetTokens)
        }

        let parts = apportion(total: targetTokens, weights: weights)
        let outTokens = parts[1]
        let thinking = Int(round(Double(outTokens) * thinkingRatio))
        return Tokens(
            input: parts[0],
            output: outTokens,
            cacheRead: parts[2],
            cacheWrite: parts[3],
            thinking: min(thinking, outTokens),
            total: targetTokens
        )
    }

    private static func apportion(total: Int, weights: [Double]) -> [Int] {
        guard !weights.isEmpty, total > 0 else { return Array(repeating: 0, count: weights.count) }
        let sumW = weights.reduce(0.0, +)
        guard sumW > 0 else { return Array(repeating: 0, count: weights.count) }
        let quotas = weights.map { Double(total) * ($0 / sumW) }
        var integers = quotas.map { Int(floor($0)) }
        var remainders = quotas.enumerated().map { (index: $0.offset, remainder: $0.element - Double(integers[$0.offset])) }
        let leftover = total - integers.reduce(0, +)
        remainders.sort { a, b in
            if abs(a.remainder - b.remainder) > 1e-9 { return a.remainder > b.remainder }
            return a.index < b.index
        }
        for i in 0..<min(leftover, remainders.count) {
            integers[remainders[i].index] += 1
        }
        return integers
    }

    private static func buildTopModels(
        _ sortedModels: [ModelCost],
        perfByModel: [String: PerfSummary],
        limit: Int = 8
    ) -> (top: [AgentModelRow], others: AgentModelOthers?) {
        let top = sortedModels.prefix(limit).map { m in
            AgentModelRow(
                model: m.model,
                agent: m.agent,
                tokens: m.tokens,
                cost: m.cost,
                estimated: m.estimated,
                cacheHitRate: cacheHitRate(for: m.tokens),
                perf: perfByModel[m.model]
            )
        }
        let rest = sortedModels.dropFirst(limit)
        let others: AgentModelOthers?
        if !rest.isEmpty {
            others = AgentModelOthers(
                count: rest.count,
                tokens: rest.reduce(0) { $0 + $1.tokens.total },
                cost: rest.reduce(0.0) { $0 + $1.cost }
            )
        } else {
            others = nil
        }
        return (top, others)
    }

    static func buildProjectShares(
        agent: String,
        projects: [FilteredProject],
        excluding hidden: Set<String> = []
    ) -> (top: [AgentProjectShare], others: AgentProjectOthers?) {
        var raw: [(id: String, name: String, cost: Double)] = []
        for fp in projects where !hidden.contains(fp.id) {
            if let a = fp.byAgent.first(where: { $0.agent == agent }), a.cost > 0 {
                raw.append((id: fp.id, name: fp.project.name, cost: a.cost))
            }
        }
        raw.sort { a, b in
            if a.cost != b.cost { return a.cost > b.cost }
            return a.id < b.id
        }
        let totalCost = raw.reduce(0.0) { $0 + $1.cost }
        guard totalCost > 0 else { return ([], nil) }

        let top = raw.prefix(4).map {
            AgentProjectShare(projectId: $0.id, projectName: $0.name, cost: $0.cost, share: $0.cost / totalCost)
        }
        let rest = raw.dropFirst(4)
        let others: AgentProjectOthers?
        if !rest.isEmpty {
            let restCost = rest.reduce(0.0) { $0 + $1.cost }
            others = restCost > 0
                ? AgentProjectOthers(count: rest.count, cost: restCost, share: restCost / totalCost)
                : nil
        } else {
            others = nil
        }
        return (top, others)
    }
}
