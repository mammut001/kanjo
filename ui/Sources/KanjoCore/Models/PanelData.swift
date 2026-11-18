import Foundation

public struct PanelData: Sendable, Equatable {
    public let rangeSpec: RangeSpec
    public let filteredReport: FilteredReport
    public let subscriptionRows: [SubscriptionRow]
    public let agentSummary: AgentSummaryReport
    public let now: Date

    public static func compute(report: UsageReport, rangeRaw: String, now: Date) -> PanelData? {
        guard let range = TimeRange(rawValue: rangeRaw) else { return nil }
        let spec = RangeEngine.spec(range, report: report, now: now)
        let filtered = RangeEngine.filtered(report, range: spec, fallbackAgentFor: { p in
            dominantAgent(p.byAgent)?.agent ?? p.byAgent.first?.agent ?? "unknown"
        })
        let subscriptionRows = SubscriptionValue.rows(of: report, now: now)
        let agentSummary = AgentSummary.build(report: report, filtered: filtered, now: now)
        
        return PanelData(
            rangeSpec: spec,
            filteredReport: filtered,
            subscriptionRows: subscriptionRows,
            agentSummary: agentSummary,
            now: now
        )
    }
}
