import Foundation

public struct PanelData: Equatable {
    public let rangeSpec: RangeSpec
    public let filteredReport: FilteredReport
    public let subscriptionRows: [SubscriptionRow]
    public let reportGeneratedAt: String
    public let subscriptionsFingerprint: String
    public let now: Date
    public var models: [ModelCost] = []
    public var agentSummary: AgentSummaryReport? = nil
    public var weeklyTokens: Int = 0
    public var heatWeeks: [String: [WeekCost]] = [:]

    public static func compute(report: UsageReport, rangeRaw: String, now: Date, isSnapshot: Bool = false) -> PanelData? {
        let resolved = RangeEngine.resolve(raw: rangeRaw, report: report, now: now)
        let spec = resolved.spec
        
        let filtered = RangeEngine.filtered(report, range: spec, fallbackAgentFor: { p in
            dominantAgent(p.byAgent)?.agent ?? p.byAgent.first?.agent ?? "unknown"
        })
        let cycleUsage = SubscriptionValue.cycleUsage(of: report, now: now)
        let subscriptionRows = SubscriptionValue.rows(of: report, now: now, cycleUsage: cycleUsage)
        
        let models = ModelAggregation.aggregate(in: filtered)
        let reference = WeeklyTokens.reference(now: now, generatedAt: ReportDates.parseTimestamp(report.generatedAt))
        let weeklyTokens = WeeklyTokens.since(mondayOfWeekContaining: reference, projects: report.projects, calendar: .current)
        let end = ReportDates.parseTimestamp(report.generatedAt) ?? report.totals.lastActive.flatMap(ReportDates.parseDay) ?? now
        var heatWeeks: [String: [WeekCost]] = [:]
        for project in filtered.projects {
            let p = project.projected
            heatWeeks[p.id] = HeatStrip.weekly(p.byDay, endingOn: end, fallbackAgent: RangeEngine.fallbackAgent(for: p))
        }
        return PanelData(
            rangeSpec: spec,
            filteredReport: filtered,
            subscriptionRows: subscriptionRows,
            reportGeneratedAt: report.generatedAt,
            subscriptionsFingerprint: Self.subscriptionsFingerprint(report),
            now: now,
            models: models,
            agentSummary: AgentSummary.build(report: report, filtered: filtered, now: now, quotaNow: AgentSummary.quotaReference(report: report, now: now, isSnapshot: isSnapshot), cycleUsage: cycleUsage, models: models),
            weeklyTokens: weeklyTokens,
            heatWeeks: heatWeeks
        )
    }

    public func matches(report: UsageReport, spec: RangeSpec) -> Bool {
        return self.reportGeneratedAt == report.generatedAt &&
               self.rangeSpec.range == spec.range &&
               self.rangeSpec.start == spec.start &&
               self.rangeSpec.agentStarts == spec.agentStarts &&
               self.rangeSpec.calendar.timeZone == spec.calendar.timeZone
    }

    public static func subscriptionsFingerprint(_ report: UsageReport) -> String {
        guard let subs = report.subscriptions, !subs.isEmpty else { return "" }
        return subs.keys.sorted().map { agent in
            let s = subs[agent]!
            let price = s.monthlyPriceUsd.map { String($0) } ?? "nil"
            let anchor = s.anchorDay.map(String.init) ?? "nil"
            return "\(agent):\(s.plan):\(s.cycleStart):\(s.cycleEnd):\(anchor):\(price)"
        }.joined(separator: "|")
    }

    /// Overview subscription rows: reuse panel cache only when subscriptions and time are still current.
    public func canReuseSubscriptionRows(for report: UsageReport, now: Date, maxAge: TimeInterval = 60) -> Bool {
        reportGeneratedAt == report.generatedAt &&
        subscriptionsFingerprint == Self.subscriptionsFingerprint(report) &&
        now.timeIntervalSince(self.now) >= 0 &&
        now.timeIntervalSince(self.now) < maxAge
    }
}
