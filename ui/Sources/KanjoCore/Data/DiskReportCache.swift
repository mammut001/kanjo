import Foundation

/// 便利缓存：读写失败都忽略，CLI 仍是报告的来源。directory 可供测试隔离。
public struct DiskReportCache {
    public let fileURL: URL?

    public init(directory: URL? = nil) {
        let base = directory ?? FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?
            .appendingPathComponent(Bundle.main.bundleIdentifier ?? "com.lanshuagent.kanjo", isDirectory: true)
        fileURL = base?.appendingPathComponent("disk-report.json")
    }

    public func load() -> DiskReport? {
        guard let fileURL, let data = try? Data(contentsOf: fileURL) else { return nil }
        return try? DiskDecoder.decode(data)
    }

    public func save(_ report: DiskReport) {
        guard let fileURL else { return }
        do {
            try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(report).write(to: fileURL, options: .atomic)
        } catch {
            // 缓存不可写不影响内存中的报告。
        }
    }
}
