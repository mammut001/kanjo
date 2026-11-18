import XCTest
@testable import KanjoCore

final class PanelDataTests: XCTestCase {
    func testParseTimestamp() {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        let formatterFraction = ISO8601DateFormatter()
        formatterFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        
        let inputs = [
            "2026-11-18T14:16:50Z",
            "2026-11-18T14:16:50.123Z",
            "2026-11-18T14:16:50.123456Z",
            "2026-11-18T14:16:50+05:30",
            "2026-11-18T14:16:50.123-08:00"
        ]
        
        for input in inputs {
            let expected = input.contains(".") ? formatterFraction.date(from: input) : formatter.date(from: input)
            let actual = ReportDates.parseTimestamp(input)
            
            if let expected = expected, let actual = actual {
                XCTAssertEqual(actual.timeIntervalSince1970, expected.timeIntervalSince1970, accuracy: 0.000001, "Failed for \(input)")
            } else {
                XCTAssertEqual(actual, expected, "Failed for \(input)")
            }
        }
        
        let malformed = [
            "", "garbage", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z",
            "2026-11-18 10:00:00Z", "2026-11-18T10:00:00Zjunk", "2026-11-18T1a:00:00Z"
        ]
        for input in malformed {
            let expected = formatter.date(from: input) ?? formatterFraction.date(from: input)
            let actual = ReportDates.parseTimestamp(input)
            if let expected = expected, let actual = actual {
                XCTAssertEqual(actual.timeIntervalSince1970, expected.timeIntervalSince1970, accuracy: 1e-6, "Failed for \(input)")
            } else {
                XCTAssertEqual(actual, expected, "Failed for \(input)")
            }
        }
    }
    
    func testSpecMatch() {
        // RangeEngine.resolve matches RangeContext's logic
        let report = try! JSONDecoder().decode(UsageReport.self, from: """
        {
            "schema_version": 1,
            "generated_at": "2026-11-18T10:00:00Z",
            "currency": "USD",
            "cost_note": "",
            "config": {"dominant_threshold": 0},
            "totals": {"cost": 0, "tokens": {"total": 0}, "sessions": 0},
            "projects": [],
            "buckets": {
                "unattributed": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "excluded": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "parse_failed": {"sessions": 0, "files": []}
            }
        }
        """.data(using: .utf8)!)
        
        let now = Date(timeIntervalSince1970: 1763440800) // 2026-11-18T10:00:00Z
        
        // sinceReset requires QuotaWindows, which are missing
        let resolved = RangeEngine.resolve(raw: "sinceReset", report: report, now: now)
        XCTAssertEqual(resolved.range, .all)
        
        let panelData = PanelData.compute(report: report, rangeRaw: "sinceReset", now: now)
        XCTAssertNotNil(panelData)
        XCTAssertEqual(panelData!.rangeSpec, resolved.spec)
    }
}
