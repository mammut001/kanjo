import XCTest
@testable import KanjoCore

final class PublishScheduleTests: XCTestCase {
    let dummyRepo = "/Users/test/Documents/GitHub/resume"

    func testDisabledState() {
        let should = PublishSchedule.shouldPublish(
            enabled: false,
            repoPath: dummyRepo,
            frequency: .daily,
            lastSuccessAt: nil,
            lastAttemptAt: nil
        )
        XCTAssertFalse(should)
    }

    func testEmptyRepoPath() {
        XCTAssertFalse(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: "",
            frequency: .daily,
            lastSuccessAt: nil,
            lastAttemptAt: nil
        ))
        XCTAssertFalse(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: "   \t\n",
            frequency: .daily,
            lastSuccessAt: nil,
            lastAttemptAt: nil
        ))
    }

    func testFirstTimePublish() {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let should = PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .daily,
            lastSuccessAt: nil,
            lastAttemptAt: nil,
            now: now
        )
        XCTAssertTrue(should)
    }

    func testFailureBackoff() {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        // Failure 30 minutes ago (less than 1 hour backoff)
        let attemptRecent = now.addingTimeInterval(-1800)
        let shouldBlocked = PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .daily,
            lastSuccessAt: nil,
            lastAttemptAt: attemptRecent,
            now: now
        )
        XCTAssertFalse(shouldBlocked)

        // Failure 65 minutes ago (more than 1 hour backoff)
        let attemptOld = now.addingTimeInterval(-3900)
        let shouldAllowed = PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .daily,
            lastSuccessAt: nil,
            lastAttemptAt: attemptOld,
            now: now
        )
        XCTAssertTrue(shouldAllowed)

        // Failure after last success (e.g. success 3 days ago, attempt failed 30 mins ago)
        let lastSuccess = now.addingTimeInterval(-3 * 86400)
        let shouldBlockedAfterSuccess = PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .daily,
            lastSuccessAt: lastSuccess,
            lastAttemptAt: attemptRecent,
            now: now
        )
        XCTAssertFalse(shouldBlockedAfterSuccess)
    }

    func testDailyFrequency() {
        let now = Date(timeIntervalSince1970: 1_700_000_000)

        // 23 hours ago: not yet
        let success23h = now.addingTimeInterval(-23 * 3600)
        XCTAssertFalse(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .daily,
            lastSuccessAt: success23h,
            lastAttemptAt: success23h,
            now: now
        ))

        // 25 hours ago: ready
        let success25h = now.addingTimeInterval(-25 * 3600)
        XCTAssertTrue(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .daily,
            lastSuccessAt: success25h,
            lastAttemptAt: success25h,
            now: now
        ))
    }

    func testWeeklyFrequency() {
        let now = Date(timeIntervalSince1970: 1_700_000_000)

        // 6 days ago: not yet
        let success6d = now.addingTimeInterval(-6 * 86400)
        XCTAssertFalse(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .weekly,
            lastSuccessAt: success6d,
            lastAttemptAt: success6d,
            now: now
        ))

        // 7.5 days ago: ready
        let success7_5d = now.addingTimeInterval(-7.5 * 86400)
        XCTAssertTrue(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .weekly,
            lastSuccessAt: success7_5d,
            lastAttemptAt: success7_5d,
            now: now
        ))
    }

    func testMonthlyFrequency() {
        let tz = TimeZone(identifier: "UTC")!
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = tz

        let oct15 = cal.date(from: DateComponents(year: 2026, month: 10, day: 15, hour: 12))!
        let oct31 = cal.date(from: DateComponents(year: 2026, month: 10, day: 31, hour: 23, minute: 59))!
        let nov01 = cal.date(from: DateComponents(year: 2026, month: 11, day: 1, hour: 0, minute: 1))!
        let nov20 = cal.date(from: DateComponents(year: 2026, month: 11, day: 20, hour: 12))!

        // Same month (Oct 15 to Oct 31): false
        XCTAssertFalse(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .monthly,
            lastSuccessAt: oct15,
            lastAttemptAt: oct15,
            now: oct31,
            timeZone: tz
        ))

        // Calendar month changed (Oct 31 to Nov 01): true
        XCTAssertTrue(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .monthly,
            lastSuccessAt: oct31,
            lastAttemptAt: oct31,
            now: nov01,
            timeZone: tz
        ))

        // Same month again (Nov 01 to Nov 20): false
        XCTAssertFalse(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .monthly,
            lastSuccessAt: nov01,
            lastAttemptAt: nov01,
            now: nov20,
            timeZone: tz
        ))

        // Year boundary (Dec 31, 2025 to Jan 01, 2026): true
        let dec31 = cal.date(from: DateComponents(year: 2025, month: 12, day: 31, hour: 18))!
        let jan01 = cal.date(from: DateComponents(year: 2026, month: 1, day: 1, hour: 9))!
        XCTAssertTrue(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .monthly,
            lastSuccessAt: dec31,
            lastAttemptAt: dec31,
            now: jan01,
            timeZone: tz
        ))
    }

    func testMonthlyFrequencyRespectsReportTimezone() {
        let utc = TimeZone(identifier: "UTC")!
        let toronto = TimeZone(identifier: "America/Toronto")! // UTC-5 in November (EST) / UTC-4 in October (EDT)

        // At 2026-11-01 02:00:00 UTC:
        // In UTC: Month is 11 (November)
        // In Toronto: Month is 10 (October 31, 22:00)
        let utcNov1At2am = Date(timeIntervalSince1970: 1_793_508_000) // approx
        var utcCal = Calendar(identifier: .gregorian)
        utcCal.timeZone = utc
        let exactNov1At2am = utcCal.date(from: DateComponents(year: 2026, month: 11, day: 1, hour: 2, minute: 0))!

        let lastOct10 = utcCal.date(from: DateComponents(year: 2026, month: 10, day: 10, hour: 10))!

        // In UTC: month 10 -> 11, should publish
        XCTAssertTrue(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .monthly,
            lastSuccessAt: lastOct10,
            lastAttemptAt: lastOct10,
            now: exactNov1At2am,
            timeZone: utc
        ))

        // In Toronto: month is still 10, should NOT publish
        XCTAssertFalse(PublishSchedule.shouldPublish(
            enabled: true,
            repoPath: dummyRepo,
            frequency: .monthly,
            lastSuccessAt: lastOct10,
            lastAttemptAt: lastOct10,
            now: exactNov1At2am,
            timeZone: toronto
        ))
    }

    func testPublishCommandConstruction() {
        let base = "python3 -m kanjo export"
        let cmd = PublishCommand.command(from: base, repo: "/path/to/my repo", file: "src/data/token-usage.json", branch: "main")
        XCTAssertTrue(cmd.contains("publish-usage"))
        XCTAssertTrue(cmd.contains("--repo '/path/to/my repo'"))
        XCTAssertTrue(cmd.contains("--file src/data/token-usage.json"))
        XCTAssertTrue(cmd.contains("--branch main"))
    }
}
