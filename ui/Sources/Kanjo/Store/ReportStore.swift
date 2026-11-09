import Foundation
import SwiftUI
import KanjoCore
import AppKit

@MainActor
final class ReportStore: ObservableObject {
    static let shared = ReportStore()

    @Published private(set) var needsCommandLineTools = false
    @Published private(set) var report: UsageReport?
    @Published private(set) var knownPlans: [String: [KnownPlan]]?
    @Published private(set) var error: String?
    @Published private(set) var isLoading = false
    @Published private(set) var loadingStartedAt: Date?
    @Published private(set) var lastRefresh: Date?
    @Published private(set) var sourceDescription = ""

    /// `--data` / `KANJO_DATA` 指定的文件，优先于设置。
    let dataOverride: URL? = DefaultPaths.dataOverride()

    private var timer: Timer?
    private var scheduler = RefreshScheduler()
    private var logWatcher: LogWatcher?
    private var scheduledTask: Task<Void, Never>?
    private var generation = 0
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
            SettingsKeys.refreshMinutes: 30,
            SettingsKeys.showAmountInMenuBar: true,
        ])
        var storedMinutes = defaults.integer(forKey: SettingsKeys.refreshMinutes)
        storedMinutes = RefreshScheduler.migrateFallbackMinutes(storedMinutes)
        if storedMinutes != defaults.integer(forKey: SettingsKeys.refreshMinutes) {
            defaults.set(storedMinutes, forKey: SettingsKeys.refreshMinutes)
        }
        scheduler.fallbackMinutes = storedMinutes

        setupNotifications()
        Task { await checkPython() }
        Task { await loadKnownPlans() }
        refresh()
        restartTimer()
        setupWatcher()
    }

    private func setupNotifications() {
        let wsCenter = NSWorkspace.shared.notificationCenter
        wsCenter.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: nil) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.onWillSleep()
            }
        }
        wsCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: nil) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.onDidWake()
            }
        }
        NotificationCenter.default.addObserver(forName: .NSProcessInfoPowerStateDidChange, object: nil, queue: nil) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.onPowerStateDidChange()
            }
        }
    }

    private func onWillSleep() {
        scheduledTask?.cancel()
        scheduledTask = nil
        scheduler.onSleep()
    }

    private func onDidWake() {
        let action = scheduler.onWake()
        handleSchedulerAction(action)
    }

    private func onPowerStateDidChange() {
        let isLowPower = ProcessInfo.processInfo.isLowPowerModeEnabled
        let action = scheduler.onLowPowerModeChanged(enabled: isLowPower)
        handleSchedulerAction(action)
    }

    func setupWatcher() {
        guard dataOverride == nil else {
            logWatcher?.stop()
            logWatcher = nil
            return
        }
        let kind = SourceKind(rawValue: defaults.string(forKey: SettingsKeys.sourceKind) ?? "") ?? .file
        guard kind == .cli else {
            logWatcher?.stop()
            logWatcher = nil
            return
        }
        let cli = CLILaunch.command(defaults: defaults)
        let cwd = CLILaunch.workingDirectory(defaults: defaults)
        let cliSource = CLIDataSource(command: cli, workingDirectory: cwd)
        Task { [weak self] in
            do {
                let pathsMap = try await cliSource.loadPaths(qualityOfService: .background)
                let paths = Array(Set(pathsMap.values.flatMap { $0 }))
                guard !Task.isCancelled else { return }
                await MainActor.run {
                    self?.startLogWatcher(paths: paths)
                }
            } catch {
                // CLI paths unavailable; safety fallback timer will handle refreshes
            }
        }
    }

    private func startLogWatcher(paths: [String]) {
        logWatcher?.stop()
        logWatcher = LogWatcher(paths: paths) { [weak self] in
            Task { @MainActor [weak self] in
                self?.handleFileEvent()
            }
        }
    }

    private func handleFileEvent() {
        let action = scheduler.onFileEvent()
        handleSchedulerAction(action)
    }

    private func handleSchedulerAction(_ action: RefreshScheduler.Action) {
        switch action {
        case .none:
            break
        case .refreshNow:
            scheduledTask?.cancel()
            scheduledTask = nil
            refresh(qualityOfService: .background)
        case .scheduleRefresh(let delay):
            scheduledTask?.cancel()
            scheduledTask = Task { [weak self] in
                do {
                    try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
                } catch { return }
                guard !Task.isCancelled else { return }
                self?.refresh(qualityOfService: .background)
            }
        }
    }

    func onPanelOpened() {
        if scheduler.shouldRefreshOnOpen() {
            refresh(qualityOfService: .background)
        }
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

    func refresh(qualityOfService: QualityOfService = .userInitiated) {
        scheduledTask?.cancel()
        scheduledTask = nil
        scheduler.onRefreshStarted()
        generation += 1
        let gen = generation
        let (source, desc) = makeSource()
        sourceDescription = desc
        isLoading = true
        if loadingStartedAt == nil {
            loadingStartedAt = Date()
        }
        Task {
            do {
                let r: UsageReport
                if let cliSource = source as? CLIDataSource {
                    r = try await cliSource.load(qualityOfService: qualityOfService)
                } else {
                    r = try await source.load()
                }
                guard gen == generation else { return }
                report = r
                error = nil
                CloudSyncStore.shared.reportDidRefresh(r)
            } catch {
                guard gen == generation else { return }
                if source is CLIDataSource { await checkPython() }
                guard gen == generation else { return }
                // 刷新失败时保留上一份报告，面板顶部显示错误。
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            guard gen == generation else { return }
            lastRefresh = Date()
            isLoading = false
            loadingStartedAt = nil
            let followUpAction = scheduler.onRefreshFinished()
            handleSchedulerAction(followUpAction)
        }
    }

    func restartTimer() {
        timer?.invalidate()
        timer = nil
        var minutes = defaults.integer(forKey: SettingsKeys.refreshMinutes)
        minutes = RefreshScheduler.migrateFallbackMinutes(minutes)
        if minutes != defaults.integer(forKey: SettingsKeys.refreshMinutes) {
            defaults.set(minutes, forKey: SettingsKeys.refreshMinutes)
        }
        scheduler.fallbackMinutes = minutes
        guard minutes > 0 else { return }
        timer = Timer.scheduledTimer(withTimeInterval: TimeInterval(minutes * 60), repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self = self else { return }
                let action = self.scheduler.onFallbackTimerFired()
                self.handleSchedulerAction(action)
            }
        }
    }

    /// 设置改动后调用：重建数据源、重排定时器。
    func applySettings() {
        restartTimer()
        setupWatcher()
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
