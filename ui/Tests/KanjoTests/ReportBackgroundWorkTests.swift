import XCTest
@testable import KanjoCore

final class ReportBackgroundWorkTests: XCTestCase {
    func testRenderingDoesNotStartBackgroundWork() {
        for isSnapshot in [true, false] {
            let policy = ReportBackgroundWork(isSnapshot: isSnapshot)
            var started: [String] = []
            policy.start(
                checkPython: { started.append("python") },
                loadKnownPlans: { started.append("plans") },
                restartTimer: { started.append("timer") },
                setupWatcher: { started.append("watcher") },
                setupNotifications: { started.append("notifications") }
            )
            policy.perform { started.append("background refresh") }
            policy.perform { started.append("family and publish schedules") }
            XCTAssertEqual(started, isSnapshot ? [] : ["notifications", "python", "plans", "timer", "watcher", "background refresh", "family and publish schedules"])
        }
    }

    func testRenderingArguments() {
        for argument in ["--snapshot", "--snapshot=out.png", "--share-image", "--share-image=out.png"] {
            XCTAssertTrue(AppDefaults.isRenderingMode(arguments: [argument]))
        }
        XCTAssertFalse(AppDefaults.isRenderingMode(arguments: ["--window"]))
    }
}
