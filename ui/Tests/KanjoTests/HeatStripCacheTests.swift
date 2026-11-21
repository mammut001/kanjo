import XCTest
@testable import KanjoCore

final class HeatStripCacheTests: XCTestCase {
    func testCachedDaysMatchCalendarParsingAcrossTimeZones() {
        let days = ["2024-02-29", "2025-03-09", "2025-11-02", "2026-01-01", "2026-13-01", "bad", "2026-2-3"]
        for zone in ["UTC", "America/New_York", "Asia/Shanghai", "Pacific/Apia"] {
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = TimeZone(identifier: zone)!
            for day in days {
                let parts = day.split(separator: "-")
                let expected: Date?
                if parts.count == 3, let year = Int(parts[0]), let month = Int(parts[1]), let date = Int(parts[2]) {
                    expected = calendar.date(from: DateComponents(year: year, month: month, day: date))
                } else {
                    expected = nil
                }
                XCTAssertEqual(HeatStrip.parseDay(day, calendar: calendar), expected, "\(day) in \(zone)")
                XCTAssertEqual(HeatStrip.parseDay(day, calendar: calendar), expected, "cached \(day) in \(zone)")
            }
        }
    }
}
