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
    private let source: SnapshotSource

    init(source: SnapshotSource = BundledSampleSnapshotSource()) {
        self.source = source
    }

    func load() async {
        state = .loading
        do {
            if let report = try await source.load() {
                state = .loaded(report)
            } else {
                state = .empty
            }
        } catch {
            state = .failed(error.localizedDescription)
        }
    }
}
