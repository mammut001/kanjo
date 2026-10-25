import XCTest
@testable import KanjoCore

final class FormattingTests: XCTestCase {
    func testMoney() {
        XCTAssertEqual(Fmt.money(0), "$0.00")
        XCTAssertEqual(Fmt.money(0.0013), "<$0.01")
        XCTAssertEqual(Fmt.money(0.009999), "<$0.01")
        XCTAssertEqual(Fmt.money(0.01), "$0.01")
        XCTAssertEqual(Fmt.money(12.345), "$12.35")
        XCTAssertEqual(Fmt.money(1234.5), "$1,234.50")
        XCTAssertEqual(Fmt.money(-1.5), "-$1.50")
        XCTAssertEqual(Fmt.money(3, currency: "EUR"), "EUR 3.00")
    }

    func testTokens() {
        XCTAssertEqual(Fmt.tokens(0), "0")
        XCTAssertEqual(Fmt.tokens(999), "999")
        XCTAssertEqual(Fmt.tokens(1000), "1.0k")
        XCTAssertEqual(Fmt.tokens(12_345), "12.3k")
        XCTAssertEqual(Fmt.tokens(999_960), "1.0M")
        XCTAssertEqual(Fmt.tokens(4_560_000), "4.6M")
        XCTAssertEqual(Fmt.tokens(2_500_000_000), "2.5B")
    }

    func testPerMonthAndMultiple() {
        XCTAssertEqual(Fmt.perMonth(100), "$100/mo")
        XCTAssertEqual(Fmt.perMonth(20), "$20/mo")
        XCTAssertEqual(Fmt.perMonth(19.5), "$19.50/mo")
        XCTAssertEqual(Fmt.perMonth(nil), "—")
        XCTAssertEqual(Fmt.multiple(15.72), "15.7×")
        XCTAssertEqual(Fmt.multiple(0), "0.0×")
        XCTAssertEqual(Fmt.multiple(nil), "—")
    }

    func testPercent() {
        XCTAssertEqual(Fmt.percent(1), "100%")
        XCTAssertEqual(Fmt.percent(0.6), "60%")
        XCTAssertEqual(Fmt.percent(0.004), "0.4%")
    }

    func testDay() {
        XCTAssertEqual(Fmt.day("2026-10-22"), "Oct 22, 2026")
        XCTAssertEqual(Fmt.day(nil), "—")
    }

    func testAttributionExplanationUsesThreshold() {
        XCTAssertTrue(AttributionInfo.explanation("dominant", threshold: 0.8).contains("80%"))
        XCTAssertTrue(AttributionInfo.explanation("weird", threshold: 0.8).contains("Unknown"))
    }
}
