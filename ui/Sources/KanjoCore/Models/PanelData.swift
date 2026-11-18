import Foundation

public struct PanelData: Equatable {
    public let rangeSpec: RangeSpec
    public let filteredReport: FilteredReport
    public let subscriptionRows: [SubscriptionRow]
    public let reportGeneratedAt: String
    public let now: Date

    public static func compute(report: UsageReport, rangeRaw: String, now: Date) -> PanelData? {
        let resolved = RangeEngine.resolve(raw: rangeRaw, report: report, now: now)
        let spec = resolved.spec
        
        let filtered = RangeEngine.filtered(report, range: spec, fallbackAgentFor: { p in
            dominantAgent(p.byAgent)?.agent ?? p.byAgent.first?.agent ?? "unknown"
        })
        let subscriptionRows = SubscriptionValue.rows(of: report, now: now)
        
        return PanelData(
            rangeSpec: spec,
            filteredReport: filtered,
            subscriptionRows: subscriptionRows,
            reportGeneratedAt: report.generatedAt,
            now: now
        )
    }

    public func matches(report: UsageReport, spec: RangeSpec) -> Bool {
        return self.reportGeneratedAt == report.generatedAt &&
               self.rangeSpec.range == spec.range &&
               self.rangeSpec.start == spec.start &&
               self.rangeSpec.agentStarts == spec.agentStarts &&
               self.rangeSpec.calendar.timeZone == spec.calendar.timeZone
    }
}
