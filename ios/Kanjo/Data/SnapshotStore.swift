import CloudKit
import Foundation
import KanjoCore
import Observation
import os
#if canImport(WidgetKit)
import WidgetKit
#endif

@MainActor
@Observable
final class SnapshotStore {
    enum State {
        case loading
        case empty
        case failed(String)
        case loaded(UsageReport)
    }

    private(set) var state: State = .loading
    private(set) var deviceName: String?
    private(set) var accountCode: String?
    private(set) var isSampleMode: Bool = false
    private(set) var refreshFailed = false
    private let source: SnapshotSource

    init(source: SnapshotSource? = nil) {
        self.source = source ?? Self.defaultSource()
    }

    static func defaultSource(arguments: [String] = CommandLine.arguments) -> SnapshotSource {
        if arguments.contains("-useSampleSnapshot") {
            SyncLog.sync.info("fallback to sample: -useSampleSnapshot argument")
            return BundledSampleSnapshotSource()
        }
        return CloudKitSnapshotSource()
    }

    func loadSample() async {
        isSampleMode = true
        refreshFailed = false
        state = .loading
        do {
            let sampleSource = BundledSampleSnapshotSource()
            if let report = try await sampleSource.load() {
                deviceName = "Sample Mac"
                accountCode = nil
                state = .loaded(report)
                SyncLog.sync.info("sample snapshot loaded")
            } else {
                state = .failed("Sample data not found")
            }
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    func exitSampleMode() async {
        isSampleMode = false
        await load()
    }

    func load() async {
        isSampleMode = false
        SyncLog.sync.info("load started: source \(String(describing: type(of: self.source)), privacy: .public)")
        await load(preserveState: false)
    }

    func refresh() async {
        await load(preserveState: true)
    }

    private func load(preserveState: Bool) async {
        if isSampleMode {
            if preserveState {
                await loadSample()
                return
            }
            isSampleMode = false
        }
        if !preserveState {
            state = .loading
            refreshFailed = false
        }
        do {
            let report = try await source.load()
            if preserveState, case .loaded(let previous) = state {
                guard let report else {
                    refreshFailed = true
                    return
                }
                if let previousDate = ReportDates.parseTimestamp(previous.generatedAt),
                   let newDate = ReportDates.parseTimestamp(report.generatedAt),
                   newDate < previousDate {
                    refreshFailed = true
                    return
                }
            }
            refreshFailed = false
            deviceName = source.lastDeviceName
            accountCode = source.lastAccountCode
            if let report {
                state = .loaded(report)
                SyncLog.sync.info("load finished: snapshot decoded")
                if !isSampleMode && !(source is BundledSampleSnapshotSource) {
                    _ = try? WidgetSnapshotCache.write(report: report, deviceName: deviceName)
                    #if canImport(WidgetKit)
                    WidgetCenter.shared.reloadAllTimelines()
                    #endif
                }
            } else {
                state = .empty
                SyncLog.sync.info("load finished: no snapshot, showing empty state")
            }
        } catch {
            if let ckError = error as? CKError {
                SyncLog.sync.error("load failed: CKError code \(ckError.code.rawValue, privacy: .public), description \(ckError.localizedDescription, privacy: .private)")
            } else {
                SyncLog.sync.error("load failed: \(String(describing: type(of: error)), privacy: .public), description \(error.localizedDescription, privacy: .private)")
            }
            if preserveState, case .loaded = state {
                refreshFailed = true
            } else {
                state = .failed(error.localizedDescription)
            }
        }
    }
}
