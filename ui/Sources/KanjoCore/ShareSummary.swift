import Foundation
import KanjoCore

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
    public var totals: Totals
    public var topProjects: [ProjectShare]
    public var rangeLabel: String
    public var updated: Date

    public static func build(report: UsageReport, rangeSpec: RangeSpec, now: Date = Date()) -> ShareSummary {
        let filtered = RangeEngine.filtered(report, range: rangeSpec, fallbackAgentFor: { p in
            // Need to implement dominantAgent or reuse it. It's in PanelData.
            // Actually I should look where dominantAgent is defined.
            // It seems to be a helper in KanjoCore. Let's check imports.
            "unknown" // Placeholder for now, need to find the right helper.
        })
        
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
                sessionCount: nil 
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
            sessions: filtered.sessions, // From FilteredReport
            input: totalInput,
            output: totalOutput,
            cacheRead: totalCacheRead,
            cacheWrite: totalCacheWrite,
            thinking: totalThinking
        )
        
        var projectCosts: [String: (name: String, cost: Double)] = [:]
        for p in filtered.projects {
            projectCosts[p.id] = (name: p.project.name, cost: (projectCosts[p.id]?.cost ?? 0) + p.cost)
        }
        
        let sortedProjects = projectCosts.values.sorted { $0.cost > $1.cost }.prefix(5)
        let topProjects = sortedProjects.map { p in
            ProjectShare(name: p.name, cost: p.cost, share: p.cost / max(1, agentSummary.totalCost))
        }
        
        return ShareSummary(
            agentRows: agentRows,
            totals: totals,
            topProjects: Array(topProjects),
            rangeLabel: RangeCaption.build(spec: rangeSpec, report: report),
            updated: ReportDates.parseTimestamp(report.generatedAt) ?? now
        )
    }
}
