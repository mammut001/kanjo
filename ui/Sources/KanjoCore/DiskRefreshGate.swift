import Foundation

/// 磁盘扫描的代次与补跑队列：只有磁盘数据源（命令 / 工作目录）真的变了，才丢弃进行中的扫描结果。
public struct DiskRefreshGate {
    public private(set) var generation = 0
    private var pendingRefresh = false
    private var pendingRescan = false
    private var sourceKey: String?

    public init() {}

    /// 开始一次扫描，返回它的代次。
    public mutating func begin(sourceKey: String) -> Int {
        self.sourceKey = sourceKey
        return generation
    }

    /// 扫描进行中又来了请求：结束后串行补跑（任一请求要强制扫描就强制）。
    public mutating func queue(rescan: Bool) {
        pendingRefresh = true
        if rescan { pendingRescan = true }
    }

    /// 设置已应用；返回数据源是否变了（变了时旧数据源进行中的结果作废，并用新数据源补跑一次）。
    @discardableResult
    public mutating func settingsApplied(sourceKey newKey: String, isLoading: Bool) -> Bool {
        guard newKey != sourceKey else { return false }
        generation += 1
        sourceKey = newKey
        if isLoading { pendingRefresh = true }
        return true
    }

    public func accepts(_ gen: Int) -> Bool { gen == generation }

    /// 取出排队的补跑：nil = 没有；否则值表示是否强制扫描。
    public mutating func takePending() -> Bool? {
        guard pendingRefresh || pendingRescan else { return nil }
        let force = pendingRescan
        pendingRefresh = false
        pendingRescan = false
        return force
    }
}
