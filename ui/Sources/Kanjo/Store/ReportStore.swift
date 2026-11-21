import Foundation
import SwiftUI
import KanjoCore
import AppKit

@MainActor
final class ReportStore: ObservableObject {
    static let shared = ReportStore()

    @Published private(set) var needsCommandLineTools = false
    @Published private(set) var report: UsageReport?
    @Published private(set) var panelData: PanelData?
    private var panelGeneration: Int = 0
    @Published private(set) var isStaleReport = false
    @Published private(set) var staleReportGeneratedAt: String?
    @Published private(set) var knownPlans: [String: [KnownPlan]]?
    @Published private(set) var error: String?
    @Published private(set) var isLoading = false
    @Published private(set) var loadingStartedAt: Date?
    @Published private(set) var lastRefresh: Date?
    @Published private(set) var sourceDescription = ""
    /// Antigravity 账号 -> 已选但报告里还没体现的套餐 key（"" 表示无套餐）。
    @Published private(set) var pendingAntigravityAccountPlans: [String: String] = [:]
    /// 最近一次账号套餐写入失败的 CLI 错误信息。
    @Published private(set) var accountPlanError: String?

    /// `--data` / `KANJO_DATA` 指定的文件，优先于设置。
    let dataOverride: URL?

    private var timer: Timer?
    private var busyCheckTimer: Timer?
    private let loader: ReportLoader
    private var logWatcher: LogWatcher?
    private var scheduledTask: Task<Void, Never>?
    private let defaults: UserDefaults
    private var defaultsObserver: NSObjectProtocol?
    private var pendingReport: (report: UsageReport, isStale: Bool, staleAt: String?)?
    private var writeQueue = WriteQueue()
    private var writeQueueTask: Task<Void, Never>?
    private var writingAccountEmail: String?

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
        
        defaultsObserver = NotificationCenter.default.addObserver(forName: UserDefaults.didChangeNotification, object: defaults, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.handleDefaultsChange() }
        }

        Task { await checkPython() }
        Task { await loadKnownPlans() }
        loader.startInitialLoad()
        restartTimer()
        setupWatcher()
    }

    deinit {
        timer?.invalidate()
        busyCheckTimer?.invalidate()
        logWatcher?.stop()
        if let observer = defaultsObserver {
            NotificationCenter.default.removeObserver(observer)
        }
    }

    private func handleDefaultsChange() {
        let newRange = defaults.string(forKey: SettingsKeys.timeRange) ?? TimeRange.all.rawValue
        if let currentRange = panelData?.rangeSpec.range.rawValue, currentRange == newRange {
            return
        }
        prepare(rangeRaw: newRange)
    }

    func apply(_ state: ReportLoadState) {
        error = state.error
        isLoading = state.isLoading
        loadingStartedAt = state.loadingStartedAt
        lastRefresh = state.lastRefresh
        sourceDescription = state.sourceDescription
        
        if state.report?.generatedAt != report?.generatedAt || (state.report == nil) != (report == nil) {
            let gen = panelGeneration + 1
            panelGeneration = gen
            
            if let newReport = state.report {
                pendingReport = (newReport, state.isStaleReport, state.staleReportGeneratedAt)
                let range = defaults.string(forKey: SettingsKeys.timeRange) ?? TimeRange.all.rawValue
                Task.detached(priority: .userInitiated) {
                    let now = Date()
                    let data = PanelData.compute(report: newReport, rangeRaw: range, now: now)
                    await MainActor.run {
                        guard self.panelGeneration == gen else { return }
                        self.report = newReport
                        self.reconcilePendingAccountPlans(with: newReport)
                        self.isStaleReport = state.isStaleReport
                        self.staleReportGeneratedAt = state.staleReportGeneratedAt
                        self.panelData = data
                        self.pendingReport = nil
                    }
                }
            } else {
                self.report = nil
                self.isStaleReport = false
                self.staleReportGeneratedAt = nil
                self.panelData = nil
                self.pendingReport = nil
            }
        }
    }

    func prepare(rangeRaw: String) {
        let reportToCompute = pendingReport?.report ?? report
        guard let report = reportToCompute else { return }
        
        let gen = panelGeneration + 1
        panelGeneration = gen
        
        let stale = pendingReport?.isStale
        let staleAt = pendingReport?.staleAt
        
        Task.detached(priority: .userInitiated) {
            let now = Date()
            let data = PanelData.compute(report: report, rangeRaw: rangeRaw, now: now)
            await MainActor.run {
                guard self.panelGeneration == gen else { return }
                self.panelData = data
                if let stale = stale {
                    self.report = report
                    self.isStaleReport = stale
                    self.staleReportGeneratedAt = staleAt
                    self.pendingReport = nil
                }
            }
        }
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
        if isLowPower {
            // Same as sleep: the armed timer must not fire while Low Power is on.
            // The scheduler parks it in pendingWakeRefresh and resumes when power returns.
            scheduledTask?.cancel()
            scheduledTask = nil
        }
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
            checkBusy()
            startBackgroundRefreshIfIdle()
        case .scheduleRefresh(let delay):
            scheduledTask?.cancel()
            scheduledTask = Task { [weak self] in
                do {
                    try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
                } catch { return }
                guard let self = self, !Task.isCancelled else { return }
                self.checkBusy()
                self.startBackgroundRefreshIfIdle()
            }
        }
    }

    /// One quiet refresh, unless sleep, Low Power, or busy should hold it,
    /// or a nested busy check already started one.
    private func startBackgroundRefreshIfIdle() {
        if loader.scheduler.isSystemBusy || loader.scheduler.isLowPowerMode || loader.scheduler.isAsleep {
            scheduledTask?.cancel()
            scheduledTask = nil
            loader.scheduler.deferForBusy()
            return
        }
        if loader.scheduler.isRefreshing {
            return
        }
        scheduledTask?.cancel()
        scheduledTask = nil
        refresh(quiet: true, qualityOfService: .background)
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

    /// 立即记下选择（选择器和合计马上更新），再排队交给唯一的写入任务逐个写 overrides.json。
    /// `plan` 为 nil / "" / "none" 时写入显式的 "none"，免得 unset 后又回落到 attribution.toml 里的套餐。
    func setAntigravityAccountPlan(email: String, plan: String?) {
        guard canEditSubscriptions else { return }
        let key = AntigravityAggregation.normalizedPlanKey(plan)
        pendingAntigravityAccountPlans[email] = key
        accountPlanError = nil
        writeQueue.enqueue(WriteQueue.Write(email: email, plan: key.isEmpty ? "none" : key))
        startWriteQueueIfNeeded()
    }

    /// 同一时间只有一个写入任务：依次写完队列，队列空着满 1 秒才退出并静默刷新一次；
    /// 等待期间来的新选择会在下一轮循环里写掉。任务在主 actor 上，CLI 调用本身在后台线程跑。
    private func startWriteQueueIfNeeded() {
        guard writeQueueTask == nil else { return }
        writeQueueTask = Task { @MainActor [weak self] in
            while let self {
                let batch = self.writeQueue.dequeueAllAndCoalesce()
                if batch.isEmpty {
                    try? await Task.sleep(nanoseconds: 1_000_000_000)
                    guard self.writeQueue.isEmpty else { continue }
                    self.writeQueueTask = nil
                    self.loader.refresh(quiet: true)
                    return
                }
                let source = ConfigDataSource(cliCommand: CLILaunch.command(defaults: self.defaults),
                                              workingDirectory: CLILaunch.workingDirectory(defaults: self.defaults))
                for write in batch {
                    self.writingAccountEmail = write.email
                    do {
                        try await source.setAntigravityAccountPlan(email: write.email, plan: write.plan)
                    } catch {
                        await self.checkPython()
                        // 写失败就撤回这次选择（后面又排了新选择的话以新的为准）。
                        if !self.writeQueue.emails.contains(write.email),
                           self.pendingAntigravityAccountPlans[write.email]
                            == AntigravityAggregation.normalizedPlanKey(write.plan) {
                            self.pendingAntigravityAccountPlans.removeValue(forKey: write.email)
                        }
                        self.accountPlanError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                    }
                    self.writingAccountEmail = nil
                }
            }
        }
    }

    /// 报告已显示所选套餐的账号不再 pending；还在排队或正在写的账号先不动。
    private func reconcilePendingAccountPlans(with report: UsageReport) {
        guard !pendingAntigravityAccountPlans.isEmpty,
              let accounts = report.antigravityAccounts?.accounts else { return }
        var busy = writeQueue.emails
        if let writingAccountEmail { busy.insert(writingAccountEmail) }
        let remaining = AntigravityAggregation.remainingPending(pendingAntigravityAccountPlans,
                                                                report: accounts, busy: busy)
        if remaining != pendingAntigravityAccountPlans {
            pendingAntigravityAccountPlans = remaining
        }
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
