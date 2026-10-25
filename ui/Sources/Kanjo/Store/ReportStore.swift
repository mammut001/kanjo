import Foundation
import SwiftUI
import KanjoCore

@MainActor
final class ReportStore: ObservableObject {
    static let shared = ReportStore()

    @Published private(set) var report: UsageReport?
    @Published private(set) var error: String?
    @Published private(set) var isLoading = false
    @Published private(set) var lastRefresh: Date?
    @Published private(set) var sourceDescription = ""

    /// `--data` / `KANJO_DATA` 指定的文件，优先于设置。
    let dataOverride: URL? = DefaultPaths.dataOverride()

    private var timer: Timer?
    private var generation = 0
    private let defaults = UserDefaults.standard

    init() {
        // 默认直接跑 CLI：仓库里 ui/ 旁边有 cli/ 就用它；没有（打包后的 .app）就先显示示例数据。
        let defaultKind: SourceKind = DefaultPaths.cliDirectoryExists ? .cli : .file
        defaults.register(defaults: [
            SettingsKeys.sourceKind: defaultKind.rawValue,
            SettingsKeys.filePath: "",
            SettingsKeys.cliCommand: CLIDataSource.defaultCommand,
            SettingsKeys.cliWorkingDirectory: "",
            SettingsKeys.refreshMinutes: 5,
            SettingsKeys.showAmountInMenuBar: true,
        ])
        refresh()
        restartTimer()
    }

    func makeSource() -> (UsageDataSource, String) {
        if let o = dataOverride {
            return (FileDataSource(url: o), "File (--data): \(o.path)")
        }
        let kind = SourceKind(rawValue: defaults.string(forKey: SettingsKeys.sourceKind) ?? "") ?? .file
        switch kind {
        case .file:
            let raw = (defaults.string(forKey: SettingsKeys.filePath) ?? "").trimmingCharacters(in: .whitespaces)
            let url = raw.isEmpty ? DefaultPaths.sampleFixture
                                  : URL(fileURLWithPath: (raw as NSString).expandingTildeInPath)
            return (FileDataSource(url: url), "File: \(url.path)")
        case .cli:
            let cmd = CLILaunch.command(defaults: defaults)
            // 工作目录留空 = 仓库里的 cli/，其次 install.sh 装的位置（DefaultPaths.resolvedCLIDirectory）；
            // 都没有就继承进程的当前目录。磁盘页用同一套命令和工作目录。
            let url = CLILaunch.workingDirectory(defaults: defaults)
            return (CLIDataSource(command: cmd, workingDirectory: url),
                    "Command: \(cmd)" + (url.map { " (in \($0.path))" } ?? ""))
        }
    }

    func refresh() {
        generation += 1
        let gen = generation
        let (source, desc) = makeSource()
        sourceDescription = desc
        isLoading = true
        Task {
            do {
                let r = try await source.load()
                guard gen == generation else { return }
                report = r
                error = nil
            } catch {
                guard gen == generation else { return }
                // 刷新失败时保留上一份报告，面板顶部显示错误。
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            lastRefresh = Date()
            isLoading = false
        }
    }

    func restartTimer() {
        timer?.invalidate()
        timer = nil
        let minutes = defaults.integer(forKey: SettingsKeys.refreshMinutes)
        guard minutes > 0 else { return }
        timer = Timer.scheduledTimer(withTimeInterval: TimeInterval(minutes * 60), repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
    }

    /// 设置改动后调用：重建数据源、重排定时器、立即刷新。磁盘页若已打开过，跟着重取。
    func applySettings() {
        restartTimer()
        refresh()
        DiskStore.shared.applySettings()
    }
}

/// 设置里的 CLI 命令和工作目录。用量导出和磁盘报告共用。
enum CLILaunch {
    static func command(defaults: UserDefaults = .standard) -> String {
        let cmd = (defaults.string(forKey: SettingsKeys.cliCommand) ?? "").trimmingCharacters(in: .whitespaces)
        return cmd.isEmpty ? CLIDataSource.defaultCommand : cmd
    }

    static func workingDirectory(defaults: UserDefaults = .standard) -> URL? {
        let dir = (defaults.string(forKey: SettingsKeys.cliWorkingDirectory) ?? "").trimmingCharacters(in: .whitespaces)
        if dir.isEmpty { return DefaultPaths.resolvedCLIDirectory() }
        return URL(fileURLWithPath: (dir as NSString).expandingTildeInPath)
    }
}
