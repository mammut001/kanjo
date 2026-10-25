import Foundation
import SwiftUI
import KanjoCore

/// 磁盘页自己的数据。和用量报告分开加载：打开磁盘页才去取，失败时保留上一份。
@MainActor
final class DiskStore: ObservableObject {
    static let shared = DiskStore()

    @Published private(set) var report: DiskReport?
    @Published private(set) var error: String?
    @Published private(set) var isLoading = false
    @Published private(set) var lastRefresh: Date?
    @Published private(set) var sourceDescription = ""

    private var generation = 0
    private var source: (any DiskSource)?

    func makeSource() -> (any DiskSource, String) {
        if let o = DefaultPaths.diskDataOverride() {
            return (FileDiskSource(url: o), "File (--disk-data): \(o.path)")
        }
        let cli = CLILaunch.command()
        let url = CLILaunch.workingDirectory()
        let shown = DiskCommand.report(from: cli)
        return (DiskDataSource(cliCommand: cli, workingDirectory: url),
                "Command: \(shown)" + (url.map { " (in \($0.path))" } ?? ""))
    }

    func refresh() {
        generation += 1
        let gen = generation
        let (src, desc) = makeSource()
        source = src
        sourceDescription = desc
        isLoading = true
        Task {
            do {
                let r = try await src.load()
                guard gen == generation else { return }
                report = r
                error = nil
            } catch {
                guard gen == generation else { return }
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            lastRefresh = Date()
            isLoading = false
        }
    }

    /// 设置改过、并且磁盘页已经加载过时才重取。没打开过磁盘页就不额外跑 CLI。
    func applySettings() {
        guard report != nil || error != nil else { return }
        refresh()
    }

    /// 先 dry-run（confirmed: false），用户确认后再带 --yes。文件来源会拒绝，不会动磁盘。
    func clean(ids: [String], olderThan: String?, confirmed: Bool) async throws -> CleanResult {
        let src = source ?? makeSource().0
        return try await src.clean(ids: ids, olderThan: olderThan, confirmed: confirmed)
    }
}
