import XCTest
@testable import KanjoCore

final class ShareSummaryTests: KanjoTestCase {
    func makeReport() throws -> UsageReport {
        let json = """
        {
            "schema_version": 1,
            "generated_at": "2026-11-18T10:00:00Z",
            "currency": "USD",
            "cost_note": "",
            "totals": {"cost": 280, "tokens": {"total": 280000}, "sessions": 14},
            "projects": [
                \( (1...7).map { i in
                    let cost = (8 - i) * 10
                    return """
                    {
                        "id": "p\(i)", "name": "Project \(i)", "cost": \(Double(cost)), "tokens": {"total": \(cost * 1000)}, "sessions": 2,
                        "by_agent": [
                            {"agent": "claude", "label": "Claude Code", "cost": \(Double(cost) * 0.6), "tokens": {"total": \(cost * 600)}, "sessions": 1},
                            {"agent": "codex", "label": "Codex", "cost": \(Double(cost) * 0.4), "tokens": {"total": \(cost * 400)}, "sessions": 1}
                        ],
                        "by_model": [],
                        "by_day": [{"day": "2026-11-17", "cost": \(Double(cost)), "tokens": \(cost * 1000), "by_agent": {"claude": \(Double(cost) * 0.6), "codex": \(Double(cost) * 0.4)}, "by_agent_tokens": {"claude": \(cost * 600), "codex": \(cost * 400)}}],
                        "sessions_detail": [
                            {"id": "s1-\(i)", "agent": "claude", "label": "Claude Code", "started": "2026-11-17T10:00:00Z", "ended": "2026-11-17T11:00:00Z", "cost": \(Double(cost) * 0.6), "tokens": {"input": 100, "output": 100, "cache_read": 100, "cache_write": 100, "thinking": 200, "total": \(cost * 600)}, "share": 0.6, "attribution": "none", "subagents": 0},
                            {"id": "s2-\(i)", "agent": "codex", "label": "Codex", "started": "2026-11-17T10:00:00Z", "ended": "2026-11-17T11:00:00Z", "cost": \(Double(cost) * 0.4), "tokens": {"input": 100, "output": 100, "cache_read": 100, "cache_write": 100, "thinking": 0, "total": \(cost * 400)}, "share": 0.4, "attribution": "none", "subagents": 0}
                        ]
                    }
                    """
                }.joined(separator: ",") )
            ],
            "buckets": {
                "unattributed": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "excluded": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "parse_failed": {"sessions": 0, "files": []}
            }
        }
        """
        return try JSONDecoder().decode(UsageReport.self, from: json.data(using: .utf8)!)
    }

    func testBuild() throws {
        let report = try makeReport()
        let summary = ShareSummary.build(report: report, rangeRaw: "all")
        XCTAssertEqual(summary.totals.tokens, 280000)
        XCTAssertEqual(summary.totals.cost, 280, accuracy: 0.01)
    }

    func testTopProjectsSortedLimitedAndHidden() throws {
        let report = try makeReport()
        let now = Date(timeIntervalSince1970: 1763460000)
        let summary = ShareSummary.build(report: report, rangeRaw: "all", now: now, hiddenProjects: ["p1"])
        
        XCTAssertEqual(summary.topProjects.count, 5)
        let names = summary.topProjects.map(\.name)
        XCTAssertEqual(names, ["Project 2", "Project 3", "Project 4", "Project 5", "Project 6"])
        
        let costs = summary.topProjects.map(\.cost)
        XCTAssertTrue(costs[0] > costs[1] && costs[1] > costs[2] && costs[2] > costs[3] && costs[3] > costs[4])
        
        let sharesSum = summary.topProjects.map(\.share).reduce(0, +)
        XCTAssertTrue(sharesSum <= 1.0001)
    }
    
    func testAgentRowsMatchAgentSummary() throws {
        let report = try makeReport()
        let now = Date(timeIntervalSince1970: 1763460000)
        let rangeRaw = "all"
        let resolved = RangeEngine.resolve(raw: rangeRaw, report: report, now: now)
        let spec = resolved.spec
        let filtered = RangeEngine.filtered(report, range: spec, fallbackAgentFor: { RangeEngine.fallbackAgent(for: $0) })
        let expected = AgentSummary.build(report: report, filtered: filtered, now: now)
        
        let summary = ShareSummary.build(report: report, rangeRaw: rangeRaw, now: now)
        
        XCTAssertEqual(summary.agentRows.map(\.agent).sorted(), expected.rows.map(\.agent).sorted())
        for row in summary.agentRows {
            if let exp = expected.rows.first(where: { $0.agent == row.agent }) {
                XCTAssertEqual(row.tokens, exp.tokens)
                XCTAssertEqual(row.cost, exp.cost, accuracy: 1e-6)
            }
        }
    }
    
    func testTotalsMatchFiltered() throws {
        let report = try makeReport()
        let now = Date(timeIntervalSince1970: 1763460000)
        let resolved = RangeEngine.resolve(raw: "all", report: report, now: now)
        let filtered = RangeEngine.filtered(report, range: resolved.spec, fallbackAgentFor: { RangeEngine.fallbackAgent(for: $0) })
        
        let summary = ShareSummary.build(report: report, rangeRaw: "all", now: now)
        
        XCTAssertEqual(Double(summary.totals.tokens), Double(filtered.tokens), accuracy: 1e-6)
        XCTAssertEqual(summary.totals.cost, filtered.cost, accuracy: 1e-6)
        XCTAssertEqual(summary.agentRows.count, 2)
    }
}
