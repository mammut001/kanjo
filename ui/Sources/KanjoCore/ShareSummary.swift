import Foundation

public struct ShareSummary: Equatable {
    public struct AgentRow: Equatable {
        public var agent: String
        public var label: String
        public var tokens: Int
        public var tokenBreakdown: Tokens
        public var cacheHitRate: Double?
        public var cost: Double
        public var subscription: Subscription?
        public var multiplier: Double?
        public var sessionCount: Int?
        public var projectShares: [AgentProjectShare]
    }

    public struct AgentProjectShare: Equatable {
        public var name: String
        public var cost: Double
    }

    public struct ProjectShare: Equatable {
        public var name: String
        public var cost: Double
        public var share: Double
    }

    public struct Totals: Equatable {
        public var tokens: Int
        public var cost: Double
        public var agentsCount: Int
        public var sessions: Int
        public var input: Int
        public var output: Int
        public var cacheRead: Int
        public var cacheWrite: Int
        public var thinking: Int
    }

    public var agentRows: [AgentRow]
    public var agentSummaryRows: [AgentSummaryRow]
    public var totals: Totals
    public var topProjects: [ProjectShare]
    public var mosaicProjects: [Project]
    public var rangeLabel: String
    public var updated: Date

    public static func build(report: UsageReport, rangeRaw: String, now: Date = Date(), hiddenProjects: Set<String> = []) -> ShareSummary {
        let resolved = RangeEngine.resolve(raw: rangeRaw, report: report, now: now)
        let filtered = RangeEngine.filtered(report, range: resolved.spec, fallbackAgentFor: { RangeEngine.fallbackAgent(for: $0) })
        
        let agentSummary = AgentSummary.build(report: report, filtered: filtered, now: now)
        
        let agentRows = agentSummary.rows.map { row in
            AgentRow(
                agent: row.agent,
                label: row.label,
                tokens: row.tokens,
                tokenBreakdown: row.tokenBreakdown,
                cacheHitRate: row.cacheHitRate,
                cost: row.cost,
                subscription: row.subscription,
                multiplier: row.multiplier,
                sessionCount: filtered.projects.flatMap { $0.sessionsDetail }.filter { $0.agent == row.agent }.count,
                projectShares: filtered.projects.compactMap { p -> AgentProjectShare? in
                    guard let agentCost = p.byAgent.first(where: { $0.agent == row.agent })?.cost, agentCost > 0 else { return nil }
                    return AgentProjectShare(name: p.project.name, cost: agentCost)
                }
            )
        }
        
        var totalInput = 0
        var totalOutput = 0
        var totalCacheRead = 0
        var totalCacheWrite = 0
        var totalThinking = 0
        
        for row in agentSummary.rows {
            totalInput += row.tokenBreakdown.input
            totalOutput += row.tokenBreakdown.output
            totalCacheRead += row.tokenBreakdown.cacheRead
            totalCacheWrite += row.tokenBreakdown.cacheWrite
            totalThinking += row.tokenBreakdown.thinking
        }
        
        let totals = Totals(
            tokens: agentSummary.totalTokens,
            cost: agentSummary.totalCost,
            agentsCount: agentSummary.rows.count,
            sessions: filtered.sessions,
            input: totalInput,
            output: totalOutput,
            cacheRead: totalCacheRead,
            cacheWrite: totalCacheWrite,
            thinking: totalThinking
        )
        
        var projectCosts: [String: (name: String, cost: Double)] = [:]
        for p in filtered.projects.filter { !hiddenProjects.contains($0.id) } {
            projectCosts[p.id] = (name: p.project.name, cost: (projectCosts[p.id]?.cost ?? 0) + p.cost)
        }
        
        let sortedProjects = projectCosts.values.sorted { $0.cost > $1.cost }.prefix(5)
        let topProjects = sortedProjects.map { p in
            ProjectShare(name: p.name, cost: p.cost, share: p.cost / max(1, agentSummary.totalCost))
        }
        
        let mosaicProjects = filtered.projects.filter { $0.cost > 0 && !hiddenProjects.contains($0.id) }.map { $0.projected }
        
        return ShareSummary(
            agentRows: agentRows,
            agentSummaryRows: agentSummary.rows,
            totals: totals,
            topProjects: Array(topProjects),
            mosaicProjects: mosaicProjects,
            rangeLabel: RangeCaptionBuilder.caption(for: resolved.range, report: report)?.text ?? resolved.range.longLabel,
            updated: ReportDates.parseTimestamp(report.generatedAt) ?? now
        )
    }
}
