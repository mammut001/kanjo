import Foundation
import KanjoCore

/// 手机端只读快照的来源。首版读内置示例；T4 会加 CloudKit 实现，界面无需改动。
protocol SnapshotSource {
    /// nil 表示还没有任何快照（显示空状态）。
    func load() async throws -> UsageReport?
}

/// 读 App bundle 里的 sample-snapshot.json（由 ui/fixtures/sample.json 复制而来）。
struct BundledSampleSnapshotSource: SnapshotSource {
    var bundle: Bundle = .main
    var resourceName = "sample-snapshot"

    func load() async throws -> UsageReport? {
        guard let url = bundle.url(forResource: resourceName, withExtension: "json") else {
            return nil
        }
        let data = try Data(contentsOf: url)
        return try ReportDecoder.decode(data)
    }
}

// TODO(T4): 增加 CloudKitSnapshotSource（私有库 Snapshot 记录、取 generatedAt 最新的一条），
// 用它替换 BundledSampleSnapshotSource；SnapshotSource 协议保持不变。
