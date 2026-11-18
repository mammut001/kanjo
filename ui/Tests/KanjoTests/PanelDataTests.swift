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
            XCTAssertEqual(ReportDates.parseTimestamp(input), expected, "Failed for \(input)")
        }
        
        // Malformed
        XCTAssertNil(ReportDates.parseTimestamp(""))
        XCTAssertNil(ReportDates.parseTimestamp("garbage"))
    }
    
    func testSpecMatch() {
        let now = Date(timeIntervalSince1970: 1000)
        let spec = RangeSpec(range: .all, calendar: Calendar(identifier: .gregorian), start: now, end: now.addingTimeInterval(100))
        
        let ctx = RangeSpec(range: .all, calendar: Calendar(identifier: .gregorian), start: now, end: now.addingTimeInterval(100))
        
        XCTAssertEqual(spec.range.rawValue, "all")
        XCTAssertEqual(spec.start, ctx.start)
        XCTAssertEqual(spec.end, ctx.end)
        
        let differentEnd = RangeSpec(range: .all, calendar: Calendar(identifier: .gregorian), start: now, end: now.addingTimeInterval(200))
        XCTAssertNotEqual(spec.end, differentEnd.end)
    }
}
