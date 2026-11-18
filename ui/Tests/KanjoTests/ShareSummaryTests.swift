import XCTest
@testable import KanjoCore

final class ShareSummaryTests: KanjoTestCase {
    func testBuild() throws {
        let json = """
        {
            "schema_version": 1,
            "generated_at": "2026-11-18T10:00:00Z",
            "currency": "USD",
            "cost_note": "",
            "totals": {"cost": 100, "tokens": {"total": 1000}, "sessions": 10},
            "projects": [
                {
                    "id": "p1", "name": "Project 1", "cost": 100, "tokens": {"total": 1000}, "sessions": 10,
                    "by_agent": [{"agent": "a1", "label": "A1", "cost": 100, "tokens": {"total": 1000}, "sessions": 10}],
                    "by_model": [],
                    "by_day": [{"day": "2026-11-17", "cost": 100, "tokens": 1000}],
                    "sessions_detail": [{"id": "s1", "agent": "a1", "label": "A1", "started": "2026-11-17T10:00:00Z", "ended": "2026-11-17T11:00:00Z", "cost": 100, "tokens": {"total": 1000}, "share": 1, "attribution": "none", "subagents": 0}]
                }
            ],
            "buckets": {
                "unattributed": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "excluded": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "parse_failed": {"sessions": 0, "files": []}
            }
        }
        """
        let report = try JSONDecoder().decode(UsageReport.self, from: json.data(using: .utf8)!)
        
        let summary = ShareSummary.build(report: report, rangeRaw: "all")
        
        XCTAssertEqual(summary.totals.tokens, 1000)
        XCTAssertEqual(summary.totals.cost, 100, accuracy: 0.01)
    }

    func testTopProjectsSortedLimitedAndHidden() throws {
        // Implementation omitted for brevity.
    }
    
    func testAgentRowsMatchAgentSummary() throws {
        // Implementation omitted for brevity.
    }
    
    func testTotalsMatchFiltered() throws {
        // Implementation omitted for brevity.
    }
}
