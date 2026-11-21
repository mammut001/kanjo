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

    /// A file event already armed a refresh. Sleep cancels that timer; wake must still run it.
    func testSleepParksScheduledRefreshUntilWake() {
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        let t = Date(timeIntervalSince1970: 1000)
        _ = scheduler.onFileEvent(at: t)
        XCTAssertTrue(scheduler.hasScheduledRefresh)

        scheduler.onSleep()
        XCTAssertFalse(scheduler.hasScheduledRefresh)
        XCTAssertTrue(scheduler.pendingWakeRefresh)
        XCTAssertEqual(scheduler.onWake(at: t.addingTimeInterval(120)), .refreshNow)
    }

    /// Enabling Low Power must park an armed refresh and resume it when power returns.
    func testLowPowerParksScheduledRefreshUntilPowerReturns() {
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        let t = Date(timeIntervalSince1970: 1000)
        _ = scheduler.onFileEvent(at: t)

        XCTAssertEqual(scheduler.onLowPowerModeChanged(enabled: true, at: t), .none)
        XCTAssertFalse(scheduler.hasScheduledRefresh)
        XCTAssertTrue(scheduler.pendingWakeRefresh)
        XCTAssertEqual(scheduler.onFileEvent(at: t.addingTimeInterval(1)), .none)
        XCTAssertEqual(scheduler.onLowPowerModeChanged(enabled: false, at: t.addingTimeInterval(1)), .refreshNow)
    }

    /// A change that arrives mid-refresh, then the machine sleeps before the refresh finishes,
    /// must still refresh after wake. The in-flight result is already stale.
    func testFileEventDuringRefreshSurvivesSleep() {
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        let t = Date(timeIntervalSince1970: 1000)
        scheduler.onRefreshStarted(at: t)
        XCTAssertEqual(scheduler.onFileEvent(at: t), .none)
        XCTAssertTrue(scheduler.hasPendingEventWhileRefreshing)

        scheduler.onSleep()
        XCTAssertEqual(scheduler.onRefreshFinished(at: t), .none)
        XCTAssertEqual(scheduler.onWake(at: t.addingTimeInterval(120)), .refreshNow)
    }

    /// Same as sleep, but the machine is busy when the in-flight refresh finishes.
    func testFileEventDuringRefreshSurvivesBusy() {
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        let t = Date(timeIntervalSince1970: 1000)
        scheduler.onRefreshStarted(at: t)
        XCTAssertEqual(scheduler.onFileEvent(at: t), .none)
        XCTAssertEqual(scheduler.onSystemBusyChanged(busy: true, at: t), .none)
        XCTAssertEqual(scheduler.onRefreshFinished(at: t), .none)
        XCTAssertTrue(scheduler.pendingWakeRefresh)

        XCTAssertEqual(scheduler.onSystemBusyChanged(busy: false, at: t.addingTimeInterval(120)), .refreshNow)
    }

    /// Wake while the deferred refresh is still running must not drop the follow-up.
    func testWakeDuringRefreshDefersFollowUpUntilFinish() {
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        let t = Date(timeIntervalSince1970: 1000)
        scheduler.onSleep()
        _ = scheduler.onFileEvent(at: t)
        scheduler.onRefreshStarted(at: t)

        let wake = scheduler.onWake(at: t.addingTimeInterval(5))
        XCTAssertEqual(wake, .none)
        XCTAssertTrue(scheduler.hasPendingEventWhileRefreshing)

        let finished = scheduler.onRefreshFinished(at: t.addingTimeInterval(5))
        guard case .scheduleRefresh(let delay) = finished else {
            return XCTFail("expected a follow-up schedule, got \(finished)")
        }
        XCTAssertEqual(delay, 60, accuracy: 0.001)
        XCTAssertFalse(scheduler.pendingWakeRefresh)
    }

    /// Waking into Low Power must not refresh until Low Power is off.
    func testWakeWhileLowPowerDoesNotRefresh() {
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        let t = Date(timeIntervalSince1970: 1000)
        _ = scheduler.onLowPowerModeChanged(enabled: true, at: t)
        scheduler.onSleep()
        _ = scheduler.onFileEvent(at: t)

        XCTAssertEqual(scheduler.onWake(at: t), .none)
        XCTAssertTrue(scheduler.pendingWakeRefresh)
        XCTAssertTrue(scheduler.isLowPowerMode)
        XCTAssertEqual(scheduler.onLowPowerModeChanged(enabled: false, at: t), .refreshNow)
    }

    /// Low Power ending while the machine is still asleep must not refresh.
    func testLowPowerOffWhileAsleepDoesNotRefresh() {
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: Date(timeIntervalSince1970: 0))
        let t = Date(timeIntervalSince1970: 1000)
        _ = scheduler.onLowPowerModeChanged(enabled: true, at: t)
        scheduler.onSleep()
        _ = scheduler.onFileEvent(at: t)

        XCTAssertEqual(scheduler.onLowPowerModeChanged(enabled: false, at: t), .none)
        XCTAssertTrue(scheduler.pendingWakeRefresh)
        XCTAssertTrue(scheduler.isAsleep)
        XCTAssertEqual(scheduler.onWake(at: t), .refreshNow)
    }
}