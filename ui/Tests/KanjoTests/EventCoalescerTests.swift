import XCTest
@testable import KanjoCore

final class EventCoalescerTests: XCTestCase {
    func testHourOfFrequentEventsIsBounded() {
        let start = Date(timeIntervalSince1970: 1_000)
        var gate = EventCoalescer(interval: 60)
        var gateDeadline: Date?
        var deliveries = 0

        func drainGateDeadline(until now: Date) {
            if let deadline = gateDeadline, now >= deadline {
                gateDeadline = nil
                if gate.fire(at: now) { deliveries += 1 }
            }
        }

        // A write every 100 ms for an hour, then drain long enough for at most one trailing edge.
        for tick in 0...38_000 {
            let now = start.addingTimeInterval(Double(tick) / 10)
            drainGateDeadline(until: now)
            if tick < 36_000 {
                switch gate.event(at: now) {
                case .deliver:
                    deliveries += 1
                case .schedule(let delay):
                    gateDeadline = now.addingTimeInterval(delay)
                case .none:
                    break
                }
            }
        }
        XCTAssertGreaterThanOrEqual(deliveries, 60)
        XCTAssertLessThanOrEqual(deliveries, 61, "Coalescer caps FSEvents to one delivery per interval")
    }

    func testHourOfFrequentEventsDrivesSchedulerAtMostOncePerInterval() {
        let start = Date(timeIntervalSince1970: 1_000)
        var gate = EventCoalescer(interval: 60)
        var scheduler = RefreshScheduler(backgroundInterval: 60, lastRefreshTime: start)
        var gateDeadline: Date?
        var refreshDeadline: Date?
        var refreshes = 0

        for tick in 0...36_000 {
            let now = start.addingTimeInterval(Double(tick) / 10)
            if let deadline = gateDeadline, now >= deadline {
                gateDeadline = nil
                if gate.fire(at: now) {
                    if case .scheduleRefresh(let delay) = scheduler.onFileEvent(at: now) {
                        refreshDeadline = now.addingTimeInterval(delay)
                    }
                }
            }
            if let deadline = refreshDeadline, now >= deadline {
                refreshDeadline = nil
                scheduler.onRefreshStarted(at: now)
                refreshes += 1
                if case .scheduleRefresh(let delay) = scheduler.onRefreshFinished(at: now) {
                    refreshDeadline = now.addingTimeInterval(delay)
                }
            }
            if tick < 36_000 {
                switch gate.event(at: now) {
                case .deliver:
                    if case .scheduleRefresh(let delay) = scheduler.onFileEvent(at: now) {
                        refreshDeadline = now.addingTimeInterval(delay)
                    }
                case .schedule(let delay):
                    gateDeadline = now.addingTimeInterval(delay)
                case .none:
                    break
                }
            }
        }
        XCTAssertGreaterThanOrEqual(refreshes, 59)
        XCTAssertLessThanOrEqual(refreshes, 61)
    }

    func testIsolatedSuppressedEventIsDeliveredOnce() {
        let now = Date(timeIntervalSince1970: 0)
        var gate = EventCoalescer(interval: 60)
        XCTAssertEqual(gate.event(at: now), .deliver)
        XCTAssertEqual(gate.event(at: now.addingTimeInterval(1)), .schedule(after: 59))
        XCTAssertEqual(gate.event(at: now.addingTimeInterval(2)), .none)
        XCTAssertTrue(gate.fire(at: now.addingTimeInterval(60)))
        XCTAssertFalse(gate.fire(at: now.addingTimeInterval(60)))
    }
}