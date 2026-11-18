import Foundation

public struct ReportLoadState: Equatable {
    public var report: UsageReport?
    public var isStaleReport: Bool
    public var staleReportGeneratedAt: String?
    public var error: String?
    public var isLoading: Bool
    public var loadingStartedAt: Date?
    public var lastRefresh: Date?
    public var sourceDescription: String

    public init(
        report: UsageReport? = nil,
        isStaleReport: Bool = false,
        staleReportGeneratedAt: String? = nil,
        error: String? = nil,
        isLoading: Bool = false,
        loadingStartedAt: Date? = nil,
        lastRefresh: Date? = nil,
        sourceDescription: String = ""
    ) {
        self.report = report
        self.isStaleReport = isStaleReport
        self.staleReportGeneratedAt = staleReportGeneratedAt
        self.error = error
        self.isLoading = isLoading
        self.loadingStartedAt = loadingStartedAt
        self.lastRefresh = lastRefresh
        self.sourceDescription = sourceDescription
    }
}

/// Coordinates initial cached-export loading and live refreshes for `ReportStore`.
@MainActor
public final class ReportLoader {
    public typealias SourceDescriptor = (source: any UsageDataSource, description: String, isCLI: Bool)

    public private(set) var state = ReportLoadState() {
        didSet { onStateChange?(state) }
    }
    public var scheduler: RefreshScheduler
    public var onStateChange: ((ReportLoadState) -> Void)?
    public var onLiveReport: (UsageReport) -> Void
    public var onCLIFailure: () async -> Void
    public var onFollowUpAction: (RefreshScheduler.Action) -> Void

    private var generation = 0
    private var hasFinishedLiveRefresh = false
    private var hasStartedInitialLoad = false
    private var cacheTask: Task<Void, Never>?
    private var refreshTask: Task<Void, Never>?
    /// 刷新进行中又请求了静默刷新（例如刚写完配置）：当前这次可能读到旧数据，结束后再静默刷新一次。
    private var refreshAfterCurrent = false

    private let makeSource: @MainActor () -> SourceDescriptor
    private let loadCachedReport: (@Sendable () -> UsageReport?)?

    nonisolated public static func shouldUseLastExportCache(
        sourceKind: SourceKind,
        dataOverride: URL?,
        isSnapshotMode: Bool
    ) -> Bool {
        sourceKind == .cli && dataOverride == nil && !isSnapshotMode
    }

    public init(
        scheduler: RefreshScheduler = RefreshScheduler(),
        makeSource: @escaping @MainActor () -> SourceDescriptor,
        loadCachedReport: (@Sendable () -> UsageReport?)? = nil,
        onLiveReport: @escaping (UsageReport) -> Void = { _ in },
        onCLIFailure: @escaping () async -> Void = {},
        onFollowUpAction: @escaping (RefreshScheduler.Action) -> Void = { _ in }
    ) {
        self.scheduler = scheduler
        self.makeSource = makeSource
        self.loadCachedReport = loadCachedReport
        self.onLiveReport = onLiveReport
        self.onCLIFailure = onCLIFailure
        self.onFollowUpAction = onFollowUpAction
    }

    public func startInitialLoad(qualityOfService: QualityOfService = .userInitiated) {
        guard !hasStartedInitialLoad else { return }
        hasStartedInitialLoad = true
        refresh(qualityOfService: qualityOfService)
        guard let loadCachedReport else { return }
        let expectedGen = generation
        let detached = Task.detached(priority: .userInitiated) {
            loadCachedReport()
        }
        cacheTask = Task { [weak self] in
            let cached = await detached.value
            guard !Task.isCancelled else { return }
            self?.applyCachedReportIfNeeded(cached, expectedGeneration: expectedGen)
        }
    }

    public func refresh(qualityOfService: QualityOfService = .userInitiated, quiet: Bool = false) {
        if quiet && scheduler.isRefreshing {
            refreshAfterCurrent = true
            return
        }
        // 新开始的这次会读到最新数据，之前排着的补刷就不需要了；被它取代的旧任务也不会再去补刷。
        refreshAfterCurrent = false
        scheduler.onRefreshStarted()
        generation += 1
        let gen = generation
        let descriptor = makeSource()
        
        var starting = state
        starting.sourceDescription = descriptor.description
        if !quiet {
            starting.isLoading = true
            if starting.loadingStartedAt == nil {
                starting.loadingStartedAt = Date()
            }
        }
        state = starting
        
        refreshTask = Task { [weak self] in
            guard let self else { return }
            do {
                let loaded: UsageReport
                #if os(macOS)
                if let cliSource = descriptor.source as? CLIDataSource {
                    loaded = try await cliSource.load(qualityOfService: qualityOfService)
                } else {
                    loaded = try await descriptor.source.load()
                }
                #else
                loaded = try await descriptor.source.load()
                #endif
                guard gen == self.generation else { return }
                self.hasFinishedLiveRefresh = true
                var updated = self.state
                updated.report = loaded
                updated.isStaleReport = false
                updated.staleReportGeneratedAt = nil
                updated.error = nil
                if !quiet {
                    updated.isLoading = false
                    updated.loadingStartedAt = nil
                }
                self.state = updated
                self.onLiveReport(loaded)
            } catch {
                guard gen == self.generation else { return }
                if descriptor.isCLI {
                    await self.onCLIFailure()
                }
                guard gen == self.generation else { return }
                self.hasFinishedLiveRefresh = true
                var updated = self.state
                updated.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                if !quiet {
                    updated.isLoading = false
                    updated.loadingStartedAt = nil
                }
                self.state = updated
            }
            guard gen == self.generation else { return }
            var finished = self.state
            finished.lastRefresh = Date()
            self.state = finished
            let followUpAction = self.scheduler.onRefreshFinished()
            self.onFollowUpAction(followUpAction)
            if self.refreshAfterCurrent, !self.scheduler.isRefreshing {
                self.refresh(qualityOfService: qualityOfService, quiet: true)
            }
        }
    }

    private func applyCachedReportIfNeeded(_ cached: UsageReport?, expectedGeneration: Int) {
        guard let cached,
              state.report == nil,
              generation == expectedGeneration,
              !hasFinishedLiveRefresh else { return }
        var updated = state
        updated.report = cached
        updated.isStaleReport = true
        updated.staleReportGeneratedAt = cached.generatedAt
        state = updated
    }

    public func waitForInitialCache() async {
        await cacheTask?.value
    }

    public func waitForRefresh() async {
        await refreshTask?.value
    }
}
