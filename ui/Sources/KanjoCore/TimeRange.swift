import Foundation

// 时间范围（CONTRACT.md 6.1）：纯函数，不依赖 SwiftUI。
// 项目的 cost / tokens 由 by_day 的 by_agent / by_agent_tokens 逐天逐 agent 累加；
// sessions 按在范围内有用量计（优先按日数据，否则按 [started, ended] 区间重叠）。

public enum TimeRange: String, CaseIterable, Identifiable {
    case all, today, days7, days30, lastWeek, sinceReset, billingCycle

    public var id: String { rawValue }

    /// 分段控件上的短名。
    public var shortLabel: String {
        switch self {
        case .all: return L10n.tr("timerange.all.short")
        case .today: return L10n.tr("timerange.today.short")
        case .days7: return L10n.tr("timerange.days7.short")
        case .days30: return L10n.tr("timerange.days30.short")
        case .lastWeek: return L10n.tr("timerange.lastWeek.short")
        case .sinceReset: return L10n.tr("timerange.sinceReset.short")
        case .billingCycle: return L10n.tr("timerange.billingCycle.short")
        }
    }

    /// 菜单栏范围后缀：固定时间窗口（Today / 7d / 30d）显示本地化后缀，其他范围（All、Last week、Since reset、Billing cycle）无后缀。
    public var menuBarSuffix: String? {
        switch self {
        case .today:
            return L10n.tr("timerange.today.suffix")
        case .days7, .days30:
            return shortLabel
        case .all, .lastWeek, .sinceReset, .billingCycle:
            return nil
        }
    }

    /// 兼容旧调用。
    public var menuBarPrefix: String? {
        menuBarSuffix
    }

    public var longLabel: String {
        switch self {
        case .all: return L10n.tr("timerange.all.long")
        case .today: return L10n.tr("timerange.today.long")
        case .days7: return L10n.tr("timerange.days7.long")
        case .days30: return L10n.tr("timerange.days30.long")
        case .lastWeek: return L10n.tr("timerange.lastWeek.long")
        case .sinceReset: return L10n.tr("timerange.sinceReset.long")
        case .billingCycle: return L10n.tr("timerange.billingCycle.long")
        }
    }
}

/// 一个范围的具体区间。区间一律半开 [start, end)；nil 端表示无界。
/// `sinceReset` / `billingCycle` 下每个 agent 有自己的起点（`agentStarts`），不在字典里的 agent 不计入。
public struct RangeSpec: Equatable {
    public var range: TimeRange
    public var calendar: Calendar
    public var start: Date?
    public var end: Date?
    public var agentStarts: [String: Date]

    public init(range: TimeRange, calendar: Calendar, start: Date? = nil, end: Date? = nil,
                agentStarts: [String: Date] = [:]) {
        self.range = range
        self.calendar = calendar
        self.start = start
        self.end = end
        self.agentStarts = agentStarts
    }

    public var isAll: Bool { range == .all }

    /// 某 agent 的有效区间；nil = 该 agent 在此范围下不计入（sinceReset / billingCycle 下没有窗口的 agent）。
    public func window(for agent: String) -> (start: Date?, end: Date?)? {
        switch range {
        case .all: return (nil, nil)
        case .sinceReset, .billingCycle: return agentStarts[agent].map { ($0, end) }
        default: return (start, end)
        }
    }

    /// 某天 [dayStart, dayEnd) 与该 agent 的区间相交即算。
    public func includes(dayStart: Date, dayEnd: Date, agent: String) -> Bool {
        guard let w = window(for: agent) else { return false }
        if let s = w.start, dayEnd <= s { return false }
        if let e = w.end, dayStart >= e { return false }
        return true
    }

    /// 时刻落在该 agent 的区间内。
    public func includes(_ instant: Date, agent: String) -> Bool {
        guard let w = window(for: agent) else { return false }
        if let s = w.start, instant < s { return false }
        if let e = w.end, instant >= e { return false }
        return true
    }

    /// 会话是否计入此范围：在范围内有用量。
    /// 优先使用会话的按日数据（若有）；否则按 [started, ended] 与范围区间有重叠计入。
    public func includes(_ session: Session) -> Bool {
        guard let w = window(for: session.agent) else { return false }
        if let byDay = session.byDay, !byDay.isEmpty {
            for d in byDay {
                guard let d0 = HeatStrip.parseDay(d.day, calendar: calendar),
                      let d1 = calendar.date(byAdding: .day, value: 1, to: d0) else { continue }
                if includes(dayStart: d0, dayEnd: d1, agent: session.agent) {
                    if d.cost > 0 || d.tokens > 0 { return true }
                }
            }
            for d in byDay {
                guard let d0 = HeatStrip.parseDay(d.day, calendar: calendar),
                      let d1 = calendar.date(byAdding: .day, value: 1, to: d0) else { continue }
                if includes(dayStart: d0, dayEnd: d1, agent: session.agent) {
                    return true
                }
            }
            return false
        }
        guard let s = session.startedDate ?? session.endedDate,
              let e = session.endedDate ?? session.startedDate else {
            return false
        }
        let sessionStart = min(s, e)
        let sessionEnd = max(s, e)
        if let start = w.start, sessionEnd < start { return false }
        if let end = w.end, sessionStart >= end { return false }
        return true
    }

    /// 计算会话在当前范围内的花费与 token 份额。
    /// 1. 优先使用会话的按日数据（若有）；
    /// 2. 否则按会话时间区间 [started, ended] 与范围窗口的重叠比例（timeShare）缩放。
    public func inRangeCostAndTokens(for session: Session) -> (cost: Double, tokens: Int) {
        if isAll {
            return (session.cost, session.tokens.total)
        }
        guard includes(session) else {
            return (0.0, 0)
        }
        if let byDay = session.byDay, !byDay.isEmpty {
            var c: Double = 0
            var t: Int = 0
            for d in byDay {
                guard let d0 = HeatStrip.parseDay(d.day, calendar: calendar),
                      let d1 = calendar.date(byAdding: .day, value: 1, to: d0) else { continue }
                if includes(dayStart: d0, dayEnd: d1, agent: session.agent) {
                    c += d.cost
                    t += d.tokens
                }
            }
            return (c, t)
        }
        guard let s = session.startedDate ?? session.endedDate,
              let e = session.endedDate ?? session.startedDate else {
            return (session.cost, session.tokens.total)
        }
        let s0 = min(s, e)
        let s1 = max(s, e)
        let dur = s1.timeIntervalSince(s0)
        guard dur > 0 else {
            return (session.cost, session.tokens.total)
        }
        guard let w = window(for: session.agent) else {
            return (0.0, 0)
        }
        let r0 = w.start ?? s0
        let r1 = w.end ?? s1
        let overlap0 = max(s0, r0)
        let overlap1 = min(s1, r1)
        if overlap1 <= overlap0 {
            return (0.0, 0)
        }
        let share = min(1.0, max(0.0, overlap1.timeIntervalSince(overlap0) / dur))
        return (session.cost * share, Int(round(Double(session.tokens.total) * share)))
    }
}

/// 一个项目在范围内的数字。`projected` 是把这些数字填回去的 Project（tokens 只有 total；by_model / by_branch 不过滤），
/// 方便直接交给只认 Project 的视图。
public struct FilteredProject: Identifiable, Equatable {
    public var project: Project
    public var cost: Double
    public var tokens: Int
    public var sessions: Int
    public var byAgent: [AgentCost]          // 范围下 tokens 只填 total
    public var byDay: [DayCost]
    public var sessionsDetail: [Session]
    public var firstActive: String?
    public var lastActive: String?

    public var id: String { project.id }
    public var hasUsage: Bool { cost > 0 || tokens > 0 || sessions > 0 }

    public var projected: Project {
        var p = project
        p.cost = cost
        if tokens != project.tokens.total { p.tokens = Tokens(total: tokens) }
        p.sessions = sessions
        p.byAgent = byAgent
        p.byDay = byDay
        p.sessionsDetail = sessionsDetail
        p.firstActive = firstActive
        p.lastActive = lastActive
        return p
    }
}

/// unattributed / excluded 在范围内：只能按 sessions_detail 计（桶没有 by_day）。
public struct FilteredBucket: Equatable {
    public var cost: Double
    public var tokens: Int
    public var sessions: Int
    public var sessionsDetail: [Session]
    public var firstActive: String?
    public var lastActive: String?
}

public struct FilteredReport: Equatable {
    public var spec: RangeSpec
    public var projects: [FilteredProject]   // 按范围内 cost 降序
    public var unattributed: FilteredBucket
    public var excluded: FilteredBucket
    public var cost: Double
    public var tokens: Int
    public var sessions: Int
    public var firstActive: String?
    public var lastActive: String?

    public func project(_ id: String) -> FilteredProject? { projects.first { $0.id == id } }
}

public enum RangeEngine {
    /// 报告时区的公历日历（周一为一周开始）。时区名无效时用本机时区。
    public static func calendar(timezone: TimeZone) -> Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = timezone
        c.firstWeekday = 2
        c.locale = Locale(identifier: "en_US_POSIX")
        return c
    }

    public static func timezone(of report: UsageReport) -> TimeZone {
        report.timezone.flatMap(TimeZone.init(identifier:)) ?? .current
    }

    /// 范围 → 区间。
    /// - all：无界；today：[今天零点, now)；days7 / days30：[今天往前 6 / 29 天的零点, now)；
    /// - lastWeek：上一个周一零点到本周一零点；
    /// - sinceReset：每个 agent 的起点 = 当前周窗口的开始（见 `windowStart`），没有 quota 的 agent 不计入。
    /// - billingCycle：每个 agent 的起点 = `subscriptions[agent].cycle_start`，没有订阅（或起点解析不了）的 agent 不计入。
    public static func dateInterval(for range: TimeRange, now: Date, timezone: TimeZone,
                                    quota: [String: QuotaWindow]?,
                                    subscriptions: [String: Subscription]? = nil) -> RangeSpec {
        let cal = calendar(timezone: timezone)
        let today = cal.startOfDay(for: now)
        func daysBack(_ n: Int) -> Date { cal.date(byAdding: .day, value: -n, to: today) ?? today }
        switch range {
        case .all:
            return RangeSpec(range: .all, calendar: cal)
        case .today:
            return RangeSpec(range: .today, calendar: cal, start: daysBack(0), end: now)
        case .days7:
            return RangeSpec(range: .days7, calendar: cal, start: daysBack(6), end: now)
        case .days30:
            return RangeSpec(range: .days30, calendar: cal, start: daysBack(29), end: now)
        case .lastWeek:
            let thisMonday = mondayOnOrBefore(today, calendar: cal)
            let lastMonday = cal.date(byAdding: .day, value: -7, to: thisMonday) ?? thisMonday
            return RangeSpec(range: .lastWeek, calendar: cal, start: lastMonday, end: thisMonday)
        case .sinceReset:
            var starts: [String: Date] = [:]
            for (agent, q) in quota ?? [:] {
                if let s = windowStart(q, now: now) { starts[agent] = s }
            }
            return RangeSpec(range: .sinceReset, calendar: cal, end: now, agentStarts: starts)
        case .billingCycle:
            var starts: [String: Date] = [:]
            for (agent, sub) in subscriptions ?? [:] {
                if let s = ReportDates.parseTimestamp(sub.cycleStart) { starts[agent] = s }
            }
            return RangeSpec(range: .billingCycle, calendar: cal, end: now, agentStarts: starts)
        }
    }

    /// 报告上的便捷入口：时区、quota、订阅都取自报告。
    public static func spec(_ range: TimeRange, report: UsageReport, now: Date = Date()) -> RangeSpec {
        dateInterval(for: range, now: now, timezone: timezone(of: report),
                     quota: report.quotaWindows, subscriptions: report.subscriptions)
    }

    /// `day` 所在周的周一零点（day 应已是零点）。
    public static func mondayOnOrBefore(_ day: Date, calendar cal: Calendar) -> Date {
        // weekday：周日 = 1 … 周六 = 7；换算成「距本周一的天数」。
        let offset = (cal.component(.weekday, from: day) + 5) % 7
        return cal.date(byAdding: .day, value: -offset, to: cal.startOfDay(for: day)) ?? day
    }

    /// 当前周窗口的起点：weekly_resets_at - window。起点在未来就再往前推整窗口；
    /// weekly_resets_at 已经过去（缓存过期）就往后推到最近一个 ≤ now 的起点。结果满足 start ≤ now < start + window。
    public static func windowStart(_ q: QuotaWindow, now: Date) -> Date? {
        guard q.weeklyWindowHours > 0, let reset = ReportDates.parseTimestamp(q.weeklyResetsAt) else { return nil }
        let w = TimeInterval(q.weeklyWindowHours) * 3600
        let k = (now.timeIntervalSince(reset) / w).rounded(.down)
        return reset.addingTimeInterval(k * w)
    }

    // MARK: - 过滤

    public static func filtered(_ report: UsageReport, range spec: RangeSpec,
                                fallbackAgentFor: (Project) -> String) -> FilteredReport {
        let ps = report.projects.map { filter($0, range: spec, fallbackAgent: fallbackAgentFor($0)) }
        let u = filter(report.buckets.unattributed, range: spec)
        let e = filter(report.buckets.excluded, range: spec)
        if spec.isAll {
            let t = report.totals
            return FilteredReport(spec: spec, projects: ps, unattributed: u, excluded: e,
                                  cost: t.cost, tokens: t.tokens.total, sessions: t.sessions,
                                  firstActive: t.firstActive, lastActive: t.lastActive)
        }
        let sorted = ps.enumerated().sorted { a, b in
            a.element.cost != b.element.cost ? a.element.cost > b.element.cost : a.offset < b.offset
        }.map(\.element)
        let days = sorted.flatMap { [$0.firstActive, $0.lastActive] }
            + [u.firstActive, u.lastActive, e.firstActive, e.lastActive]
        let known = days.compactMap { $0 }
        return FilteredReport(
            spec: spec, projects: sorted, unattributed: u, excluded: e,
            cost: sorted.reduce(0) { $0 + $1.cost } + u.cost + e.cost,
            tokens: sorted.reduce(0) { $0 + $1.tokens } + u.tokens + e.tokens,
            sessions: sorted.reduce(0) { $0 + $1.sessions } + u.sessions + e.sessions,
            firstActive: known.min(), lastActive: known.max())
    }

    /// 单个项目。某天缺 by_agent（或为空）时那天的 cost 全记到 `fallbackAgent`；缺 by_agent_tokens 时 tokens 同理。
    public static func filter(_ p: Project, range spec: RangeSpec, fallbackAgent: String) -> FilteredProject {
        if spec.isAll {
            return FilteredProject(project: p, cost: p.cost, tokens: p.tokens.total, sessions: p.sessions,
                                   byAgent: p.byAgent, byDay: p.byDay, sessionsDetail: p.sessionsDetail,
                                   firstActive: p.firstActive, lastActive: p.lastActive)
        }
        let cal = spec.calendar
        var agentCost: [String: Double] = [:], agentTokens: [String: Int] = [:], agentSessions: [String: Int] = [:]
        var days: [DayCost] = []
        for d in p.byDay {
            guard let d0 = HeatStrip.parseDay(d.day, calendar: cal),
                  let d1 = cal.date(byAdding: .day, value: 1, to: d0) else { continue }
            let costSplit = (d.byAgent?.isEmpty == false) ? d.byAgent! : [fallbackAgent: d.cost]
            let tokenSplit = (d.byAgentTokens?.isEmpty == false) ? d.byAgentTokens! : [fallbackAgent: d.tokens]
            var dc: [String: Double] = [:], dt: [String: Int] = [:]
            for agent in Set(costSplit.keys).union(tokenSplit.keys)
            where spec.includes(dayStart: d0, dayEnd: d1, agent: agent) {
                if let c = costSplit[agent] { dc[agent] = c }
                if let t = tokenSplit[agent] { dt[agent] = t }
            }
            guard !dc.isEmpty || !dt.isEmpty else { continue }
            for (a, c) in dc { agentCost[a, default: 0] += c }
            for (a, t) in dt { agentTokens[a, default: 0] += t }
            days.append(DayCost(day: d.day, cost: dc.values.reduce(0, +), tokens: dt.values.reduce(0, +),
                                byAgent: dc, byAgentTokens: dt))
        }
        let sessions = p.sessionsDetail.filter { s in
            spec.includes(s)
        }
        for s in sessions { agentSessions[s.agent, default: 0] += 1 }

        var labels: [String: String] = [:]
        for s in p.sessionsDetail { labels[s.agent] = s.label }
        for a in p.byAgent { labels[a.agent] = a.label }
        let keys = Set(agentCost.keys).union(agentTokens.keys).union(agentSessions.keys)
        var byAgent: [AgentCost] = []
        for k in keys {
            let a = AgentCost(agent: k, label: labels[k] ?? k, cost: agentCost[k] ?? 0,
                              tokens: Tokens(total: agentTokens[k] ?? 0), sessions: agentSessions[k] ?? 0)
            if a.cost > 0 || a.tokens.total > 0 || a.sessions > 0 { byAgent.append(a) }
        }
        byAgent.sort { $0.cost != $1.cost ? $0.cost > $1.cost : $0.agent < $1.agent }

        return FilteredProject(project: p, cost: days.reduce(0) { $0 + $1.cost },
                               tokens: days.reduce(0) { $0 + $1.tokens }, sessions: sessions.count,
                               byAgent: byAgent, byDay: days, sessionsDetail: sessions,
                               firstActive: days.first?.day, lastActive: days.last?.day)
    }

    public static func filter(_ b: SessionBucket, range spec: RangeSpec) -> FilteredBucket {
        if spec.isAll {
            return FilteredBucket(cost: b.cost, tokens: b.tokens.total, sessions: b.sessions,
                                  sessionsDetail: b.sessionsDetail, firstActive: b.firstActive, lastActive: b.lastActive)
        }
        let ss = b.sessionsDetail.filter { s in
            spec.includes(s)
        }
        let cal = spec.calendar
        let days: [String] = ss.flatMap { s -> [String] in
            [s.startedDate, s.endedDate].compactMap { $0.map { dayString($0, calendar: cal) } }
        }
        var totalCost: Double = 0
        var totalTokens: Int = 0
        for s in ss {
            let (c, t) = spec.inRangeCostAndTokens(for: s)
            totalCost += c
            totalTokens += t
        }
        return FilteredBucket(cost: totalCost, tokens: totalTokens, sessions: ss.count, sessionsDetail: ss,
                              firstActive: days.min(), lastActive: days.max())
    }

    /// 时刻 → 该日历时区下的 "YYYY-MM-DD"。
    public static func dayString(_ d: Date, calendar cal: Calendar) -> String {
        let c = cal.dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }
}
