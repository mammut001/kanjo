import Foundation

/// 契约第 2 节的不变量：totals == sum(projects) + unattributed + excluded。
public struct Reconciliation: Equatable {
    public struct Line: Equatable {
        public var reported: Double
        public var summed: Double
        public var tolerance: Double
        public var diff: Double { reported - summed }
        public var ok: Bool { abs(diff) <= tolerance }
    }

    public var cost: Line
    public var tokens: Line
    public var sessions: Line
    public var projectsCost: Double
    public var unattributedCost: Double
    public var excludedCost: Double

    public var ok: Bool { cost.ok && tokens.ok && sessions.ok }

    /// 金额误差容忍 0.01（契约）；token / 会话是整数，必须相等。
    public static let costTolerance = 0.01

    public init(report r: UsageReport) {
        let pCost = r.projects.reduce(0) { $0 + $1.cost }
        let pTok = r.projects.reduce(0) { $0 + $1.tokens.total }
        let pSess = r.projects.reduce(0) { $0 + $1.sessions }
        let u = r.buckets.unattributed, e = r.buckets.excluded
        projectsCost = pCost
        unattributedCost = u.cost
        excludedCost = e.cost
        cost = Line(reported: r.totals.cost, summed: pCost + u.cost + e.cost, tolerance: Self.costTolerance)
        tokens = Line(reported: Double(r.totals.tokens.total),
                      summed: Double(pTok + u.tokens.total + e.tokens.total), tolerance: 0)
        sessions = Line(reported: Double(r.totals.sessions),
                        summed: Double(pSess + u.sessions + e.sessions), tolerance: 0)
    }
}
