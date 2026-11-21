import XCTest
@testable import KanjoCore

final class DiskRefreshGateTests: KanjoTestCase {
    /// 离开设置但磁盘命令没变：进行中的扫描结果照常采用，排队的补跑也保留。
    func testUnchangedSettingsKeepInFlightScan() {
        var gate = DiskRefreshGate()
        let gen = gate.begin(sourceKey: "kanjo disk --json")
        gate.queue(rescan: true)
        gate.settingsApplied(sourceKey: "kanjo disk --json", isLoading: true)
        XCTAssertTrue(gate.accepts(gen))
        XCTAssertEqual(gate.takePending(), true)
    }

    /// 磁盘命令变了：旧结果丢弃，并用新数据源补跑一次。
    func testChangedSettingsDropResultAndQueueRerun() {
        var gate = DiskRefreshGate()
        let gen = gate.begin(sourceKey: "kanjo disk --json")
        gate.settingsApplied(sourceKey: "other disk --json", isLoading: true)
        XCTAssertFalse(gate.accepts(gen))
        XCTAssertEqual(gate.takePending(), false)
        XCTAssertNil(gate.takePending())
    }

    func testChangedSettingsWhileIdleQueuesNothing() {
        var gate = DiskRefreshGate()
        _ = gate.begin(sourceKey: "a")
        gate.settingsApplied(sourceKey: "b", isLoading: false)
        XCTAssertNil(gate.takePending())
    }
}
