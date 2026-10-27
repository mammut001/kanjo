import Foundation
import KanjoCore
import Observation

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
    private let source: SnapshotSource

    init(source: SnapshotSource? = nil) {
        self.source = source ?? Self.defaultSource()
    }

    static func defaultSource(arguments: [String] = CommandLine.arguments) -> SnapshotSource {
        if arguments.contains("-useSampleSnapshot") {
            return BundledSampleSnapshotSource()
        }
        return CloudKitSnapshotSource()
    }

    func load() async {
        await load(preserveState: false)
    }

    func refresh() async {
        await load(preserveState: true)
    }

    private func load(preserveState: Bool) async {
        if !preserveState {
            state = .loading
        }
        do {
            let report = try await source.load()
            deviceName = source.lastDeviceName
            if let report {
                state = .loaded(report)
            } else {
                state = .empty
            }
        } catch {
            state = .failed(error.localizedDescription)
        }
    }
}
