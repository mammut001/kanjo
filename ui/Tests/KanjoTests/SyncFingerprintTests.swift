import XCTest
@testable import KanjoCore

final class SyncFingerprintTests: XCTestCase {
    private func sampleReport() throws -> UsageReport {
        try ReportDecoder.decode(Data(contentsOf: DefaultPaths.sampleFixture))
    }

    func testFingerprintIsStableAndTracksTotals() throws {
        var report = try sampleReport()
        let base = SyncFingerprint.make(for: report)
        XCTAssertEqual(base, SyncFingerprint.make(for: report))

        report.totals.cost += 0.01
        XCTAssertNotEqual(base, SyncFingerprint.make(for: report))

        report = try sampleReport()
        report.totals.tokens.total += 1
        XCTAssertNotEqual(base, SyncFingerprint.make(for: report))

        report = try sampleReport()
        report.totals.sessions += 1
        XCTAssertNotEqual(base, SyncFingerprint.make(for: report))
    }

    func testFingerprintTracksQuotaAndRounds() throws {
        var report = try sampleReport()
        report.totals.cost = 10
        report.quotaWindows?["claude"]?.weeklyUsedPercent = 57
        let base = SyncFingerprint.make(for: report)

        report.quotaWindows?["claude"]?.weeklyUsedPercent = 57.4
        XCTAssertEqual(base, SyncFingerprint.make(for: report))

        report.quotaWindows?["claude"]?.weeklyUsedPercent = 58
        XCTAssertNotEqual(base, SyncFingerprint.make(for: report))

        report = try sampleReport()
        report.totals.cost = 10.004
        XCTAssertEqual(base, SyncFingerprint.make(for: report))
    }
}
