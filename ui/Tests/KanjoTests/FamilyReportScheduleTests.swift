import XCTest
@testable import KanjoCore

final class FamilyReportScheduleTests: XCTestCase {
    let dummyURL = "https://usage.paytonpei.top"

    func testDisabledState() {
        let should = FamilyReportSchedule.shouldReport(
            enabled: false,
            hasToken: true,
            url: dummyURL,
            lastSuccessAt: nil,
            lastAttemptAt: nil
        )
        XCTAssertFalse(should)
    }

    func testMissingToken() {
        let should = FamilyReportSchedule.shouldReport(
            enabled: true,
            hasToken: false,
            url: dummyURL,
            lastSuccessAt: nil,
            lastAttemptAt: nil
        )
        XCTAssertFalse(should)
    }

    func testURLValidation() {
        // Valid HTTPS URLs
        XCTAssertTrue(FamilyReportSchedule.isValidURL("https://usage.paytonpei.top"))
        XCTAssertTrue(FamilyReportSchedule.isValidURL("https://example.com/api"))

        // Valid local HTTP test URLs
        XCTAssertTrue(FamilyReportSchedule.isValidURL("http://127.0.0.1:8788"))
        XCTAssertTrue(FamilyReportSchedule.isValidURL("http://localhost:8788"))

        // Invalid URLs
        XCTAssertFalse(FamilyReportSchedule.isValidURL(""))
        XCTAssertFalse(FamilyReportSchedule.isValidURL("   "))
        XCTAssertFalse(FamilyReportSchedule.isValidURL("http://usage.paytonpei.top"))
        XCTAssertFalse(FamilyReportSchedule.isValidURL("ftp://127.0.0.1"))
        XCTAssertFalse(FamilyReportSchedule.isValidURL("not-a-url"))

        // shouldReport rejects invalid URLs
        XCTAssertFalse(FamilyReportSchedule.shouldReport(
            enabled: true,
            hasToken: true,
            url: "http://insecure.example.com",
            lastSuccessAt: nil,
            lastAttemptAt: nil
        ))
    }

    func testNoNetwork() {
        let should = FamilyReportSchedule.shouldReport(
            enabled: true,
            hasToken: true,
            url: dummyURL,
            lastSuccessAt: nil,
            lastAttemptAt: nil,
            noNetwork: true
        )
        XCTAssertFalse(should)
    }

    func testFirstTimeReport() {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let should = FamilyReportSchedule.shouldReport(
            enabled: true,
            hasToken: true,
            url: dummyURL,
            lastSuccessAt: nil,
            lastAttemptAt: nil,
            now: now
        )
        XCTAssertTrue(should)
    }

    func testFailureBackoff() {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        // Failure 10 minutes ago (less than 30 minutes backoff)
        let attemptRecent = now.addingTimeInterval(-600)
        let shouldBlocked = FamilyReportSchedule.shouldReport(
            enabled: true,
            hasToken: true,
            url: dummyURL,
            lastSuccessAt: nil,
            lastAttemptAt: attemptRecent,
            now: now
        )
        XCTAssertFalse(shouldBlocked)

        // Failure 35 minutes ago (more than 30 minutes backoff)
        let attemptOld = now.addingTimeInterval(-2100)
        let shouldAllowed = FamilyReportSchedule.shouldReport(
            enabled: true,
            hasToken: true,
            url: dummyURL,
            lastSuccessAt: nil,
            lastAttemptAt: attemptOld,
            now: now
        )
        XCTAssertTrue(shouldAllowed)

        // Failure after last success (success 1 hour ago, failed 10 mins ago -> blocked)
        let lastSuccess = now.addingTimeInterval(-3600)
        let shouldBlockedAfterSuccess = FamilyReportSchedule.shouldReport(
            enabled: true,
            hasToken: true,
            url: dummyURL,
            lastSuccessAt: lastSuccess,
            lastAttemptAt: attemptRecent,
            now: now
        )
        XCTAssertFalse(shouldBlockedAfterSuccess)

        // Failure after last success (success 1 hour ago, failed 35 mins ago -> allowed)
        let shouldAllowedAfterSuccess = FamilyReportSchedule.shouldReport(
            enabled: true,
            hasToken: true,
            url: dummyURL,
            lastSuccessAt: lastSuccess,
            lastAttemptAt: attemptOld,
            now: now
        )
        XCTAssertTrue(shouldAllowedAfterSuccess)
    }

    func testSuccessInterval() {
        let now = Date(timeIntervalSince1970: 1_700_000_000)

        // Success 10 minutes ago (less than 15 minutes) -> not yet
        let success10m = now.addingTimeInterval(-600)
        XCTAssertFalse(FamilyReportSchedule.shouldReport(
            enabled: true,
            hasToken: true,
            url: dummyURL,
            lastSuccessAt: success10m,
            lastAttemptAt: success10m,
            now: now
        ))

        // Success 16 minutes ago (more than 15 minutes) -> allowed
        let success16m = now.addingTimeInterval(-960)
        XCTAssertTrue(FamilyReportSchedule.shouldReport(
            enabled: true,
            hasToken: true,
            url: dummyURL,
            lastSuccessAt: success16m,
            lastAttemptAt: success16m,
            now: now
        ))
    }

    func testClockSkew() {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let futureSuccess = now.addingTimeInterval(3600)
        XCTAssertFalse(FamilyReportSchedule.shouldReport(
            enabled: true,
            hasToken: true,
            url: dummyURL,
            lastSuccessAt: futureSuccess,
            lastAttemptAt: nil,
            now: now
        ))
    }

    func testCommandConstruction() {
        let cmdWithLabel = FamilyReportCommand.command(
            from: "python3 -m kanjo export",
            url: "https://usage.paytonpei.top",
            memberLabel: "Alice (MacBook)"
        )
        XCTAssertEqual(
            cmdWithLabel,
            "python3 -m kanjo report-family --url https://usage.paytonpei.top --member-label 'Alice (MacBook)'"
        )

        let cmdWithoutLabel = FamilyReportCommand.command(
            from: "python3 -m kanjo export",
            url: "https://usage.paytonpei.top",
            memberLabel: nil
        )
        XCTAssertEqual(
            cmdWithoutLabel,
            "python3 -m kanjo report-family --url https://usage.paytonpei.top"
        )

        // Ensure token is never anywhere in the command
        XCTAssertFalse(cmdWithLabel.contains("token"))
        XCTAssertFalse(cmdWithoutLabel.contains("token"))
    }

    func testTokenStorageMock() {
        let storage = MockFamilyTokenStorage()
        XCTAssertFalse(storage.hasToken())
        XCTAssertNil(storage.loadToken())

        XCTAssertTrue(storage.saveToken("secret-token-123"))
        XCTAssertTrue(storage.hasToken())
        XCTAssertEqual(storage.loadToken(), "secret-token-123")

        XCTAssertTrue(storage.deleteToken())
        XCTAssertFalse(storage.hasToken())
        XCTAssertNil(storage.loadToken())
    }
}
