import XCTest
@testable import KanjoCore

final class WatcherPathsStateTests: KanjoTestCase {
    private let t0 = Date(timeIntervalSince1970: 1_800_000_000)

    /// 启动时 `paths` 失败：下一次成功刷新后要重新获取并建立监听。
    func testFailedFetchIsRetriedAfterNextLiveReport() {
        var state = WatcherPathsState()
        XCTAssertTrue(state.begin(force: true, now: t0))
        XCTAssertFalse(state.finish(paths: nil, now: t0))
        XCTAssertTrue(state.begin(force: false, now: t0.addingTimeInterval(5)))
        XCTAssertTrue(state.finish(paths: ["/tmp/a"], now: t0.addingTimeInterval(6)))
    }

    /// 成功后短时间内不重复获取；过了间隔再取，新出现的目录会触发重建监听。
    func testNewAgentFolderPickedUpAfterInterval() {
        var state = WatcherPathsState()
        XCTAssertTrue(state.begin(force: true, now: t0))
        XCTAssertTrue(state.finish(paths: ["/tmp/a"], now: t0))
        XCTAssertFalse(state.begin(force: false, now: t0.addingTimeInterval(60)))
        let later = t0.addingTimeInterval(WatcherPathsState.refetchInterval)
        XCTAssertTrue(state.begin(force: false, now: later))
        XCTAssertFalse(state.begin(force: false, now: later), "no overlapping fetches")
        XCTAssertTrue(state.finish(paths: ["/tmp/a", "/tmp/b"], now: later))
        XCTAssertTrue(state.begin(force: false, now: later.addingTimeInterval(WatcherPathsState.refetchInterval)))
        XCTAssertFalse(state.finish(paths: ["/tmp/b", "/tmp/a"], now: later), "same set, no restart")
    }
}
