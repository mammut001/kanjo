import Foundation
import SwiftUI
import KanjoCore

/// 磁盘报告独立预取，后台刷新时保留内存和磁盘缓存中的上一份。
@MainActor
final class DiskStore: ObservableObject {
    static let shared = DiskStore()

    @Published private var state: DiskReportState
    @Published private(set) var error: String?
    @Published private(set) var lastRefresh: Date?
    @Published private(set) var sourceDescription = ""

    var report: DiskReport? { state.report }
    var hasReport: Bool { state.hasReport }
    var isLoading: Bool { state.isLoading }
    var isRescanning: Bool { state.isRescanning }

    private let cache: DiskReportCache?
    private var prefetch: Task<Void, Never>?
    private var generation = 0
    private var pendingRefresh = false
    private var pendingRescan = false
    private var source: (any DiskSource)?

    init() {
        // 文件演示不读写真实 CLI 的缓存，也不会从缓存继承清理数据源。
        cache = DefaultPaths.diskDataOverride() == nil ? DiskReportCache() : nil
        state = DiskReportState(report: cache?.load())
    }

    func makeSource(rescan: Bool = false) -> (any DiskSource, String) {
        if let o = DefaultPaths.diskDataOverride() {
            return (FileDiskSource(url: o), "File (--disk-data): \(o.path)")
        }
        let cli = CLILaunch.command()
        let url = CLILaunch.workingDirectory()
        let shown = DiskCommand.report(from: cli, rescan: rescan)
        return (DiskDataSource(cliCommand: cli, workingDirectory: url, rescan: rescan),
                "Command: \(shown)" + (url.map { " (in \($0.path))" } ?? ""))
    }

    func cancelPrefetch() {
        prefetch?.cancel()
        prefetch = nil
    }

    /// 用量加载完成后调度，等待不会阻塞主线程；新一轮用量刷新会取消等待。
    func schedulePrefetch(delay: TimeInterval) {
        cancelPrefetch()
        prefetch = Task {
            do {
                try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            } catch { return }
            guard !Task.isCancelled else { return }
            prefetch = nil
            refresh()
        }
    }

    func refresh(rescan: Bool = false) {
        cancelPrefetch()
        guard state.beginRefresh() else {
            // 清理或手动刷新发生在预取中时，串行补跑强制扫描，避免两个 disk 进程竞争。
            pendingRefresh = true
            if rescan { pendingRescan = true }
            return
        }
        let gen = generation
        let (src, desc) = makeSource(rescan: rescan)
        source = src
        sourceDescription = desc
        Task {
            var loaded: DiskReport?
            do {
                let r = try await src.load()
                if gen == generation {
                    loaded = r
                    error = nil
                    if let cache {
                        await Task.detached(priority: .utility) { cache.save(r) }.value
                    }
                }
            } catch {
                if src is DiskDataSource { await ReportStore.shared.checkPython() }
                if gen == generation {
                    self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                }
            }
            state.finishRefresh(report: gen == generation ? loaded : nil)
            lastRefresh = Date()
            if pendingRefresh || pendingRescan {
                let force = pendingRescan
                pendingRefresh = false
                pendingRescan = false
                refresh(rescan: force)
            }
        }
    }

    /// 设置改动后由用量报告完成时调度预取，忽略旧数据源仍在运行的结果。
    func applySettings() {
        generation += 1
        source = nil
        pendingRefresh = false
        pendingRescan = false
        cancelPrefetch()
    }

    /// 先 dry-run（confirmed: false），用户确认后再带 --yes。文件来源会拒绝，不会动磁盘。
    func clean(ids: [String], olderThan: String?, confirmed: Bool) async throws -> CleanResult {
        let src = source ?? makeSource().0
        do { return try await src.clean(ids: ids, olderThan: olderThan, confirmed: confirmed) }
        catch {
            if src is DiskDataSource { await ReportStore.shared.checkPython() }
            throw error
        }
    }
}
