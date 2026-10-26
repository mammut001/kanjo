import Foundation
import SwiftUI
import KanjoCore

@MainActor
final class ReportStore: ObservableObject {
    static let shared = ReportStore()

    @Published private(set) var needsCommandLineTools = false
    @Published private(set) var report: UsageReport?
    @Published private(set) var knownPlans: [String: [KnownPlan]]?
    @Published private(set) var error: String?
    @Published private(set) var isLoading = false
    @Published private(set) var lastRefresh: Date?
    @Published private(set) var sourceDescription = ""

    /// `--data` / `KANJO_DATA` 指定的文件，优先于设置。
    let dataOverride: URL? = DefaultPaths.dataOverride()

    private var timer: Timer?
    private var generation = 0
    private var didScheduleDiskPrefetch = false
    private let defaults: UserDefaults

    init(defaults: UserDefaults = AppDefaults.store) {
        self.defaults = defaults
        // 默认直接跑 CLI：优先内置 CLI，其次源码和安装目录。
        let defaultKind: SourceKind = DefaultPaths.cliDirectoryExists ? .cli : .file
        defaults.register(defaults: [
            SettingsKeys.sourceKind: defaultKind.rawValue,
            SettingsKeys.filePath: "",
            SettingsKeys.cliCommand: CLIDataSource.defaultCommand,
            SettingsKeys.cliWorkingDirectory: "",
            SettingsKeys.refreshMinutes: 5,
            SettingsKeys.showAmountInMenuBar: true,
        ])
        Task { await checkPython() }
        Task { await loadKnownPlans() }
        refresh()
        restartTimer()
    }

    func checkPython() async {
        needsCommandLineTools = await PythonCheck.check()
    }

    func installCommandLineTools() {
        Task {
            do { try await PythonCheck.installCommandLineTools() }
            catch { self.error = error.localizedDescription }
        }
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
            // 工作目录留空 = 内置 CLI、源码 cli/，其次 install.sh 装的位置；
            // 都没有就继承进程的当前目录。磁盘页用同一套命令和工作目录。
            let url = CLILaunch.workingDirectory(defaults: defaults)
            return (CLIDataSource(command: cmd, workingDirectory: url),
                    "Command: \(cmd)" + (url.map { " (in \($0.path))" } ?? ""))
        }
    }

    var canEditSubscriptions: Bool {
        dataOverride == nil && defaults.string(forKey: SettingsKeys.sourceKind) == SourceKind.cli.rawValue
    }

    func loadKnownPlans() async {
        guard knownPlans == nil else { return }
        let source = ConfigDataSource(cliCommand: CLILaunch.command(defaults: defaults),
                                      workingDirectory: CLILaunch.workingDirectory(defaults: defaults))
        do {
            let plans = try await source.fetchKnownPlans()
            self.knownPlans = plans
        } catch {
            self.knownPlans = KnownPlan.fallbackPlans
        }
    }

    func setAnchorDay(agent: String, day: Int?) async throws {
        guard canEditSubscriptions else {
            throw DataSourceError.launchFailed("Editing needs the CLI data source")
        }
        let source = ConfigDataSource(cliCommand: CLILaunch.command(defaults: defaults),
                                      workingDirectory: CLILaunch.workingDirectory(defaults: defaults))
        do { try await source.setAnchorDay(agent: agent, day: day) }
        catch { await checkPython(); throw error }
        refresh()
    }

    func setSubscription(agent: String, plan: String?, monthlyPriceUsd: Double?, anchorDay: Int?) async throws {
        guard canEditSubscriptions else {
            throw DataSourceError.launchFailed("Editing needs the CLI data source")
        }
        let source = ConfigDataSource(cliCommand: CLILaunch.command(defaults: defaults),
                                      workingDirectory: CLILaunch.workingDirectory(defaults: defaults))
        do { try await source.setSubscription(agent: agent, plan: plan, monthlyPriceUsd: monthlyPriceUsd, anchorDay: anchorDay) }
        catch { await checkPython(); throw error }
        refresh()
    }

    func removeSubscription(agent: String) async throws {
        guard canEditSubscriptions else {
            throw DataSourceError.launchFailed("Editing needs the CLI data source")
        }
        let source = ConfigDataSource(cliCommand: CLILaunch.command(defaults: defaults),
                                      workingDirectory: CLILaunch.workingDirectory(defaults: defaults))
        do { try await source.removeSubscription(agent: agent) }
        catch { await checkPython(); throw error }
        refresh()
    }

    func setWeeklyReset(agent: String, reset: String?) async throws {
        guard canEditSubscriptions else {
            throw DataSourceError.launchFailed("Editing needs the CLI data source")
        }
        let source = ConfigDataSource(cliCommand: CLILaunch.command(defaults: defaults),
                                      workingDirectory: CLILaunch.workingDirectory(defaults: defaults))
        do { try await source.setWeeklyReset(agent: agent, reset: reset) }
        catch { await checkPython(); throw error }
        refresh()
    }

    func refresh() {
        // 先初始化磁盘缓存，并暂停尚未开始的预取，避免与用量导出同时启动。
        DiskStore.shared.cancelPrefetch()
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
                if source is CLIDataSource { await checkPython() }
                guard gen == generation else { return }
                // 刷新失败时保留上一份报告，面板顶部显示错误。
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            lastRefresh = Date()
            isLoading = false
            DiskStore.shared.schedulePrefetch(delay: didScheduleDiskPrefetch ? 0 : 15)
            didScheduleDiskPrefetch = true
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

    /// 设置改动后调用：重建数据源、重排定时器，用量刷新完成后预取磁盘报告。
    func applySettings() {
        restartTimer()
        DiskStore.shared.applySettings()
        Task { await loadKnownPlans() }
        refresh()
    }
}

/// 设置里的 CLI 命令和工作目录。用量导出和磁盘报告共用。
enum CLILaunch {
    static func command(defaults: UserDefaults = AppDefaults.store) -> String {
        let cmd = (defaults.string(forKey: SettingsKeys.cliCommand) ?? "").trimmingCharacters(in: .whitespaces)
        return cmd.isEmpty ? CLIDataSource.defaultCommand : cmd
    }

    static func workingDirectory(defaults: UserDefaults = AppDefaults.store) -> URL? {
        let dir = (defaults.string(forKey: SettingsKeys.cliWorkingDirectory) ?? "").trimmingCharacters(in: .whitespaces)
        if dir.isEmpty { return DefaultPaths.resolvedCLIDirectory() }
        return URL(fileURLWithPath: (dir as NSString).expandingTildeInPath)
    }
}
