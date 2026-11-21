import Foundation

/// 日志监听目录（`kanjo paths --json`）的获取状态：启动时获取失败、或启动后才出现的 agent 目录，
/// 都要在之后的成功刷新里补取，不能只靠 30 分钟兜底定时器。
public struct WatcherPathsState: Equatable {
    /// 成功取到之后，再隔多久重新取一次（发现新出现的 agent 目录）。
    public static let refetchInterval: TimeInterval = 30 * 60

    public private(set) var paths: Set<String>?
    public private(set) var isFetching = false
    private var lastSuccess: Date?

    public init() {}

    /// 准备获取；`force`（启动 / 设置改动）总是获取，否则只在从未成功或已过 `refetchInterval` 时获取。
    public mutating func begin(force: Bool, now: Date = Date()) -> Bool {
        if !force {
            guard !isFetching else { return false }
            if let lastSuccess, now.timeIntervalSince(lastSuccess) < Self.refetchInterval { return false }
        }
        isFetching = true
        return true
    }

    /// 获取结束；`paths` 为 nil 表示失败。返回目录集合是否变了（需要重建监听）。
    public mutating func finish(paths: [String]?, now: Date = Date()) -> Bool {
        isFetching = false
        guard let paths else { return false }
        let set = Set(paths)
        let changed = set != self.paths
        self.paths = set
        lastSuccess = now
        return changed
    }
}
