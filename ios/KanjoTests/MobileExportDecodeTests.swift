import Foundation
import XCTest
import KanjoCore

/// iOS-side decode of a live `kanjo export --mobile` JSON.
/// `scripts/e2e-smoke.sh` sets `KANJO_E2E_MOBILE_JSON` (and `SIMCTL_CHILD_…` for the simulator).
final class MobileExportDecodeTests: XCTestCase {
    func testLiveMobileExportDecodes() throws {
        guard let path = ProcessInfo.processInfo.environment["KANJO_E2E_MOBILE_JSON"],
              !path.isEmpty else {
            throw XCTSkip("KANJO_E2E_MOBILE_JSON not set (e2e-smoke only)")
        }
        let data = try Data(contentsOf: URL(fileURLWithPath: path))
        let report = try ReportDecoder.decode(data)
        XCTAssertEqual(report.schemaVersion, 1)
        let sessions = report.projects.flatMap(\.sessionsDetail)
            + report.buckets.unattributed.sessionsDetail
            + report.buckets.excluded.sessionsDetail
        XCTAssertFalse(sessions.isEmpty)
        let session = try XCTUnwrap(sessions.first)
        // Slim mobile sessions omit id; decoder falls back to agent@started.
        XCTAssertEqual(session.id, "\(session.agent)@\(session.started)")
        XCTAssertGreaterThanOrEqual(session.tokens.total, 0)
        XCTAssertGreaterThan(report.totals.cost, 0)
    }
}
