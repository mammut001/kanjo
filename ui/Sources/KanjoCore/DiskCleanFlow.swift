import Foundation

/// Dry-run 确认卡要冻结的参数：确认时不能再读可变的勾选 / Older than。
public struct DiskCleanPreview: Equatable {
    public var ids: [String]
    public var olderThan: String?
    public var result: CleanResult
    public var merged: Bool

    public init(ids: [String], olderThan: String?, result: CleanResult, merged: Bool = false) {
        self.ids = ids
        self.olderThan = olderThan
        self.result = result
        self.merged = merged
    }
}

/// Disk 页清理流程的可测逻辑（Mac DiskView / Windows DiskPage 共用语义）。
public enum DiskCleanFlow {
    /// 部分成功后：整目录已进 moved 的条目取消勾选；跳过或只挪了部分文件的条目保留。
    public static func selectionAfter(
        selected: Set<String>,
        report: DiskReport,
        result: CleanResult
    ) -> Set<String> {
        let moved = Set(result.moved)
        var next = selected
        for id in selected {
            guard let entry = report.allEntries.first(where: { $0.id == id }) else {
                next.remove(id)
                continue
            }
            if moved.contains(entry.path) {
                next.remove(id)
            }
        }
        return next
    }

    /// Move 只能点一次：已在执行，或 dry-run 没有可移动路径时都不能再开清理。
    public static func canBeginMove(applying: Bool, movedCount: Int) -> Bool {
        !applying && movedCount > 0
    }

    /// CLI 退出 0 的清理结果（含部分 moved + skipped）一律进结果卡，不当总失败。
    public static func presentsAsResultCard(_ result: CleanResult) -> Bool {
        _ = result
        return true
    }

    /// 结果卡要列出 moved；有 skipped 时用本地化原因，不露原始 reason 码。
    public static func resultShowsMovedPaths(_ result: CleanResult) -> Bool {
        !result.moved.isEmpty
    }
}
