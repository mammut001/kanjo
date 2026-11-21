import Foundation
import XCTest
@testable import KanjoCore

/// Decodes a live `kanjo export --mobile` JSON (path in `KANJO_E2E_MOBILE_JSON`).
/// Used by `scripts/e2e-smoke.sh`; skipped when the env var is unset (normal `swift test`).
final class MobileExportE2ETests: XCTestCase {
    func testMobileExportDecodesViaKanjoCore() throws {
        guard let path = ProcessInfo.processInfo.environment["KANJO_E2E_MOBILE_JSON"],
              !path.isEmpty else {
            throw XCTSkip("KANJO_E2E_MOBILE_JSON not set (e2e-smoke only)")
        }
        let data = try Data(contentsOf: URL(fileURLWithPath: path))
        let report = try ReportDecoder.decode(data)
        XCTAssertEqual(report.schemaVersion, 1)
        XCTAssertEqual(report.currency, "USD")
        // Fixture export without a fake FS may put everything in unattributed;
        // apps must still decode that shape.
        let sessions = report.projects.flatMap(\.sessionsDetail)
            + report.buckets.unattributed.sessionsDetail
            + report.buckets.excluded.sessionsDetail
        XCTAssertFalse(sessions.isEmpty, "mobile export from fixtures should include sessions")
        let session = try XCTUnwrap(sessions.first)
        XCTAssertFalse(session.id.isEmpty)
        XCTAssertFalse(session.label.isEmpty)
        XCTAssertGreaterThanOrEqual(session.tokens.total, 0)
        XCTAssertGreaterThan(report.totals.cost, 0)
    }
}
