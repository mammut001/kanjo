import Foundation

// 时间范围（CONTRACT.md 6.1）：纯函数，不依赖 SwiftUI。
// 项目的 cost / tokens 由 by_day 的 by_agent / by_agent_tokens 逐天逐 agent 累加；
// sessions 按 sessions_detail[].started 落在范围内计数。

public enum TimeRange: String, CaseIterable, Identifiable {
    case all, days7, days30, lastWeek, sinceReset, billingCycle

    public var id: String { rawValue }

    /// 分段控件上的短名。
    public var shortLabel: String {
        switch self {
        case .all: return L10n.tr("timerange.all.short")
        case .days7: return L10n.tr("timerange.days7.short")
        case .days30: return L10n.tr("timerange.days30.short")
        case .lastWeek: return L10n.tr("timerange.lastWeek.short")
        case .sinceReset: return L10n.tr("timerange.sinceReset.short")
        case .billingCycle: return L10n.tr("timerange.billingCycle.short")
        }
    }

    /// 菜单栏范围后缀：仅固定时间窗口（7d / 30d）显示本地化短标签，其他范围（All、Last week、Since reset、Billing cycle）无后缀。
    public var menuBarSuffix: String? {
        switch self {
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
    /// - all：无界；days7 / days30：[今天往前 6 / 29 天的零点, now)；
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
            s.startedDate.map { spec.includes($0, agent: s.agent) } ?? false
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
            s.startedDate.map { spec.includes($0, agent: s.agent) } ?? false
        }
        let cal = spec.calendar
        let days: [String] = ss.compactMap { s -> String? in s.startedDate.map { dayString($0, calendar: cal) } }
        let cost: Double = ss.reduce(0.0) { $0 + $1.cost }
        let tokens: Int = ss.reduce(0) { $0 + $1.tokens.total }
        return FilteredBucket(cost: cost, tokens: tokens, sessions: ss.count, sessionsDetail: ss,
                              firstActive: days.min(), lastActive: days.max())
    }

    /// 时刻 → 该日历时区下的 "YYYY-MM-DD"。
    public static func dayString(_ d: Date, calendar cal: Calendar) -> String {
        let c = cal.dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }
}
