import Foundation
import SwiftUI
import KanjoCore
import AppKit

@MainActor
final class ReportStore: ObservableObject {
    static let shared = ReportStore()

    @Published private(set) var needsCommandLineTools = false
    @Published private(set) var report: UsageReport?
    @Published private(set) var isStaleReport = false
    @Published private(set) var staleReportGeneratedAt: String?
    @Published private(set) var knownPlans: [String: [KnownPlan]]?
    @Published private(set) var error: String?
    @Published private(set) var isLoading = false
    @Published private(set) var loadingStartedAt: Date?
    @Published private(set) var lastRefresh: Date?
    @Published private(set) var sourceDescription = ""

    /// `--data` / `KANJO_DATA` 指定的文件，优先于设置。
    let dataOverride: URL?

    private var timer: Timer?
    private var busyCheckTimer: Timer?
    private let loader: ReportLoader
    private var logWatcher: LogWatcher?
    private var scheduledTask: Task<Void, Never>?
    private let defaults: UserDefaults

    init(defaults: UserDefaults = AppDefaults.store) {
        self.defaults = defaults
        let override = DefaultPaths.dataOverride()
        self.dataOverride = override

        // 默认直接跑 CLI：优先内置 CLI，其次源码和安装目录。
        let defaultKind: SourceKind = DefaultPaths.cliDirectoryExists ? .cli : .file
        defaults.register(defaults: [
            SettingsKeys.sourceKind: defaultKind.rawValue,
            SettingsKeys.filePath: "",
            SettingsKeys.cliCommand: CLIDataSource.defaultCommand,
            SettingsKeys.cliWorkingDirectory: "",
            SettingsKeys.refreshMinutes: 30,
            SettingsKeys.backgroundRefreshSeconds: 60,
            SettingsKeys.showAmountInMenuBar: true,
        ])
        var storedMinutes = defaults.integer(forKey: SettingsKeys.refreshMinutes)
        storedMinutes = RefreshScheduler.migrateFallbackMinutes(storedMinutes)
        if storedMinutes != defaults.integer(forKey: SettingsKeys.refreshMinutes) {
            defaults.set(storedMinutes, forKey: SettingsKeys.refreshMinutes)
        }
        let backgroundSeconds = defaults.integer(forKey: SettingsKeys.backgroundRefreshSeconds)
        let backgroundInterval = TimeInterval(BackgroundRefreshInterval.resolve(backgroundSeconds).rawValue)
        
        let scheduler = RefreshScheduler(
            fallbackMinutes: storedMinutes,
            backgroundInterval: backgroundInterval
        )

        let initialKind = SourceKind(rawValue: defaults.string(forKey: SettingsKeys.sourceKind) ?? "") ?? .file
        let shouldLoadCache = ReportLoader.shouldUseLastExportCache(
            sourceKind: initialKind,
            dataOverride: override,
            isSnapshotMode: AppDefaults.isSnapshotMode()
        )
        let cacheLoader = Self.makeCacheLoader(shouldLoad: shouldLoadCache)
        self.loader = ReportLoader(
            scheduler: scheduler,
            makeSource: {
                ReportStore.makeSourceDescriptor(defaults: defaults, dataOverride: override)
            },
            loadCachedReport: cacheLoader
        )
        loader.onStateChange = { [weak self] state in
            self?.apply(state)
        }
        loader.onLiveReport = { r in
            CloudSyncStore.shared.reportDidRefresh(r)
            PublishStore.shared.reportDidRefresh(r)
            FamilyReportStore.shared.reportDidRefresh(r)
        }
        loader.onCLIFailure = { [weak self] in
            await self?.checkPython()
        }
        loader.onFollowUpAction = { [weak self] action in
            self?.handleSchedulerAction(action)
        }

        setupNotifications()
        Task { await checkPython() }
        Task { await loadKnownPlans() }
        loader.startInitialLoad()
        restartTimer()
        setupWatcher()
    }

    private func apply(_ state: ReportLoadState) {
        report = state.report
        isStaleReport = state.isStaleReport
        staleReportGeneratedAt = state.staleReportGeneratedAt
        error = state.error
        isLoading = state.isLoading
        loadingStartedAt = state.loadingStartedAt
        lastRefresh = state.lastRefresh
        sourceDescription = state.sourceDescription
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
        NotificationCenter.default.addObserver(forName: ProcessInfo.thermalStateDidChangeNotification, object: nil, queue: nil) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.checkBusy()
            }
        }
    }

    private func onWillSleep() {
        scheduledTask?.cancel()
        scheduledTask = nil
        loader.scheduler.onSleep()
    }

    private func onDidWake() {
        let action = loader.scheduler.onWake()
        handleSchedulerAction(action)
    }

    private func onPowerStateDidChange() {
        let isLowPower = ProcessInfo.processInfo.isLowPowerModeEnabled
        let action = loader.scheduler.onLowPowerModeChanged(enabled: isLowPower)
        handleSchedulerAction(action)
        checkBusy()
    }

    private func getLoadAverage() -> Double {
        var load = [Double](repeating: 0.0, count: 3)
        let count = getloadavg(&load, 3)
        return count >= 1 ? load[0] : 0.0
    }

    private func checkBusy() {
        let load = getLoadAverage()
        let thermal = ProcessInfo.processInfo.thermalState
        let cores = ProcessInfo.processInfo.activeProcessorCount
        let isBusy = SystemBusy.isBusy(thermalState: thermal, loadAverage: load, cores: cores)

        let action = loader.scheduler.onSystemBusyChanged(busy: isBusy)
        handleSchedulerAction(action)

        if isBusy {
            if busyCheckTimer == nil {
                busyCheckTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
                    Task { @MainActor [weak self] in
                        self?.checkBusy()
                    }
                }
            }
        } else {
            busyCheckTimer?.invalidate()
            busyCheckTimer = nil
        }
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
        let action = loader.scheduler.onFileEvent()
        handleSchedulerAction(action)
    }

    private func handleSchedulerAction(_ action: RefreshScheduler.Action) {
        switch action {
        case .none:
            break
        case .refreshNow:
            scheduledTask?.cancel()
            scheduledTask = nil
            refresh(quiet: true, qualityOfService: .background)
        case .scheduleRefresh(let delay):
            scheduledTask?.cancel()
            scheduledTask = Task { [weak self] in
                do {
                    try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
                } catch { return }
                guard !Task.isCancelled else { return }
                self?.refresh(quiet: true, qualityOfService: .background)
            }
        }
    }

    func onPanelOpened() {
        let shouldRefresh = loader.scheduler.shouldRefreshOnOpen(isStaleReport: isStaleReport)
        let action = loader.scheduler.onPanelVisibilityChanged(visible: true)
        if shouldRefresh {
            refresh(quiet: false, qualityOfService: .userInitiated)
        } else if action == .refreshNow {
            refresh(quiet: true, qualityOfService: .background)
        } else {
            handleSchedulerAction(action)
        }
    }

    func onPanelClosed() {
        let action = loader.scheduler.onPanelVisibilityChanged(visible: false)
        handleSchedulerAction(action)
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
        let d = Self.makeSourceDescriptor(defaults: defaults, dataOverride: dataOverride)
        return (d.source, d.description)
    }

    nonisolated private static func makeCacheLoader(shouldLoad: Bool) -> (@Sendable () -> UsageReport?)? {
        guard shouldLoad else { return nil }
        let cache = LastExportCache()
        return { cache.load() }
    }

    private static func makeSourceDescriptor(
        defaults: UserDefaults,
        dataOverride: URL?
    ) -> ReportLoader.SourceDescriptor {
        if let o = dataOverride {
            return (FileDataSource(url: o), "File (--data): \(o.path)", false)
        }
        let kind = SourceKind(rawValue: defaults.string(forKey: SettingsKeys.sourceKind) ?? "") ?? .file
        switch kind {
        case .file:
            let raw = (defaults.string(forKey: SettingsKeys.filePath) ?? "").trimmingCharacters(in: .whitespaces)
            let url = raw.isEmpty ? DefaultPaths.sampleFixture
                                  : URL(fileURLWithPath: (raw as NSString).expandingTildeInPath)
            return (FileDataSource(url: url), "File: \(url.path)", false)
        case .cli:
            let cmd = CLILaunch.command(defaults: defaults)
            // 工作目录留空 = 内置 CLI、源码 cli/，其次 install.sh 装的位置；
            // 都没有就继承进程的当前目录。磁盘页用同一套命令和工作目录。
            let url = CLILaunch.workingDirectory(defaults: defaults)
            return (CLIDataSource(command: cmd, workingDirectory: url),
                    "Command: \(cmd)" + (url.map { " (in \($0.path))" } ?? ""),
                    true)
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

    func setFamilySince(_ since: String?) async throws {
        guard canEditSubscriptions else {
            throw DataSourceError.launchFailed("Editing needs the CLI data source")
        }
        let source = ConfigDataSource(cliCommand: CLILaunch.command(defaults: defaults),
                                      workingDirectory: CLILaunch.workingDirectory(defaults: defaults))
        do { try await source.setFamilySince(since) }
        catch { await checkPython(); throw error }
        refresh()
    }

    func setFamilyAgents(_ agents: String?) async throws {
        guard canEditSubscriptions else {
            throw DataSourceError.launchFailed("Editing needs the CLI data source")
        }
        let source = ConfigDataSource(cliCommand: CLILaunch.command(defaults: defaults),
                                      workingDirectory: CLILaunch.workingDirectory(defaults: defaults))
        do { try await source.setFamilyAgents(agents) }
        catch { await checkPython(); throw error }
        refresh()
    }

    func setAntigravityAccountPlan(email: String, plan: String?) async throws {
        guard canEditSubscriptions else {
            throw DataSourceError.launchFailed("Editing needs the CLI data source")
        }
        let source = ConfigDataSource(cliCommand: CLILaunch.command(defaults: defaults),
                                      workingDirectory: CLILaunch.workingDirectory(defaults: defaults))
        do { try await source.setAntigravityAccountPlan(email: email, plan: plan) }
        catch { await checkPython(); throw error }
        refresh()
    }

    func refresh(quiet: Bool = false, qualityOfService: QualityOfService = .userInitiated) {
        scheduledTask?.cancel()
        scheduledTask = nil
        loader.refresh(qualityOfService: qualityOfService, quiet: quiet)
    }

    func restartTimer() {
        timer?.invalidate()
        timer = nil
        var minutes = defaults.integer(forKey: SettingsKeys.refreshMinutes)
        minutes = RefreshScheduler.migrateFallbackMinutes(minutes)
        if minutes != defaults.integer(forKey: SettingsKeys.refreshMinutes) {
            defaults.set(minutes, forKey: SettingsKeys.refreshMinutes)
        }
        loader.scheduler.fallbackMinutes = minutes
        guard minutes > 0 else { return }
        timer = Timer.scheduledTimer(withTimeInterval: TimeInterval(minutes * 60), repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self = self else { return }
                let action = self.loader.scheduler.onFallbackTimerFired()
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

    func applyBackgroundInterval(_ seconds: Int) {
        let interval = TimeInterval(BackgroundRefreshInterval.resolve(seconds).rawValue)
        loader.scheduler.backgroundInterval = interval
        let action = loader.scheduler.onBackgroundIntervalChanged(interval)
        handleSchedulerAction(action)
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
