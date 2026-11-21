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
    /// 上一次后台自动清理已合并 worktree 的结果，Disk 页显示一次，用户关掉后清空。
    @Published var autoCleanRecord: AutoCleanRecord?

    var report: DiskReport? { state.report }
    var hasReport: Bool { state.hasReport }
    var isLoading: Bool { state.isLoading }
    var isRescanning: Bool { state.isRescanning }
    var isStale: Bool { state.isStale() }

    private let cache: DiskReportCache?
    private var gate = DiskRefreshGate()
    private var source: (any DiskSource)?
    private var autoCleanRunning = false
    private var autoCleanLastAttempt: Set<String> = []

    struct AutoCleanRecord: Equatable {
        let result: CleanResult
        let date: Date
    }

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
        let shown = DiskCommand.report(from: cli, rescan: rescan, maxAge: 21600)
        return (DiskDataSource(cliCommand: cli, workingDirectory: url, rescan: rescan, maxAge: 21600),
                "Command: \(shown)" + (url.map { " (in \($0.path))" } ?? ""))
    }

    func refresh(rescan: Bool = false) {
        guard state.beginRefresh() else {
            // 清理或手动刷新发生在预取中时，串行补跑强制扫描，避免两个 disk 进程竞争。
            gate.queue(rescan: rescan)
            return
        }
        let gen = gate.begin(sourceKey: makeSource().1)
        let (src, desc) = makeSource(rescan: rescan)
        source = src
        sourceDescription = desc
        Task {
            var loaded: DiskReport?
            do {
                let r = try await src.load()
                if gate.accepts(gen) {
                    loaded = r
                    error = nil
                    if let cache {
                        await Task.detached(priority: .utility) { cache.save(r) }.value
                    }
                }
            } catch {
                if src is DiskDataSource { await ReportStore.shared.checkPython() }
                if gate.accepts(gen) {
                    self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                }
            }
            state.finishRefresh(report: gate.accepts(gen) ? loaded : nil)
            if gate.accepts(gen) { lastRefresh = Date() }
            if let loaded { autoCleanMergedWorktrees(after: loaded) }
            if let force = gate.takePending() {
                refresh(rescan: force)
            }
        }
    }

    /// 设置改动后：只有磁盘命令或工作目录变了才作废旧数据源仍在运行的结果，并用新数据源补跑。
    func applySettings() {
        if gate.settingsApplied(sourceKey: makeSource().1, isLoading: state.isLoading) {
            source = nil
        }
    }

    /// `disk clean --merged-worktrees`，同样先 dry-run 再确认。
    func cleanMergedWorktrees(confirmed: Bool, onlyPaths: [String]? = nil) async throws -> CleanResult {
        let src = source ?? makeSource().0
        do { return try await src.cleanMergedWorktrees(confirmed: confirmed, onlyPaths: onlyPaths) }
        catch {
            if src is DiskDataSource { await ReportStore.shared.checkPython() }
            throw error
        }
    }

    /// 打开“自动清理已合并的工作树”后，每次扫描完成都在后台跑一次
    /// `disk clean --merged-worktrees --yes`。CLI 会重新扫描并重新检查每个 worktree，
    /// 这里只决定要不要启动。文件演示（--disk-data）从不清理。
    private func autoCleanMergedWorktrees(after report: DiskReport) {
        guard DefaultPaths.diskDataOverride() == nil, !autoCleanRunning else { return }
        let enabled = AppDefaults.store.bool(forKey: SettingsKeys.diskAutoCleanMergedWorktrees)
        guard let ids = MergedWorktreeAutoClean.candidates(enabled: enabled, report: report,
                                                           lastAttempt: autoCleanLastAttempt) else { return }
        autoCleanLastAttempt = ids
        autoCleanRunning = true
        Task {
            defer { autoCleanRunning = false }
            guard let result = try? await cleanMergedWorktrees(confirmed: true), !result.moved.isEmpty else { return }
            autoCleanRecord = AutoCleanRecord(result: result, date: Date())
            refreshAfterClean()
        }
    }

    /// 先 dry-run（confirmed: false），用户确认后再带 --yes。文件来源会拒绝，不会动磁盘。
    func clean(ids: [String], olderThan: String?, confirmed: Bool, onlyPaths: [String]? = nil) async throws -> CleanResult {
        let src = source ?? makeSource().0
        do { return try await src.clean(ids: ids, olderThan: olderThan, confirmed: confirmed, onlyPaths: onlyPaths) }
        catch {
            if src is DiskDataSource { await ReportStore.shared.checkPython() }
            throw error
        }
    }

    /// 清理成功后：丢掉应用侧磁盘报告缓存，再强制重扫。
    func refreshAfterClean() {
        cache?.invalidate()
        refresh(rescan: true)
    }
}
