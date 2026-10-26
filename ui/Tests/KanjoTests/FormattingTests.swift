import XCTest
@testable import KanjoCore

final class FormattingTests: KanjoTestCase {
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

    func testMenuBarMoney() {
        // < 100：两位小数，保留 <$0.01
        XCTAssertEqual(Fmt.menuBarMoney(0.004), "<$0.01")
        XCTAssertEqual(Fmt.menuBarMoney(12.345), "$12.35")
        XCTAssertEqual(Fmt.menuBarMoney(99.99), "$99.99")

        // 100 ..< 10,000：无小数，千分位分组
        XCTAssertEqual(Fmt.menuBarMoney(100), "$100")
        XCTAssertEqual(Fmt.menuBarMoney(3056.88), "$3,057")

        // >= 10,000：紧凑 K/M 一位小数，去尾部 .0（四舍五入 >= 10,000 也进位到此档）
        XCTAssertEqual(Fmt.menuBarMoney(9999.6), "$10K")
        XCTAssertEqual(Fmt.menuBarMoney(10000), "$10K")
        XCTAssertEqual(Fmt.menuBarMoney(12345), "$12.3K")
        XCTAssertEqual(Fmt.menuBarMoney(1_234_567), "$1.2M")

        // 负数：保持前导 -
        XCTAssertEqual(Fmt.menuBarMoney(-0.004), "-<$0.01")
        XCTAssertEqual(Fmt.menuBarMoney(-12.345), "-$12.35")
        XCTAssertEqual(Fmt.menuBarMoney(-3056.88), "-$3,057")
        XCTAssertEqual(Fmt.menuBarMoney(-12345), "-$12.3K")

        // 非 USD
        XCTAssertEqual(Fmt.menuBarMoney(12.345, currency: "EUR"), "EUR 12.35")
        XCTAssertEqual(Fmt.menuBarMoney(3056.88, currency: "EUR"), "EUR 3,057")
        XCTAssertEqual(Fmt.menuBarMoney(12345, currency: "EUR"), "EUR 12.3K")
        XCTAssertEqual(Fmt.menuBarMoney(-3056.88, currency: "EUR"), "-EUR 3,057")
    }

    func testMenuBarText() {
        // 金额模式：固定窗口有后缀，其余无后缀
        XCTAssertEqual(MenuBarText.make(cost: 3056.88, currency: "USD", range: .all), "$3,057")
        XCTAssertEqual(MenuBarText.make(cost: 3056.88, currency: "USD", range: .days7), "$3,057 · \(TimeRange.days7.shortLabel)")
        XCTAssertEqual(MenuBarText.make(cost: 3056.88, currency: "USD", range: .days30), "$3,057 · \(TimeRange.days30.shortLabel)")
        XCTAssertEqual(MenuBarText.make(cost: 3056.88, currency: "USD", range: .lastWeek), "$3,057")
        XCTAssertEqual(MenuBarText.make(cost: 3056.88, currency: "USD", range: .sinceReset), "$3,057")
        XCTAssertEqual(MenuBarText.make(cost: 3056.88, currency: "USD", range: .billingCycle), "$3,057")

        // Token 模式：固定窗口有后缀，其余无后缀
        XCTAssertEqual(MenuBarText.make(tokens: 23_500_000_000, range: .all), "23.5B")
        XCTAssertEqual(MenuBarText.make(tokens: 23_500_000_000, range: .days7), "23.5B · \(TimeRange.days7.shortLabel)")
        XCTAssertEqual(MenuBarText.make(tokens: 23_500_000_000, range: .days30), "23.5B · \(TimeRange.days30.shortLabel)")
        XCTAssertEqual(MenuBarText.make(tokens: 23_500_000_000, range: .lastWeek), "23.5B")
        XCTAssertEqual(MenuBarText.make(tokens: 23_500_000_000, range: .sinceReset), "23.5B")
        XCTAssertEqual(MenuBarText.make(tokens: 23_500_000_000, range: .billingCycle), "23.5B")

        // 统一模式入口
        XCTAssertEqual(MenuBarText.make(mode: .cost, cost: 100, tokens: 500, range: .days7), "$100 · \(TimeRange.days7.shortLabel)")
        XCTAssertEqual(MenuBarText.make(mode: .tokens, cost: 100, tokens: 500, range: .days7), "500 · \(TimeRange.days7.shortLabel)")
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

    func testBytes() {
        XCTAssertEqual(Fmt.bytes(0), "0 B")
        XCTAssertEqual(Fmt.bytes(999), "999 B")
        XCTAssertEqual(Fmt.bytes(1_500), "1.5 KB")
        XCTAssertEqual(Fmt.bytes(626_000_000), "626 MB")
        XCTAssertEqual(Fmt.bytes(1_100_000_000), "1.1 GB")
        XCTAssertEqual(Fmt.bytes(11_800_000_000), "11.8 GB")
        XCTAssertEqual(Fmt.bytes(55_200_000_000), "55.2 GB")
        XCTAssertEqual(Fmt.bytes(8_000_000_000), "8 GB")
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
