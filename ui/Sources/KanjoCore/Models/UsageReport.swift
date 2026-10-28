import Foundation

// 严格对应 CONTRACT.md 的 Codable 模型。字段名用 CodingKeys 映射 snake_case；
// 契约里标注「可为 null」的字段才是 Optional，其余缺失即解码失败。

/// UI 能完整理解的最高 schema 版本。
public let supportedSchemaVersion = 1

public struct UsageReport: Codable, Equatable {
    public var schemaVersion: Int
    public var generatedAt: String
    public var generatedBy: String?     // 产出工具和版本，如 "kanjo 0.1.0"
    public var timezone: String?        // IANA 时区名，所有 YYYY-MM-DD 按它划分
    public var currency: String
    public var costNote: String
    public var config: ReportConfig
    /// 各 agent 的额度窗口（「Since reset」范围用）；旧数据没有这个字段，拿不到的 agent 不出现。
    public var quotaWindows: [String: QuotaWindow]? = nil
    /// 各 agent 的订阅档位（「Subscription value」卡和「Billing cycle」范围用）；旧数据没有这个字段。
    public var subscriptions: [String: Subscription]? = nil
    public var totals: Aggregate
    public var projects: [Project]
    public var buckets: Buckets

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case generatedAt = "generated_at"
        case generatedBy = "generated_by"
        case timezone
        case currency
        case costNote = "cost_note"
        case config
        case quotaWindows = "quota_windows"
        case subscriptions
        case totals, projects, buckets
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try c.decode(Int.self, forKey: .schemaVersion)
        generatedAt = try c.decode(String.self, forKey: .generatedAt)
        generatedBy = try c.decodeIfPresent(String.self, forKey: .generatedBy)
        timezone = try c.decodeIfPresent(String.self, forKey: .timezone)
        currency = try c.decode(String.self, forKey: .currency)
        costNote = try c.decode(String.self, forKey: .costNote)
        config = try c.decodeIfPresent(ReportConfig.self, forKey: .config)
            ?? ReportConfig(dominantThreshold: 0.8)
        quotaWindows = try c.decodeIfPresent([String: QuotaWindow].self, forKey: .quotaWindows)
        subscriptions = try c.decodeIfPresent([String: Subscription].self, forKey: .subscriptions)
        totals = try c.decode(Aggregate.self, forKey: .totals)
        projects = try c.decode([Project].self, forKey: .projects)
        buckets = try c.decode(Buckets.self, forKey: .buckets)
    }

    /// schema_version 高于本 UI 支持的版本：显示警告，继续渲染。
    public var isNewerSchema: Bool { schemaVersion > supportedSchemaVersion }

    /// 报告里所有 agent 的显示名（agent key → label）。
    public var agentLabels: [String: String] {
        var out: [String: String] = [:]
        for p in projects { for a in p.byAgent { out[a.agent] = a.label } }
        return out
    }

    /// 格式化后的 cost_note 文本。若为空或纯空白返回 nil；若为默认英文字符串则返回本地化文案；否则返回原文。
    public var costNoteDisplayText: String? {
        let trimmed = costNote.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return nil }
        if trimmed == "API-equivalent cost estimated from public API prices. Not actual subscription spend." {
            return L10n.tr("common.cost_note_default")
        }
        return trimmed
    }
}

public struct ReportConfig: Codable, Equatable {
    public var dominantThreshold: Double

    enum CodingKeys: String, CodingKey {
        case dominantThreshold = "dominant_threshold"
    }

    public init(dominantThreshold: Double) {
        self.dominantThreshold = dominantThreshold
    }
}

/// 额度附加窗口（如 Antigravity 中的第三方模型组 Claude / GPT 窗口）。
public struct ExtraQuotaWindow: Codable, Equatable, Identifiable {
    public var id: String
    public var title: String
    public var usedPercent: Double?
    public var resetsAt: String?
    public var windowHours: Int?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case usedPercent = "used_percent"
        case resetsAt = "resets_at"
        case windowHours = "window_hours"
    }

    public init(id: String, title: String, usedPercent: Double? = nil, resetsAt: String? = nil, windowHours: Int? = nil) {
        self.id = id
        self.title = title
        self.usedPercent = usedPercent
        self.resetsAt = resetsAt
        self.windowHours = windowHours
    }
}

/// 一个 agent 的额度窗口（契约第 2 节 quota_windows）。
public struct QuotaWindow: Codable, Equatable {
    public var weeklyResetsAt: String       // 下次周重置，ISO 8601 UTC
    public var weeklyWindowHours: Int
    public var weeklyUsedPercent: Double?   // 0–100；缓存没有或窗口已过时为 nil
    public var fiveHourResetsAt: String?
    public var fiveHourWindowHours: Int?
    public var fiveHourUsedPercent: Double?
    public var source: String               // "live" | "tokei" | "manual"
    public var extraWindows: [ExtraQuotaWindow]?

    enum CodingKeys: String, CodingKey {
        case weeklyResetsAt = "weekly_resets_at"
        case weeklyWindowHours = "weekly_window_hours"
        case weeklyUsedPercent = "weekly_used_percent"
        case fiveHourResetsAt = "five_hour_resets_at"
        case fiveHourWindowHours = "five_hour_window_hours"
        case fiveHourUsedPercent = "five_hour_used_percent"
        case source
        case extraWindows = "extra_windows"
    }

    public init(weeklyResetsAt: String, weeklyWindowHours: Int = 168, weeklyUsedPercent: Double? = nil,
                fiveHourResetsAt: String? = nil, fiveHourWindowHours: Int? = nil, fiveHourUsedPercent: Double? = nil,
                source: String = "tokei", extraWindows: [ExtraQuotaWindow]? = nil) {
        self.weeklyResetsAt = weeklyResetsAt
        self.weeklyWindowHours = weeklyWindowHours
        self.weeklyUsedPercent = weeklyUsedPercent
        self.fiveHourResetsAt = fiveHourResetsAt
        self.fiveHourWindowHours = fiveHourWindowHours
        self.fiveHourUsedPercent = fiveHourUsedPercent
        self.source = source
        self.extraWindows = extraWindows
    }
}

/// 一个 agent 的订阅档位（契约第 2 节 subscriptions）。月费未知时 monthlyPriceUsd 为 nil。
public struct Subscription: Codable, Equatable {
    public var plan: String
    public var planLabel: String
    public var monthlyPriceUsd: Double?
    public var cycleStart: String          // 当前账期起点，ISO 8601 UTC
    public var cycleEnd: String            // 下一账期起点
    public var anchorDay: Int?             // rolling_30d 时未知
    public var cycleSource: String         // subscription_date | manual | rolling_30d；容忍未知值
    public var extraUsageEnabled: Bool
    public var source: String              // detected | manual

    enum CodingKeys: String, CodingKey {
        case plan
        case planLabel = "plan_label"
        case monthlyPriceUsd = "monthly_price_usd"
        case cycleStart = "cycle_start"
        case cycleEnd = "cycle_end"
        case anchorDay = "anchor_day"
        case cycleSource = "cycle_source"
        case extraUsageEnabled = "extra_usage_enabled"
        case source
    }

    public init(plan: String, planLabel: String, monthlyPriceUsd: Double?, cycleStart: String, cycleEnd: String,
                anchorDay: Int?, cycleSource: String, extraUsageEnabled: Bool, source: String) {
        self.plan = plan
        self.planLabel = planLabel
        self.monthlyPriceUsd = monthlyPriceUsd
        self.cycleStart = cycleStart
        self.cycleEnd = cycleEnd
        self.anchorDay = anchorDay
        self.cycleSource = cycleSource
        self.extraUsageEnabled = extraUsageEnabled
        self.source = source
    }
}

public struct Tokens: Codable, Equatable {
    public var input: Int
    public var output: Int
    public var cacheRead: Int
    public var cacheWrite: Int
    public var thinking: Int
    public var total: Int

    enum CodingKeys: String, CodingKey {
        case input, output
        case cacheRead = "cache_read"
        case cacheWrite = "cache_write"
        case thinking, total
    }

    public init(input: Int = 0, output: Int = 0, cacheRead: Int = 0, cacheWrite: Int = 0, thinking: Int = 0, total: Int = 0) {
        self.input = input; self.output = output; self.cacheRead = cacheRead
        self.cacheWrite = cacheWrite; self.thinking = thinking; self.total = total
    }

    /// 手机快照里的会话只有 `{"total": N}`；其余字段缺失时补 0，total 缺失时用四项之和。
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        input = try c.decodeIfPresent(Int.self, forKey: .input) ?? 0
        output = try c.decodeIfPresent(Int.self, forKey: .output) ?? 0
        cacheRead = try c.decodeIfPresent(Int.self, forKey: .cacheRead) ?? 0
        cacheWrite = try c.decodeIfPresent(Int.self, forKey: .cacheWrite) ?? 0
        thinking = try c.decodeIfPresent(Int.self, forKey: .thinking) ?? 0
        total = try c.decodeIfPresent(Int.self, forKey: .total)
            ?? (input + output + cacheRead + cacheWrite)
    }

    public static let zero = Tokens()

    public static func + (a: Tokens, b: Tokens) -> Tokens {
        Tokens(input: a.input + b.input, output: a.output + b.output,
               cacheRead: a.cacheRead + b.cacheRead, cacheWrite: a.cacheWrite + b.cacheWrite,
               thinking: a.thinking + b.thinking, total: a.total + b.total)
    }
}

public struct Aggregate: Codable, Equatable {
    public var cost: Double
    public var tokens: Tokens
    public var sessions: Int
    /// 只有 totals 带：去重后的真实会话数。拆分会话在 sessions 里按项目各算 1。
    public var uniqueSessions: Int?
    public var firstActive: String?
    public var lastActive: String?

    enum CodingKeys: String, CodingKey {
        case cost, tokens, sessions
        case uniqueSessions = "unique_sessions"
        case firstActive = "first_active"
        case lastActive = "last_active"
    }
}

public struct Project: Codable, Equatable, Identifiable {
    public var id: String
    public var name: String
    public var remote: String?
    public var paths: [String]
    public var pathMissing: Bool

    public var cost: Double
    public var tokens: Tokens
    public var sessions: Int
    public var firstActive: String?
    public var lastActive: String?

    public var byAgent: [AgentCost]
    public var byModel: [ModelCost]
    public var byDay: [DayCost]
    public var byBranch: [BranchCost]
    public var sessionsDetail: [Session]

    enum CodingKeys: String, CodingKey {
        case id, name, remote, paths
        case pathMissing = "path_missing"
        case cost, tokens, sessions
        case firstActive = "first_active"
        case lastActive = "last_active"
        case byAgent = "by_agent"
        case byModel = "by_model"
        case byDay = "by_day"
        case byBranch = "by_branch"
        case sessionsDetail = "sessions_detail"
    }

    public init(id: String, name: String, remote: String?, paths: [String], pathMissing: Bool,
                cost: Double, tokens: Tokens, sessions: Int, firstActive: String? = nil, lastActive: String? = nil,
                byAgent: [AgentCost], byModel: [ModelCost], byDay: [DayCost],
                byBranch: [BranchCost], sessionsDetail: [Session]) {
        self.id = id
        self.name = name
        self.remote = remote
        self.paths = paths
        self.pathMissing = pathMissing
        self.cost = cost
        self.tokens = tokens
        self.sessions = sessions
        self.firstActive = firstActive
        self.lastActive = lastActive
        self.byAgent = byAgent
        self.byModel = byModel
        self.byDay = byDay
        self.byBranch = byBranch
        self.sessionsDetail = sessionsDetail
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        remote = try c.decodeIfPresent(String.self, forKey: .remote)
        paths = try c.decodeIfPresent([String].self, forKey: .paths) ?? []
        pathMissing = try c.decodeIfPresent(Bool.self, forKey: .pathMissing) ?? false
        cost = try c.decode(Double.self, forKey: .cost)
        tokens = try c.decode(Tokens.self, forKey: .tokens)
        sessions = try c.decode(Int.self, forKey: .sessions)
        firstActive = try c.decodeIfPresent(String.self, forKey: .firstActive)
        lastActive = try c.decodeIfPresent(String.self, forKey: .lastActive)
        byAgent = try c.decode([AgentCost].self, forKey: .byAgent)
        byModel = try c.decode([ModelCost].self, forKey: .byModel)
        byDay = try c.decode([DayCost].self, forKey: .byDay)
        byBranch = try c.decodeIfPresent([BranchCost].self, forKey: .byBranch) ?? []
        sessionsDetail = try c.decodeIfPresent([Session].self, forKey: .sessionsDetail) ?? []
    }
}

public struct AgentCost: Codable, Equatable, Identifiable {
    public var agent: String
    public var label: String
    public var cost: Double
    public var tokens: Tokens
    public var sessions: Int
    public var id: String { agent }
}

public struct ModelCost: Codable, Equatable, Identifiable {
    public var model: String
    public var agent: String
    public var cost: Double
    public var tokens: Tokens
    public var estimated: Bool
    public var id: String { agent + "/" + model }

    public init(model: String, agent: String, cost: Double, tokens: Tokens, estimated: Bool = false) {
        self.model = model
        self.agent = agent
        self.cost = cost
        self.tokens = tokens
        self.estimated = estimated
    }
}

public struct DayCost: Codable, Equatable, Identifiable {
    public var day: String      // YYYY-MM-DD，本地时区
    public var cost: Double
    public var tokens: Int      // total
    public var byAgent: [String: Double]? = nil   // 当天各 agent 的 cost；旧数据没有这个字段
    public var byAgentTokens: [String: Int]? = nil  // 当天各 agent 的 tokens.total；旧数据没有这个字段
    public var id: String { day }

    enum CodingKeys: String, CodingKey {
        case day, cost, tokens
        case byAgent = "by_agent"
        case byAgentTokens = "by_agent_tokens"
    }
}

public struct BranchCost: Codable, Equatable, Identifiable {
    public var branch: String
    public var cost: Double
    public var sessions: Int
    public var id: String { branch }
}

public struct Session: Codable, Equatable, Identifiable {
    public var id: String
    public var agent: String
    public var label: String
    public var started: String
    public var ended: String
    public var cwd: String?             // 日志里没有工作目录时为 null
    public var branch: String?
    public var models: [String]
    public var cost: Double
    public var tokens: Tokens
    public var share: Double
    public var attribution: String
    public var subagents: Int
    public var title: String?
    public var byDay: [DayCost]? = nil

    enum CodingKeys: String, CodingKey {
        case id, agent, label, started, ended, cwd, branch, models, cost, tokens, share, attribution, subagents, title
        case byDay = "by_day"
    }

    public init(
        id: String,
        agent: String,
        label: String,
        started: String,
        ended: String,
        cwd: String? = nil,
        branch: String? = nil,
        models: [String] = [],
        cost: Double,
        tokens: Tokens,
        share: Double,
        attribution: String,
        subagents: Int,
        title: String? = nil,
        byDay: [DayCost]? = nil
    ) {
        self.id = id
        self.agent = agent
        self.label = label
        self.started = started
        self.ended = ended
        self.cwd = cwd
        self.branch = branch
        self.models = models
        self.cost = cost
        self.tokens = tokens
        self.share = share
        self.attribution = attribution
        self.subagents = subagents
        self.title = title
        self.byDay = byDay
    }

    /// 手机快照的精简会话没有 id / label / share / attribution / subagents / by_day。
    /// 兜底值保证范围过滤和列表仍能工作，同时不改变完整导出的语义。
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        agent = try c.decode(String.self, forKey: .agent)
        started = try c.decode(String.self, forKey: .started)
        ended = try c.decode(String.self, forKey: .ended)
        cost = try c.decode(Double.self, forKey: .cost)
        tokens = try c.decode(Tokens.self, forKey: .tokens)
        id = try c.decodeIfPresent(String.self, forKey: .id) ?? "\(agent)@\(started)"
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? AgentColors.label(for: agent)
        cwd = try c.decodeIfPresent(String.self, forKey: .cwd)
        branch = try c.decodeIfPresent(String.self, forKey: .branch)
        models = try c.decodeIfPresent([String].self, forKey: .models) ?? []
        share = try c.decodeIfPresent(Double.self, forKey: .share) ?? 1
        attribution = try c.decodeIfPresent(String.self, forKey: .attribution) ?? "none"
        subagents = try c.decodeIfPresent(Int.self, forKey: .subagents) ?? 0
        title = try c.decodeIfPresent(String.self, forKey: .title)
        byDay = try c.decodeIfPresent([DayCost].self, forKey: .byDay)
    }

    public var startedDate: Date? { ReportDates.parseTimestamp(started) }
    public var endedDate: Date? { ReportDates.parseTimestamp(ended) }
}

/// unattributed / excluded：Aggregate 外加 sessions_detail。
public struct SessionBucket: Codable, Equatable {
    public var cost: Double
    public var tokens: Tokens
    public var sessions: Int
    public var firstActive: String?
    public var lastActive: String?
    public var sessionsDetail: [Session]

    enum CodingKeys: String, CodingKey {
        case cost, tokens, sessions
        case firstActive = "first_active"
        case lastActive = "last_active"
        case sessionsDetail = "sessions_detail"
    }

    public init(cost: Double, tokens: Tokens, sessions: Int, firstActive: String? = nil,
                lastActive: String? = nil, sessionsDetail: [Session]) {
        self.cost = cost
        self.tokens = tokens
        self.sessions = sessions
        self.firstActive = firstActive
        self.lastActive = lastActive
        self.sessionsDetail = sessionsDetail
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        cost = try c.decode(Double.self, forKey: .cost)
        tokens = try c.decode(Tokens.self, forKey: .tokens)
        sessions = try c.decode(Int.self, forKey: .sessions)
        firstActive = try c.decodeIfPresent(String.self, forKey: .firstActive)
        lastActive = try c.decodeIfPresent(String.self, forKey: .lastActive)
        sessionsDetail = try c.decodeIfPresent([Session].self, forKey: .sessionsDetail) ?? []
    }
}

public struct ParseFailedBucket: Codable, Equatable {
    public var sessions: Int
    public var files: [String]

    enum CodingKeys: String, CodingKey {
        case sessions, files
    }

    public init(sessions: Int, files: [String]) {
        self.sessions = sessions
        self.files = files
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sessions = try c.decode(Int.self, forKey: .sessions)
        files = try c.decodeIfPresent([String].self, forKey: .files) ?? []
    }
}

public struct Buckets: Codable, Equatable {
    public var unattributed: SessionBucket
    public var excluded: SessionBucket
    public var parseFailed: ParseFailedBucket

    enum CodingKeys: String, CodingKey {
        case unattributed, excluded
        case parseFailed = "parse_failed"
    }
}

// MARK: - 日期

public enum ReportDates {
    private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    public static func parseTimestamp(_ s: String) -> Date? {
        iso.date(from: s) ?? isoFractional.date(from: s)
    }

    /// "YYYY-MM-DD"（契约里的本地日期）→ 本地零点。
    public static func parseDay(_ s: String) -> Date? {
        dayFormatter.date(from: s)
    }
}
