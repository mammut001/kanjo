import XCTest
import KanjoCore
@testable import Kanjo

@MainActor
final class SnapshotStoreTests: XCTestCase {
    final class Source: SnapshotSource {
        var result: Result<UsageReport?, Error>
        var lastDeviceName: String? = "Mac"
        init(_ result: Result<UsageReport?, Error>) { self.result = result }
        func load() async throws -> UsageReport? { try result.get() }
    }

    private func sample() throws -> UsageReport {
        let url = try XCTUnwrap(Bundle(for: SnapshotStore.self).url(forResource: "sample-snapshot", withExtension: "json"))
        return try ReportDecoder.decode(Data(contentsOf: url))
    }

    func testRefreshFailureKeepsReportAndShowsWarning() async throws {
        let report = try sample()
        let source = Source(.success(report))
        let store = SnapshotStore(source: source)
        await store.load()
        source.result = .failure(NSError(domain: "offline", code: 1))
        await store.refresh()
        guard case .loaded(let retained) = store.state else { return XCTFail("Refresh lost the report") }
        XCTAssertEqual(retained, report)
        XCTAssertTrue(store.refreshFailed)
    }

    func testRefreshDoesNotReplaceReportWithEmptySnapshot() async throws {
        let report = try sample()
        let source = Source(.success(report))
        let store = SnapshotStore(source: source)
        await store.load()
        source.result = .success(nil)
        await store.refresh()
        guard case .loaded(let retained) = store.state else { return XCTFail("Empty refresh lost the report") }
        XCTAssertEqual(retained, report)
        XCTAssertTrue(store.refreshFailed)
    }

    func testRefreshDoesNotReplaceReportWithOlderSnapshot() async throws {
        let report = try sample()
        let source = Source(.success(report))
        let store = SnapshotStore(source: source)
        await store.load()
        var older = report
        older.generatedAt = "2020-01-01T00:00:00Z"
        source.result = .success(older)
        await store.refresh()
        guard case .loaded(let newest) = store.state else { return XCTFail("Missing report") }
        XCTAssertEqual(newest.generatedAt, report.generatedAt)
        XCTAssertTrue(store.refreshFailed)
        source.result = .success(report)
        await store.refresh()
        XCTAssertFalse(store.refreshFailed)
    }
    func testHeatStripUsesSnapshotTimezoneAtWeekBoundary() throws {
        let previous = NSTimeZone.default
        NSTimeZone.default = TimeZone(identifier: "America/Los_Angeles")!
        defer { NSTimeZone.default = previous }
        var report = try sample()
        report.timezone = "Asia/Tokyo"
        report.generatedAt = "2026-10-25T16:00:00Z" // Monday in Tokyo, Sunday in Los Angeles.
        let project = try XCTUnwrap(report.projects.first)
        let last = try XCTUnwrap(project.heatWeeks(endingOn: report.heatEndDate, timezone: RangeEngine.timezone(of: report)).last)
        let calendar = RangeEngine.calendar(timezone: TimeZone(identifier: "Asia/Tokyo")!)
        XCTAssertEqual(RangeEngine.dayString(last.start, calendar: calendar), "2026-10-26")
    }

    func testSwitchingToSampleClearsRefreshWarning() async throws {
        let source = Source(.success(try sample()))
        let store = SnapshotStore(source: source)
        await store.load()
        source.result = .failure(NSError(domain: "offline", code: 1))
        await store.refresh()
        XCTAssertTrue(store.refreshFailed)
        await store.loadSample()
        XCTAssertFalse(store.refreshFailed)
    }

    func testMobileSnapshotDecodesWithoutOmittedFields() throws {
        let url = try XCTUnwrap(Bundle(for: SnapshotStore.self).url(forResource: "sample-snapshot", withExtension: "json"))
        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        for key in ["config", "quota_windows", "subscriptions", "generated_by", "timezone", "perf_by_day"] {
            json.removeValue(forKey: key)
        }
        var projects = try XCTUnwrap(json["projects"] as? [[String: Any]])
        for index in projects.indices {
            for key in ["config", "paths", "remote", "path_missing", "by_branch"] {
                projects[index].removeValue(forKey: key)
            }
            if var sessions = projects[index]["sessions_detail"] as? [[String: Any]] {
                for sessionIndex in sessions.indices {
                    for key in ["id", "title", "cwd", "branch", "label", "share", "attribution", "subagents", "by_day"] {
                        sessions[sessionIndex].removeValue(forKey: key)
                    }
                }
                projects[index]["sessions_detail"] = sessions
            }
        }
        json["projects"] = projects
        let report = try ReportDecoder.decode(JSONSerialization.data(withJSONObject: json))
        XCTAssertFalse(report.projects.isEmpty)
        let session = try XCTUnwrap(report.projects.flatMap(\.sessionsDetail).first)
        XCTAssertEqual(session.id, "\(session.agent)@\(session.started)")
        XCTAssertNil(report.timezone)
    }

}
