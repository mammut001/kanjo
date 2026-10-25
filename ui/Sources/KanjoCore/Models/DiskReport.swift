import Foundation

// CONTRACT.md §10。kind / deletable 遇到不认识的字符串不失败，原样留下。
// reclaimable = deletable 不是 never，且 blocked 为空。

public enum DiskKind: Equatable, Hashable {
    case sessions, scratch, worktrees, cache, memory, other
    case unknown(String)

    public var rawValue: String {
        switch self {
        case .sessions: return "sessions"
        case .scratch: return "scratch"
        case .worktrees: return "worktrees"
        case .cache: return "cache"
        case .memory: return "memory"
        case .other: return "other"
        case .unknown(let s): return s
        }
    }
}

extension DiskKind: Codable {
    public init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        switch raw {
        case "sessions": self = .sessions
        case "scratch": self = .scratch
        case "worktrees": self = .worktrees
        case "cache": self = .cache
        case "memory": self = .memory
        case "other": self = .other
        default: self = .unknown(raw)
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        try c.encode(rawValue)
    }
}

public enum DiskDeletable: Equatable, Hashable {
    case always, afterImport, whenClean, never
    case unknown(String)

    public var rawValue: String {
        switch self {
        case .always: return "always"
        case .afterImport: return "after_import"
        case .whenClean: return "when_clean"
        case .never: return "never"
        case .unknown(let s): return s
        }
    }
}

extension DiskDeletable: Codable {
    public init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        switch raw {
        case "always": self = .always
        case "after_import": self = .afterImport
        case "when_clean": self = .whenClean
        case "never": self = .never
        default: self = .unknown(raw)
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        try c.encode(rawValue)
    }
}

public struct DiskReport: Codable, Equatable {
    public var schemaVersion: Int
    public var generatedAt: String
    public var totalBytes: Int
    public var reclaimableBytes: Int
    public var agents: [DiskAgent]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case generatedAt = "generated_at"
        case totalBytes = "total_bytes"
        case reclaimableBytes = "reclaimable_bytes"
        case agents
    }

    public static let empty = DiskReport(schemaVersion: 1, generatedAt: "", totalBytes: 0, reclaimableBytes: 0, agents: [])

    public init(schemaVersion: Int, generatedAt: String, totalBytes: Int, reclaimableBytes: Int, agents: [DiskAgent]) {
        self.schemaVersion = schemaVersion
        self.generatedAt = generatedAt
        self.totalBytes = totalBytes
        self.reclaimableBytes = reclaimableBytes
        self.agents = agents
    }

    public var isNewerSchema: Bool { schemaVersion > supportedSchemaVersion }

    public var allEntries: [DiskEntry] { agents.flatMap(\.entries) }

    /// 所有 deletable != never 且 blocked 为空的条目字节之和。应等于 reclaimable_bytes。
    public var summedReclaimableBytes: Int {
        allEntries.filter(\.isReclaimable).reduce(0) { $0 + $1.bytes }
    }
}

public struct DiskAgent: Codable, Equatable, Identifiable {
    public var agent: String
    public var label: String
    public var bytes: Int
    public var entries: [DiskEntry]
    public var id: String { agent }
}

public struct DiskEntry: Codable, Equatable, Identifiable {
    public var id: String
    public var kind: DiskKind
    public var path: String
    public var bytes: Int
    public var files: Int
    public var oldest: String
    public var newest: String
    public var deletable: DiskDeletable
    public var blocked: [String]
    public var note: String?

    /// 现在可以交给 `disk clean` 的条目。never 永久留下；blocked 非空时 CLI 会跳过。
    public var isReclaimable: Bool { deletable != .never && blocked.isEmpty }
}

public struct CleanSkip: Codable, Equatable {
    public var id: String
    public var reason: String

    public init(id: String, reason: String) {
        self.id = id
        self.reason = reason
    }
}

public struct CleanResult: Codable, Equatable {
    public var moved: [String]
    public var freedBytes: Int
    public var skipped: [CleanSkip]

    public init(moved: [String], freedBytes: Int, skipped: [CleanSkip]) {
        self.moved = moved
        self.freedBytes = freedBytes
        self.skipped = skipped
    }

    enum CodingKeys: String, CodingKey {
        case moved
        case freedBytes = "freed_bytes"
        case skipped
    }
}

/// blocked 原因的界面短句。不认识的原因保留原文（下划线换成空格）。
public enum DiskBlock {
    public static func short(_ reason: String) -> String {
        switch reason {
        case "not_imported": return "not imported"
        case "uncommitted_changes": return "uncommitted changes"
        case "active": return "active"
        default: return reason.replacingOccurrences(of: "_", with: " ")
        }
    }

    public static func title(_ reason: String) -> String { "Blocked: \(short(reason))" }

    public static func explanation(_ reason: String) -> String {
        switch reason {
        case "not_imported":
            return "The ledger has not imported every file here yet, so cleaning would drop numbers that are not saved."
        case "uncommitted_changes":
            return "This git worktree has uncommitted changes, so it stays until those changes are committed or discarded."
        case "active":
            return "Something wrote here in the last 24 hours, or a running process is using it."
        default:
            return "The CLI will not move this entry until the block is cleared."
        }
    }
}

/// dry-run 结果的可读计划：路径按条目分组，附数量和大小。确认页和测试共用这一份。
public struct CleanPlanGroup: Equatable {
    public var entryID: String
    public var title: String
    public var paths: [String]
    /// 整目录被移动时用条目自己的字节数；CLI 只列出其中一些文件时没有单文件大小，为 nil。
    public var bytes: Int?
}

public enum CleanPlan {
    public static func groups(report: DiskReport, moved: [String]) -> [CleanPlanGroup] {
        let index: [(entry: DiskEntry, title: String)] = report.agents.flatMap { agent in
            agent.entries.map { ($0, "\(agent.label) · \($0.kind.rawValue)") }
        }
        struct Bucket { var title: String; var paths: [String] = [] }
        var buckets: [String: Bucket] = [:]
        var seen: [String] = []
        var other: [String] = []
        for path in moved {
            let hits = index.filter { owns($0.entry, path) }
            guard let hit = hits.max(by: { $0.entry.path.count < $1.entry.path.count }) else {
                other.append(path)
                continue
            }
            var bucket = buckets[hit.entry.id] ?? Bucket(title: hit.title)
            if buckets[hit.entry.id] == nil { seen.append(hit.entry.id) }
            bucket.paths.append(path)
            buckets[hit.entry.id] = bucket
        }
        let order = index.map(\.entry.id)
        let ids = seen.sorted { a, b in
            (order.firstIndex(of: a) ?? Int.max) < (order.firstIndex(of: b) ?? Int.max)
        }
        var result: [CleanPlanGroup] = []
        for id in ids {
            guard let entry = index.first(where: { $0.entry.id == id })?.entry, let bucket = buckets[id] else { continue }
            let whole = bucket.paths.count == 1 && bucket.paths[0] == entry.path
            result.append(CleanPlanGroup(entryID: id, title: bucket.title, paths: bucket.paths,
                                          bytes: whole ? entry.bytes : nil))
        }
        if !other.isEmpty {
            result.append(CleanPlanGroup(entryID: "", title: "Other", paths: other, bytes: nil))
        }
        return result
    }

    public static func text(report: DiskReport, result: CleanResult) -> String {
        var blocks = groups(report: report, moved: result.moved).map { groupText($0) }
        blocks.append("Total \(countAndSize(count: result.moved.count, bytes: result.freedBytes))")
        var body = blocks.joined(separator: "\n\n")
        if !result.skipped.isEmpty {
            let lines = result.skipped.map { "\($0.id) — \(DiskBlock.short($0.reason))" }
            body += "\n\nSkipped\n" + lines.joined(separator: "\n")
        }
        return body
    }

    public static func groupText(_ g: CleanPlanGroup) -> String {
        ([g.title] + g.paths + [countAndSize(count: g.paths.count, bytes: g.bytes)]).joined(separator: "\n")
    }

    /// `1 path · 4.6 GB`，没有大小时只写数量（`2 paths`）。
    public static func countAndSize(count: Int, bytes: Int?) -> String {
        let noun = count == 1 ? "path" : "paths"
        guard let bytes else { return "\(count) \(noun)" }
        return "\(count) \(noun) · \(Fmt.bytes(bytes))"
    }

    private static func owns(_ entry: DiskEntry, _ path: String) -> Bool {
        path == entry.path || path.hasPrefix(entry.path + "/")
    }
}
