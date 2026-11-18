import XCTest
@testable import KanjoCore

final class RefreshSchedulerTests: XCTestCase {
    func testFallbackMigration() {
        XCTAssertEqual(RefreshScheduler.migrateFallbackMinutes(5), 30)
        XCTAssertEqual(RefreshScheduler.migrateFallbackMinutes(0), 0)
        XCTAssertEqual(RefreshScheduler.migrateFallbackMinutes(15), 15)
        XCTAssertEqual(RefreshScheduler.migrateFallbackMinutes(60), 60)
    }

    func testEventSchedulesAtLastRefreshPlusInterval() {
        let t0 = Date(timeIntervalSince1970: 1000)
        let intervals: [TimeInterval] = [30, 60, 300, 600]
        
        for interval in intervals {
            var scheduler = RefreshScheduler(backgroundInterval: interval, lastRefreshTime: Date(timeIntervalSince1970: 0))
            // Last refresh 0, interval 30 -> min interval target 30.
            // Event at 1000 -> event deadline 1005. Max(30, 1005) = 1005. Delay = 5.
            let action = scheduler.onFileEvent(at: t0)
            XCTAssertEqual(action, RefreshScheduler.Action.scheduleRefresh(after: 5), "Failed for interval \(interval)")
        }
    }

    func testEventsDoNotPushDeadline() {
        let t0 = Date(timeIntervalSince1970: 1000)
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        
        // First event sets schedule 1005
        _ = scheduler.onFileEvent(at: t0)
        
        // Events every 2s for 2 minutes (120s)
        for i in 1...60 {
            let t = t0.addingTimeInterval(Double(i * 2))
            let action = scheduler.onFileEvent(at: t)
            XCTAssertEqual(action, RefreshScheduler.Action.none, "Event at \(t) pushed deadline")
        }
    }

    func testFirstEventAfterLongIdleFiresAfter5Seconds() {
        let t0 = Date(timeIntervalSince1970: 1000)
        // Last refresh at 0, interval 60. Idle for > 60s.
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        
        let action = scheduler.onFileEvent(at: t0)
        XCTAssertEqual(action, RefreshScheduler.Action.scheduleRefresh(after: 5))
    }

    func testPanelOpenCloseNeverReturnsRefreshNow() {
        var scheduler = RefreshScheduler()
        let t0 = Date(timeIntervalSince1970: 1000)
        
        XCTAssertEqual(scheduler.onPanelVisibilityChanged(visible: true, at: t0), RefreshScheduler.Action.none)
        XCTAssertEqual(scheduler.onPanelVisibilityChanged(visible: false, at: t0), RefreshScheduler.Action.none)
    }

    func testShouldRefreshOnOpenRules() {
        var scheduler = RefreshScheduler()
        
        // Stale report, not refreshing
        XCTAssertTrue(scheduler.shouldRefreshOnOpen(isStaleReport: true))
        
        // Stale report, refreshing
        scheduler.onRefreshStarted()
        XCTAssertFalse(scheduler.shouldRefreshOnOpen(isStaleReport: true))
        
        // Not stale
        scheduler.onRefreshFinished()
        XCTAssertFalse(scheduler.shouldRefreshOnOpen(isStaleReport: false))
    }

    func testBusyDefersAndBusyOffRefreshes() {
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        let t0 = Date(timeIntervalSince1970: 1000)
        
        // FSEvent while busy
        _ = scheduler.onSystemBusyChanged(busy: true, at: t0)
        let action = scheduler.onFileEvent(at: t0)
        XCTAssertEqual(action, RefreshScheduler.Action.none)
        XCTAssertTrue(scheduler.pendingWakeRefresh)
        
        // Busy off: schedule refresh when not yet due (lastRefresh 0, now 1000, minInterval 60 -> Due!)
        let actionOff = scheduler.onSystemBusyChanged(busy: false, at: t0)
        XCTAssertEqual(actionOff, RefreshScheduler.Action.refreshNow)

        // Case where not yet due:
        var scheduler2 = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 950))
        _ = scheduler2.onSystemBusyChanged(busy: true, at: t0)
        _ = scheduler2.onFileEvent(at: t0)
        
        // Busy off at 1000. lastRefresh 950 + 60 = 1010. Due at 1010.
        // It's 1000. So it should schedule for 10s later.
        let actionOff2 = scheduler2.onSystemBusyChanged(busy: false, at: t0)
        if case RefreshScheduler.Action.scheduleRefresh(let delay) = actionOff2 {
            XCTAssertEqual(delay, 10)
        } else {
            XCTFail("Expected scheduleRefresh, got \(actionOff2)")
        }
    }

    func testBackgroundIntervalChangedRetargets() {
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        _ = scheduler.onFileEvent(at: Date(timeIntervalSince1970: 1000))
        XCTAssertTrue(scheduler.hasScheduledRefresh)
        
        let action = scheduler.onBackgroundIntervalChanged(300, at: Date(timeIntervalSince1970: 1000))
        if case RefreshScheduler.Action.scheduleRefresh(let delay) = action {
            // FirstEvent 1000 + 5 = 1005.
            // MinInterval 0 + 300 = 300.
            // Max(1005, 300) = 1005. Delay = 5.
            XCTAssertEqual(delay, 5)
        } else {
            XCTFail("Expected scheduleRefresh, got \(action)")
        }
    }
    
    func testSleepWakeBehavior() {
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        scheduler.onSleep()
        
        let t = Date(timeIntervalSince1970: 1000)
        _ = scheduler.onFileEvent(at: t)
        XCTAssertTrue(scheduler.pendingWakeRefresh)
        
        let action = scheduler.onWake(at: t)
        XCTAssertEqual(action, RefreshScheduler.Action.refreshNow)
    }
}