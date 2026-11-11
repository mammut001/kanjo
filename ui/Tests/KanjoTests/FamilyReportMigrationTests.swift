import XCTest
@testable import KanjoCore

final class FamilyReportMigrationTests: XCTestCase {
    private var suiteName: String!
    private var defaults: UserDefaults!

    override func setUp() {
        super.setUp()
        suiteName = "KanjoMigrationTest_\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)!
    }

    override func tearDown() {
        UserDefaults.standard.removePersistentDomain(forName: suiteName)
        super.tearDown()
    }

    func testMigrationWhenEnabledAndURLAbsent() {
        defaults.set(true, forKey: SettingsKeys.familyReportEnabled)
        XCTAssertNil(defaults.object(forKey: SettingsKeys.familyReportURL))
        XCTAssertFalse(defaults.bool(forKey: SettingsKeys.familyReportMigrationDone))

        let migrated = FamilyReportMigration.migrate(defaults: defaults)

        XCTAssertTrue(migrated)
        XCTAssertEqual(
            defaults.string(forKey: SettingsKeys.familyReportURL),
            "https://usage.paytonpei.top"
        )
        XCTAssertTrue(defaults.bool(forKey: SettingsKeys.familyReportMigrationDone))
    }

    func testMigrationDoesNotWriteWhenDisabled() {
        defaults.set(false, forKey: SettingsKeys.familyReportEnabled)
        XCTAssertNil(defaults.object(forKey: SettingsKeys.familyReportURL))

        let migrated = FamilyReportMigration.migrate(defaults: defaults)

        XCTAssertFalse(migrated)
        XCTAssertNil(defaults.object(forKey: SettingsKeys.familyReportURL))
        XCTAssertTrue(defaults.bool(forKey: SettingsKeys.familyReportMigrationDone))
    }

    func testMigrationDoesNotOverwriteCustomURL() {
        defaults.set(true, forKey: SettingsKeys.familyReportEnabled)
        defaults.set("https://usage.customfamily.net", forKey: SettingsKeys.familyReportURL)

        let migrated = FamilyReportMigration.migrate(defaults: defaults)

        XCTAssertFalse(migrated)
        XCTAssertEqual(
            defaults.string(forKey: SettingsKeys.familyReportURL),
            "https://usage.customfamily.net"
        )
        XCTAssertTrue(defaults.bool(forKey: SettingsKeys.familyReportMigrationDone))
    }

    func testMigrationRunsOnlyOnce() {
        defaults.set(true, forKey: SettingsKeys.familyReportEnabled)
        let firstRun = FamilyReportMigration.migrate(defaults: defaults)
        XCTAssertTrue(firstRun)
        XCTAssertEqual(defaults.string(forKey: SettingsKeys.familyReportURL), "https://usage.paytonpei.top")

        // Change URL to something else
        defaults.set("https://usage.example.com", forKey: SettingsKeys.familyReportURL)

        // Second run must be a no-op
        let secondRun = FamilyReportMigration.migrate(defaults: defaults)
        XCTAssertFalse(secondRun)
        XCTAssertEqual(defaults.string(forKey: SettingsKeys.familyReportURL), "https://usage.example.com")
    }

    func testEmptyOrInvalidURLNoReport() {
        // Empty URL
        XCTAssertFalse(
            FamilyReportSchedule.shouldReport(
                enabled: true,
                hasToken: true,
                url: "",
                lastSuccessAt: nil,
                lastAttemptAt: nil
            )
        )

        // Whitespace only
        XCTAssertFalse(
            FamilyReportSchedule.shouldReport(
                enabled: true,
                hasToken: true,
                url: "   ",
                lastSuccessAt: nil,
                lastAttemptAt: nil
            )
        )

        // Insecure remote HTTP
        XCTAssertFalse(
            FamilyReportSchedule.shouldReport(
                enabled: true,
                hasToken: true,
                url: "http://remote.example.com",
                lastSuccessAt: nil,
                lastAttemptAt: nil
            )
        )
    }

    func testFamilyReportStatusCalculation() {
        // Empty URL yields noServer status
        let stateEmpty = FamilyReportStatus.state(
            url: "",
            hasToken: true,
            isReporting: false,
            lastError: nil,
            lastSuccessAt: nil,
            noNetwork: false
        )
        XCTAssertEqual(stateEmpty, .noServer)
        XCTAssertEqual(
            FamilyReportStatus.text(
                url: "",
                hasToken: true,
                isReporting: false,
                lastError: nil,
                lastSuccessAt: nil,
                noNetwork: false
            ),
            L10n.tr("settings.family.status.no_server")
        )

        // Invalid URL yields noServer status
        let stateInvalid = FamilyReportStatus.state(
            url: "invalid-url",
            hasToken: true,
            isReporting: false,
            lastError: nil,
            lastSuccessAt: nil,
            noNetwork: false
        )
        XCTAssertEqual(stateInvalid, .noServer)

        // Valid URL but missing token yields missingToken
        let stateNoToken = FamilyReportStatus.state(
            url: "https://usage.example.com",
            hasToken: false,
            isReporting: false,
            lastError: nil,
            lastSuccessAt: nil,
            noNetwork: false
        )
        XCTAssertEqual(stateNoToken, .missingToken)

        // Valid URL and token yields never (or last reported)
        let stateReady = FamilyReportStatus.state(
            url: "https://usage.example.com",
            hasToken: true,
            isReporting: false,
            lastError: nil,
            lastSuccessAt: nil,
            noNetwork: false
        )
        XCTAssertEqual(stateReady, .never)
    }
}
