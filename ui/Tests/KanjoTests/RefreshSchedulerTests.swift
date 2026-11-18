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
        var scheduler = RefreshScheduler(lastRefreshTime: lastRefresh, isPanelVisible: true)

        // Event happens 30s after last refresh. Debounce would be +60 (1090), but min interval is +120 (1120).
        let t1 = Date(timeIntervalSince1970: 1030)
        let action = scheduler.onFileEvent(at: t1)
        // 1120 - 1030 = 90s delay
        XCTAssertEqual(action, .scheduleRefresh(after: 90))
    }

    func testCoalesceEventsDuringRunningRefresh() {
        let t0 = Date(timeIntervalSince1970: 1000)
        var scheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 800), isPanelVisible: true)
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

        // Never refreshed yet, no pending events and not stale -> no unconditional refresh
        let freshScheduler = RefreshScheduler(lastRefreshTime: nil)
        XCTAssertFalse(freshScheduler.shouldRefreshOnOpen(at: t0))
        XCTAssertTrue(freshScheduler.shouldRefreshOnOpen(at: t0, isStaleReport: true))

        var freshWithEvent = RefreshScheduler(lastRefreshTime: nil)
        _ = freshWithEvent.onFileEvent(at: Date(timeIntervalSince1970: 990))
        XCTAssertTrue(freshWithEvent.shouldRefreshOnOpen(at: t0))

        // Refreshed 50s ago (<= 180s), even with pending events or stale cache -> no refresh
        var recentScheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 950))
        _ = recentScheduler.onFileEvent(at: Date(timeIntervalSince1970: 990))
        XCTAssertFalse(recentScheduler.shouldRefreshOnOpen(at: t0))
        XCTAssertFalse(recentScheduler.shouldRefreshOnOpen(at: t0, isStaleReport: true))

        // Refreshed 150s ago (<= 180s) with pending events -> no immediate refresh
        var withinThresholdScheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 850))
        _ = withinThresholdScheduler.onFileEvent(at: Date(timeIntervalSince1970: 990))
        XCTAssertFalse(withinThresholdScheduler.shouldRefreshOnOpen(at: t0))

        // Refreshed 200s ago (> 180s), no pending events and not stale -> no refresh
        let idleOldScheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 800))
        XCTAssertFalse(idleOldScheduler.shouldRefreshOnOpen(at: t0))

        // Refreshed 200s ago (> 180s), with pending events or stale cache -> refresh
        var pendingOldScheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 800))
        _ = pendingOldScheduler.onFileEvent(at: Date(timeIntervalSince1970: 990))
        XCTAssertTrue(pendingOldScheduler.shouldRefreshOnOpen(at: t0))
        XCTAssertTrue(idleOldScheduler.shouldRefreshOnOpen(at: t0, isStaleReport: true))

        // Currently refreshing: should not trigger another refresh on open
        var refreshingScheduler = RefreshScheduler(lastRefreshTime: Date(timeIntervalSince1970: 500))
        refreshingScheduler.onRefreshStarted(at: t0)
        _ = refreshingScheduler.onFileEvent(at: Date(timeIntervalSince1970: 999))
        XCTAssertFalse(refreshingScheduler.shouldRefreshOnOpen(at: t0, isStaleReport: true))
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

    func testDebounceStarvationMaxWait() {
        var scheduler = RefreshScheduler(lastRefreshTime: nil, isPanelVisible: true)
        let t0 = Date(timeIntervalSince1970: 1000)
        var refreshStartTimes: [Date] = []
        var scheduledRefreshTime: Date? = nil

        // Continuous events every 5s for 10 minutes (600s = 120 intervals)
        for step in 0...120 {
            let currentTime = t0.addingTimeInterval(Double(step * 5))

            // Check if scheduled refresh is due before/at this event
            if let scheduled = scheduledRefreshTime, currentTime >= scheduled {
                refreshStartTimes.append(scheduled)
                scheduler.onRefreshStarted(at: scheduled)
                scheduledRefreshTime = nil

                // Refresh finishes after 1s
                let finishTime = scheduled.addingTimeInterval(1.0)
                let finishAction = scheduler.onRefreshFinished(at: finishTime)
                if case .scheduleRefresh(let delay) = finishAction {
                    scheduledRefreshTime = finishTime.addingTimeInterval(delay)
                }
            }

            let action = scheduler.onFileEvent(at: currentTime)
            if case .scheduleRefresh(let delay) = action {
                scheduledRefreshTime = currentTime.addingTimeInterval(delay)
            }
        }

        // At least one refresh within 180s of the first event
        XCTAssertFalse(refreshStartTimes.isEmpty)
        XCTAssertLessThanOrEqual(refreshStartTimes[0].timeIntervalSince(t0), 180.0)

        // Refreshes happen at most every ~3 minutes (>= 120s min interval, <= 190s with 5s steps)
        XCTAssertGreaterThanOrEqual(refreshStartTimes.count, 3)
        for i in 1..<refreshStartTimes.count {
            let interval = refreshStartTimes[i].timeIntervalSince(refreshStartTimes[i - 1])
            XCTAssertGreaterThanOrEqual(interval, 120.0)
            XCTAssertLessThanOrEqual(interval, 190.0)
        }
    }

    func testHiddenDefaultsToFalseAndUses180SecondMinimumInterval() {
        let lastRefresh = Date(timeIntervalSince1970: 1000)
        var scheduler = RefreshScheduler(lastRefreshTime: lastRefresh)
        XCTAssertFalse(scheduler.isPanelVisible)

        // Event 30s after last refresh while hidden -> min interval is +180 (1180), delay = 150s.
        let t1 = Date(timeIntervalSince1970: 1030)
        XCTAssertEqual(scheduler.onFileEvent(at: t1), .scheduleRefresh(after: 150))

        // Coalesced follow-up after refresh finishes while hidden also uses 180s minimum gap.
        let tStart = Date(timeIntervalSince1970: 2000)
        scheduler.onRefreshStarted(at: tStart)
        XCTAssertEqual(scheduler.onFileEvent(at: Date(timeIntervalSince1970: 2005)), .none)
        let tFinish = Date(timeIntervalSince1970: 2010)
        XCTAssertEqual(scheduler.onRefreshFinished(at: tFinish), .scheduleRefresh(after: 180))
    }

    func testHiddenToVisibleWithPendingEventsRefreshesNowIfOlderThan180Seconds() {
        let lastRefresh = Date(timeIntervalSince1970: 1000)
        var scheduler = RefreshScheduler(lastRefreshTime: lastRefresh)

        // File event arrives at 1150 while hidden -> debounce +60 (1210), delay = 60s.
        XCTAssertEqual(scheduler.onFileEvent(at: Date(timeIntervalSince1970: 1150)), .scheduleRefresh(after: 60))

        // Panel opens at 1181 (> 180s since last refresh) with pending event -> refresh immediately.
        let openAt = Date(timeIntervalSince1970: 1181)
        XCTAssertTrue(scheduler.shouldRefreshOnOpen(at: openAt))
        let action = scheduler.onPanelVisibilityChanged(visible: true, at: openAt)
        XCTAssertEqual(action, .refreshNow)
        XCTAssertTrue(scheduler.isPanelVisible)
        XCTAssertFalse(scheduler.hasScheduledRefresh)
    }

    func testHiddenToVisibleWithin180SecondsDoesNotRefreshNow() {
        let lastRefresh = Date(timeIntervalSince1970: 1000)
        var scheduler = RefreshScheduler(lastRefreshTime: lastRefresh)

        // File event arrives at 1100 while hidden -> min interval is +180 (1180), delay = 80s.
        XCTAssertEqual(scheduler.onFileEvent(at: Date(timeIntervalSince1970: 1100)), .scheduleRefresh(after: 80))

        // Panel opens at 1150 (150s after last refresh, > 120s and <= 180s) -> does not refreshNow;
        // continues under visible schedule (debounce 1100 + 60 = 1160, delay = 10s).
        let openAt = Date(timeIntervalSince1970: 1150)
        XCTAssertFalse(scheduler.shouldRefreshOnOpen(at: openAt))
        let action = scheduler.onPanelVisibilityChanged(visible: true, at: openAt)
        XCTAssertEqual(action, .scheduleRefresh(after: 10))
        XCTAssertTrue(scheduler.isPanelVisible)
        XCTAssertTrue(scheduler.hasScheduledRefresh)
    }

    func testHiddenToVisibleWithPendingEventsReschedulesIfWithin120Seconds() {
        let lastRefresh = Date(timeIntervalSince1970: 1000)
        var scheduler = RefreshScheduler(lastRefreshTime: lastRefresh)

        // File event arrives at 1020 while hidden -> scheduled for 1180 (delay 160s).
        XCTAssertEqual(scheduler.onFileEvent(at: Date(timeIntervalSince1970: 1020)), .scheduleRefresh(after: 160))

        // Panel opens at 1090 (90s after last refresh, <= 120s) -> reschedules for 1120 (delay 30s).
        let action = scheduler.onPanelVisibilityChanged(visible: true, at: Date(timeIntervalSince1970: 1090))
        XCTAssertEqual(action, .scheduleRefresh(after: 30))
        XCTAssertTrue(scheduler.isPanelVisible)
        XCTAssertTrue(scheduler.hasScheduledRefresh)
    }

    func testOpenWithNoPendingEventsDoesNotRefresh() {
        let lastRefresh = Date(timeIntervalSince1970: 1000)
        var idleScheduler = RefreshScheduler(lastRefreshTime: lastRefresh)
        let openAt = Date(timeIntervalSince1970: 1500) // 500s > 180s, but no pending events

        XCTAssertFalse(idleScheduler.shouldRefreshOnOpen(at: openAt))
        XCTAssertEqual(idleScheduler.onPanelVisibilityChanged(visible: true, at: openAt), .none)
        XCTAssertTrue(idleScheduler.isPanelVisible)
        XCTAssertFalse(idleScheduler.hasScheduledRefresh)
    }

    func testVisibleToHiddenExtendsPendingScheduleTo180SecondRule() {
        let lastRefresh = Date(timeIntervalSince1970: 1000)
        var scheduler = RefreshScheduler(lastRefreshTime: lastRefresh, isPanelVisible: true)

        // Event arrives at 1030 while visible -> scheduled for 1120 (delay 90s).
        XCTAssertEqual(scheduler.onFileEvent(at: Date(timeIntervalSince1970: 1030)), .scheduleRefresh(after: 90))

        // Panel closes at 1050 -> extends pending schedule to 1180 (delay 130s).
        let action = scheduler.onPanelVisibilityChanged(visible: false, at: Date(timeIntervalSince1970: 1050))
        XCTAssertEqual(action, .scheduleRefresh(after: 130))
        XCTAssertFalse(scheduler.isPanelVisible)
        XCTAssertTrue(scheduler.hasScheduledRefresh)
    }
}
