import XCTest
@testable import KanjoCore

final class RefreshSchedulerTests: XCTestCase {
    func testFallbackMigration() {
        XCTAssertEqual(RefreshScheduler.migrateFallbackMinutes(5), 30)
        XCTAssertEqual(RefreshScheduler.migrateFallbackMinutes(10), 30)
        XCTAssertEqual(RefreshScheduler.migrateFallbackMinutes(14), 30)
        XCTAssertEqual(RefreshScheduler.migrateFallbackMinutes(15), 15)
        XCTAssertEqual(RefreshScheduler.migrateFallbackMinutes(30), 30)
        XCTAssertEqual(RefreshScheduler.migrateFallbackMinutes(60), 60)
        XCTAssertEqual(RefreshScheduler.migrateFallbackMinutes(0), 0)
    }

    func testDebounce60SecondsAfterEvent() {
        let t0 = Date(timeIntervalSince1970: 1000)
        // Last refresh was long ago
        var scheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 0))
        let action = scheduler.onFileEvent(at: t0)
        XCTAssertEqual(action, .scheduleRefresh(after: 60))
    }

    func testMinimumInterval120SecondsBetweenRefreshes() {
        let lastRefresh = Date(timeIntervalSince1970: 1000)
        var scheduler = RefreshScheduler(lastRefreshTime: lastRefresh)

        // Event happens 30s after last refresh. Debounce would be +60 (1090), but min interval is +120 (1120).
        let t1 = Date(timeIntervalSince1970: 1030)
        let action = scheduler.onFileEvent(at: t1)
        // 1120 - 1030 = 90s delay
        XCTAssertEqual(action, .scheduleRefresh(after: 90))
    }

    func testCoalesceEventsDuringRunningRefresh() {
        let t0 = Date(timeIntervalSince1970: 1000)
        var scheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 800))
        scheduler.onRefreshStarted(at: t0)

        // Events arrive during refresh
        let t1 = Date(timeIntervalSince1970: 1005)
        let action1 = scheduler.onFileEvent(at: t1)
        XCTAssertEqual(action1, .none)
        XCTAssertTrue(scheduler.hasPendingEventWhileRefreshing)

        let t2 = Date(timeIntervalSince1970: 1010)
        let action2 = scheduler.onFileEvent(at: t2)
        XCTAssertEqual(action2, .none)

        // Refresh finishes at t3 (1015).
        // Coalesced follow-up must respect debounce from t2 (1010 + 60 = 1070)
        // and min interval from t3 (1015 + 120 = 1135).
        // max(1070, 1135) = 1135. Delay from 1015 is 120s.
        let t3 = Date(timeIntervalSince1970: 1015)
        let finishAction = scheduler.onRefreshFinished(at: t3)
        XCTAssertEqual(finishAction, .scheduleRefresh(after: 120))
        XCTAssertFalse(scheduler.hasPendingEventWhileRefreshing)
    }

    func testShouldRefreshOnOpen() {
        let t0 = Date(timeIntervalSince1970: 1000)

        // Never refreshed yet
        let freshScheduler = RefreshScheduler(lastRefreshTime: nil)
        XCTAssertTrue(freshScheduler.shouldRefreshOnOpen(at: t0))

        // Refreshed 50s ago (<= 120s)
        let recentScheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 950))
        XCTAssertFalse(recentScheduler.shouldRefreshOnOpen(at: t0))

        // Refreshed 121s ago (> 120s)
        let oldScheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 870))
        XCTAssertTrue(oldScheduler.shouldRefreshOnOpen(at: t0))

        // Currently refreshing: should not trigger another refresh on open
        var refreshingScheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 500))
        refreshingScheduler.onRefreshStarted(at: t0)
        XCTAssertFalse(refreshingScheduler.shouldRefreshOnOpen(at: t0))
    }

    func testSleepAndWakeHandling() {
        var scheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 500))
        scheduler.onSleep()
        XCTAssertTrue(scheduler.isAsleep)

        // Events while asleep do not schedule immediate timer
        let t1 = Date(timeIntervalSince1970: 600)
        let action = scheduler.onFileEvent(at: t1)
        XCTAssertEqual(action, .none)
        XCTAssertTrue(scheduler.pendingWakeRefresh)

        // Wake 400s later (well past 120s min interval)
        let tWake = Date(timeIntervalSince1970: 1000)
        let wakeAction = scheduler.onWake(at: tWake)
        XCTAssertEqual(wakeAction, .refreshNow)
        XCTAssertFalse(scheduler.isAsleep)
        XCTAssertFalse(scheduler.pendingWakeRefresh)
    }

    func testLowPowerModeHandling() {
        var scheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 500))
        _ = scheduler.onLowPowerModeChanged(enabled: true, at: Date(timeIntervalSince1970: 600))
        XCTAssertTrue(scheduler.isLowPowerMode)

        // Fallback timer while in low power mode is queued
        let tTimer = Date(timeIntervalSince1970: 3000)
        let timerAction = scheduler.onFallbackTimerFired(at: tTimer)
        XCTAssertEqual(timerAction, .none)
        XCTAssertTrue(scheduler.pendingWakeRefresh)

        // Exiting low power mode triggers refresh
        let tExit = Date(timeIntervalSince1970: 3100)
        let exitAction = scheduler.onLowPowerModeChanged(enabled: false, at: tExit)
        XCTAssertEqual(exitAction, .refreshNow)
    }

    func testFallbackTimerFiresWhenDue() {
        var scheduler = RefreshScheduler(fallbackMinutes: 30, lastRefreshTime: Date(timeIntervalSince1970: 0))

        // Firing before 30 min (e.g. at 20 min) -> .none
        let t20 = Date(timeIntervalSince1970: 20 * 60)
        XCTAssertEqual(scheduler.onFallbackTimerFired(at: t20), .none)

        // Firing at 30 min -> .refreshNow
        let t30 = Date(timeIntervalSince1970: 30 * 60)
        XCTAssertEqual(scheduler.onFallbackTimerFired(at: t30), .refreshNow)
    }
}
