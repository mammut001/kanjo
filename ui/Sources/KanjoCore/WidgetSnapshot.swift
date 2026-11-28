import Foundation

/// 单日总花费（供小组件缓存与热力条使用，不含任何项目名或会话信息）。
public struct WidgetDayCost: Codable, Equatable, Sendable, Identifiable {
    public var day: String
    public var cost: Double
    public var byAgent: [String: Double]?

    public var id: String { day }

    enum CodingKeys: String, CodingKey {
        case day
        case cost
        case byAgent = "by_agent"
    }

    public init(day: String, cost: Double, byAgent: [String: Double]? = nil) {
        self.day = day
        self.cost = cost
        self.byAgent = byAgent
    }
}

/// 按报告时区汇总所有项目 `projects[].by_day` 得到的今日、昨日与最近 N 天花费。
public struct DailyCostSummary: Equatable, Sendable {
    public var todayCost: Double
    public var yesterdayCost: Double
    public var days: [WidgetDayCost]

    public init(todayCost: Double, yesterdayCost: Double, days: [WidgetDayCost]) {
        self.todayCost = todayCost
        self.yesterdayCost = yesterdayCost
        self.days = days
    }
}

/// 小组件单条额度进度数据（5 小时或每周窗口）。
public struct WidgetQuotaBar: Equatable, Sendable, Identifiable {
    public var id: String          // "five_hour" | "weekly"
    public var windowHours: Int
    public var usedPercent: Double?
    public var resetsAt: Date?
    public var isReset: Bool

    public init(id: String, windowHours: Int, usedPercent: Double?, resetsAt: Date?, isReset: Bool) {
        self.id = id
        self.windowHours = windowHours
        self.usedPercent = usedPercent
        self.resetsAt = resetsAt
        self.isReset = isReset
    }
}

/// App Group 瘦身快照模型（`widget-snapshot.json`），仅包含小组件所需的聚合字段，不含项目名。
public struct WidgetSnapshot: Codable, Equatable, Sendable {
    public static let defaultDayCount = 15
    public static let staleThreshold: TimeInterval = 2 * 3600

    public var generatedAt: String
    public var deviceName: String?
    public var timezone: String?
    public var currency: String
    public var days: [WidgetDayCost]
    public var quotaWindows: [String: QuotaWindow]?

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case deviceName = "device_name"
        case timezone
        case currency
        case days
        case quotaWindows = "quota_windows"
    }

    public init(
        generatedAt: String,
        deviceName: String? = nil,
        timezone: String? = nil,
        currency: String = "USD",
        days: [WidgetDayCost],
        quotaWindows: [String: QuotaWindow]? = nil
    ) {
        self.generatedAt = generatedAt
        self.deviceName = deviceName
        self.timezone = timezone
        self.currency = currency
        self.days = days
        self.quotaWindows = quotaWindows
    }

    /// 从完整或移动端 `UsageReport` 生成小组件瘦身快照。
    public init(
        report: UsageReport,
        deviceName: String? = nil,
        now: Date? = nil,
        dayCount: Int = WidgetSnapshot.defaultDayCount
    ) {
        let referenceNow = now ?? ReportDates.parseTimestamp(report.generatedAt) ?? Date()
        let summary = Self.dailyCosts(from: report, now: referenceNow, dayCount: dayCount)
        self.generatedAt = report.generatedAt
        self.deviceName = deviceName
        self.timezone = report.timezone
        self.currency = report.currency
        self.days = summary.days
        self.quotaWindows = report.quotaWindows
    }

    // MARK: - 时区与日期

    public var resolvedTimezone: TimeZone {
        Self.resolveTimezone(timezone)
    }

    public static func resolveTimezone(_ identifier: String?) -> TimeZone {
        identifier.flatMap(TimeZone.init(identifier:)) ?? .current
    }

    public var generatedDate: Date? {
        ReportDates.parseTimestamp(generatedAt)
    }

    // MARK: - 按日花费汇总

    /// 按报告时区（若为 nil 则回退到当前时区）汇总 `projects[].by_day`，计算相对于 `now` 的今天、昨天和最近 N 天花费（缺省日补 0，最早的在前，最后一项为今天）。
    public static func dailyCosts(
        from report: UsageReport,
        now: Date = Date(),
        dayCount: Int = defaultDayCount
    ) -> DailyCostSummary {
        dailyCosts(
            projects: report.projects,
            timezone: resolveTimezone(report.timezone),
            now: now,
            dayCount: dayCount
        )
    }

    public static func dailyCosts(
        projects: [Project],
        timezoneIdentifier: String?,
        now: Date = Date(),
        dayCount: Int = defaultDayCount
    ) -> DailyCostSummary {
        dailyCosts(
            projects: projects,
            timezone: resolveTimezone(timezoneIdentifier),
            now: now,
            dayCount: dayCount
        )
    }

    public static func dailyCosts(
        projects: [Project],
        timezone: TimeZone? = nil,
        now: Date = Date(),
        dayCount: Int = defaultDayCount
    ) -> DailyCostSummary {
        let tz = timezone ?? .current
        let cal = RangeEngine.calendar(timezone: tz)
        let todayStart = cal.startOfDay(for: now)
        let todayKey = RangeEngine.dayString(todayStart, calendar: cal)
        let yesterdayStart = cal.date(byAdding: .day, value: -1, to: todayStart) ?? todayStart
        let yesterdayKey = RangeEngine.dayString(yesterdayStart, calendar: cal)

        var costByDay: [String: Double] = [:]
        var agentCostByDay: [String: [String: Double]] = [:]

        for project in projects {
            let fallback = dominantAgent(project.byAgent)?.agent ?? project.byAgent.first?.agent
            for entry in project.byDay {
                guard entry.cost.isFinite else { continue }
                costByDay[entry.day, default: 0] += entry.cost
                if let split = entry.byAgent, !split.isEmpty {
                    for (agent, c) in split where c.isFinite && c > 0 {
                        agentCostByDay[entry.day, default: [:]][agent, default: 0] += c
                    }
                } else if let fallback, entry.cost > 0 {
                    agentCostByDay[entry.day, default: [:]][fallback, default: 0] += entry.cost
                }
            }
        }

        let count = max(0, dayCount)
        let recentDays: [WidgetDayCost] = (0..<count).compactMap { index in
            let offset = -(count - 1 - index)
            guard let date = cal.date(byAdding: .day, value: offset, to: todayStart) else { return nil }
            let key = RangeEngine.dayString(date, calendar: cal)
            let cost = costByDay[key] ?? 0
            let byAgent = agentCostByDay[key]
            return WidgetDayCost(
                day: key,
                cost: cost,
                byAgent: (byAgent?.isEmpty == false) ? byAgent : nil
            )
        }

        return DailyCostSummary(
            todayCost: costByDay[todayKey] ?? 0,
            yesterdayCost: costByDay[yesterdayKey] ?? 0,
            days: recentDays
        )
    }

    // MARK: - 过期与跨天判断

    /// 快照距 `now` 是否已超过阈值（默认 2 小时）。无法解析时间戳时视为过期。
    public static func isStale(
        generatedAt: String,
        now: Date = Date(),
        threshold: TimeInterval = staleThreshold
    ) -> Bool {
        guard let generated = ReportDates.parseTimestamp(generatedAt) else { return true }
        return now.timeIntervalSince(generated) > threshold
    }

    public func isStale(now: Date = Date(), threshold: TimeInterval = staleThreshold) -> Bool {
        Self.isStale(generatedAt: generatedAt, now: now, threshold: threshold)
    }

    /// 快照的 `generatedAt` 与 `now` 在目标时区下是否处于同一个自然日。
    /// 若已跨天但尚未有新快照，今天花费未知（必须显示 "—"，不能拿昨天的数字当今天）。
    public static func isTodayKnown(
        generatedAt: String,
        timezone: TimeZone,
        now: Date = Date()
    ) -> Bool {
        guard let generated = ReportDates.parseTimestamp(generatedAt) else { return false }
        let cal = RangeEngine.calendar(timezone: timezone)
        return RangeEngine.dayString(generated, calendar: cal) == RangeEngine.dayString(now, calendar: cal)
    }

    public func isTodayKnown(now: Date = Date(), timezone: TimeZone? = nil) -> Bool {
        Self.isTodayKnown(generatedAt: generatedAt, timezone: timezone ?? resolvedTimezone, now: now)
    }

    /// 今天的花费；若跨天尚未同步（`!isTodayKnown`），返回 `nil`（界面显示 "—"）。
    public func todayCost(now: Date = Date()) -> Double? {
        guard isTodayKnown(now: now) else { return nil }
        let cal = RangeEngine.calendar(timezone: resolvedTimezone)
        let todayKey = RangeEngine.dayString(cal.startOfDay(for: now), calendar: cal)
        return days.first(where: { $0.day == todayKey })?.cost ?? 0
    }

    /// 昨天的花费（相对于 `now` 所在报告时区自然日的前一天）。
    public func yesterdayCost(now: Date = Date()) -> Double {
        let cal = RangeEngine.calendar(timezone: resolvedTimezone)
        let todayStart = cal.startOfDay(for: now)
        guard let yesterdayStart = cal.date(byAdding: .day, value: -1, to: todayStart) else { return 0 }
        let yesterdayKey = RangeEngine.dayString(yesterdayStart, calendar: cal)
        return days.first(where: { $0.day == yesterdayKey })?.cost ?? 0
    }

    /// 今天各 agent 的花费，按金额从高到低；金额相同按名字字母序。
    /// 今天未知，或这一天没有 `by_agent` 拆分（或拆分里没有正花费）时返回 nil。
    /// 调用方在 nil 时改显示近 7 天合计与日均，不要拿项目名来填。
    public func todayAgentCosts(now: Date = Date()) -> [(agent: String, cost: Double)]? {
        guard isTodayKnown(now: now) else { return nil }
        let cal = RangeEngine.calendar(timezone: resolvedTimezone)
        let todayKey = RangeEngine.dayString(cal.startOfDay(for: now), calendar: cal)
        guard let split = days.first(where: { $0.day == todayKey })?.byAgent, !split.isEmpty else {
            return nil
        }
        let ranked = split
            .filter { $0.value.isFinite && $0.value > 0 }
            .map { (agent: $0.key, cost: $0.value) }
            .sorted { lhs, rhs in
                if lhs.cost != rhs.cost { return lhs.cost > rhs.cost }
                return lhs.agent < rhs.agent
            }
        return ranked.isEmpty ? nil : ranked
    }

    /// 返回用于热力条展示的最近 `count` 天（最早的在前，最后一项为 `now` 所在日；缺失日期补 0）。
    public func recentDays(count: Int, now: Date? = nil) -> [WidgetDayCost] {
        guard count > 0 else { return [] }
        let reference = now ?? generatedDate ?? Date()
        let cal = RangeEngine.calendar(timezone: resolvedTimezone)
        let todayStart = cal.startOfDay(for: reference)
        var byKey: [String: WidgetDayCost] = [:]
        for entry in days {
            byKey[entry.day] = entry
        }
        return (0..<count).compactMap { index in
            let offset = -(count - 1 - index)
            guard let date = cal.date(byAdding: .day, value: offset, to: todayStart) else { return nil }
            let key = RangeEngine.dayString(date, calendar: cal)
            return byKey[key] ?? WidgetDayCost(day: key, cost: 0)
        }
    }

    // MARK: - 额度 Agent 选择

    /// 有额度数据的 agent 的固定展示顺序。快照里没有每个 agent 的拉取时间，
    /// 窗口起点（重置时刻减窗口长度）不是新鲜度，不能用来挑默认 agent。
    /// 未出现在这张表里的 agent 排在后面，按名字字母序。
    public static let quotaAgentPriority: [String] = ["claude", "codex", "antigravity"]

    /// 该 `QuotaWindow` 是否带有额度百分比数据（仅设置了手动重置时间但无任何百分比的不算有额度数据）。
    public static func hasQuotaData(_ window: QuotaWindow?) -> Bool {
        guard let window else { return false }
        if let p = window.fiveHourUsedPercent, p.isFinite { return true }
        if let p = window.weeklyUsedPercent, p.isFinite { return true }
        if let extra = window.extraWindows, extra.contains(where: { $0.usedPercent?.isFinite == true }) {
            return true
        }
        return false
    }

    /// 从 `quotaWindows` 中筛出有额度数据的 agent。
    /// 顺序是 `quotaAgentPriority`，其余按字母序。没有额度数据的 agent 不在结果里。
    /// `now` 不参与排序（没有可比较的拉取时间）；保留参数是为了让时间线和意图共用同一个签名。
    public static func quotaAgents(
        in quotaWindows: [String: QuotaWindow]?,
        now _: Date? = nil
    ) -> [String] {
        guard let quotaWindows, !quotaWindows.isEmpty else { return [] }
        let valid = quotaWindows.keys.filter { hasQuotaData(quotaWindows[$0]) }
        guard !valid.isEmpty else { return [] }
        return valid.sorted { lhs, rhs in
            let rank1 = quotaAgentRank(lhs)
            let rank2 = quotaAgentRank(rhs)
            if rank1 != rank2 { return rank1 < rank2 }
            return lhs < rhs
        }
    }

    /// 默认 agent：`quotaAgents` 的第一个；没有任何可用额度数据时为 `nil`。
    public static func defaultQuotaAgent(
        in quotaWindows: [String: QuotaWindow]?,
        now: Date? = nil
    ) -> String? {
        quotaAgents(in: quotaWindows, now: now).first
    }

    public func quotaAgents(now: Date? = nil) -> [String] {
        Self.quotaAgents(in: quotaWindows, now: now)
    }

    public func defaultQuotaAgent(now: Date? = nil) -> String? {
        Self.defaultQuotaAgent(in: quotaWindows, now: now)
    }

    private static func quotaAgentRank(_ agent: String) -> Int {
        quotaAgentPriority.firstIndex(of: agent) ?? quotaAgentPriority.count
    }

    // MARK: - 小组件额度行与时间线重置时刻

    /// 小组件紧凑 agent 名称（例如 "claude" → "Claude"，"codex" → "Codex"）。
    public static func shortAgentLabel(for agent: String) -> String {
        switch agent {
        case "claude": return "Claude"
        case "codex": return "Codex"
        case "antigravity": return "Antigravity"
        case "grok": return "Grok"
        case "copilot": return "Copilot"
        case "minimax": return "MiniMax"
        case "qwen": return "Qwen"
        case "commandcode": return "Command"
        case "opencode": return "OpenCode"
        default: return AgentColors.label(for: agent)
        }
    }

    /// 指定 agent 在 `now` 时刻的 5 小时窗口状态。没有有限的 5 小时百分比时返回 `nil`（不把别的窗口显示成“已重置”）。
    /// 百分比存在但重置点已过（或无法解析）时 `isReset` 为 true，且不再带旧百分比。
    public func fiveHourQuotaBar(for agent: String, now: Date = Date()) -> WidgetQuotaBar? {
        guard let window = quotaWindows?[agent] else { return nil }
        guard let pct = window.fiveHourUsedPercent, pct.isFinite else { return nil }
        let hours = window.fiveHourWindowHours ?? 5
        if let reset = window.fiveHourResetsAt.flatMap(ReportDates.parseTimestamp), reset > now {
            return WidgetQuotaBar(
                id: "five_hour",
                windowHours: hours,
                usedPercent: min(max(pct, 0), 100),
                resetsAt: reset,
                isReset: false
            )
        }
        return WidgetQuotaBar(
            id: "five_hour",
            windowHours: hours,
            usedPercent: nil,
            resetsAt: nil,
            isReset: true
        )
    }

    /// 指定 agent 在 `now` 时刻的每周窗口状态。没有有限的每周百分比时返回 `nil`。
    public func weeklyQuotaBar(for agent: String, now: Date = Date()) -> WidgetQuotaBar? {
        guard let window = quotaWindows?[agent] else { return nil }
        guard let pct = window.weeklyUsedPercent, pct.isFinite else { return nil }
        let hours = window.weeklyWindowHours
        if let reset = ReportDates.parseTimestamp(window.weeklyResetsAt), reset > now {
            return WidgetQuotaBar(
                id: "weekly",
                windowHours: hours,
                usedPercent: min(max(pct, 0), 100),
                resetsAt: reset,
                isReset: false
            )
        }
        return WidgetQuotaBar(
            id: "weekly",
            windowHours: hours,
            usedPercent: nil,
            resetsAt: nil,
            isReset: true
        )
    }

    /// 指定 agent 的主额度条（5 小时 + 每周）。若无额度数据返回空数组。
    public func quotaBars(for agent: String, now: Date = Date()) -> [WidgetQuotaBar] {
        var out: [WidgetQuotaBar] = []
        if let five = fiveHourQuotaBar(for: agent, now: now) {
            out.append(five)
        }
        if let weekly = weeklyQuotaBar(for: agent, now: now) {
            out.append(weekly)
        }
        return out
    }

    /// 所有在 `now` 之后的额度重置时刻（升序去重），供 WidgetKit 时间线在重置点精确刷新为“已重置”状态。
    public func upcomingResetDates(after now: Date) -> [Date] {
        guard let quotaWindows else { return [] }
        var dates = Set<Date>()
        for window in quotaWindows.values {
            if window.fiveHourUsedPercent?.isFinite == true,
               let d = window.fiveHourResetsAt.flatMap(ReportDates.parseTimestamp), d > now {
                dates.insert(d)
            }
            if window.weeklyUsedPercent?.isFinite == true,
               let d = ReportDates.parseTimestamp(window.weeklyResetsAt), d > now {
                dates.insert(d)
            }
        }
        return dates.sorted()
    }
}
