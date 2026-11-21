import XCTest
@testable import KanjoCore

final class LocalizationArgumentOrderTests: KanjoTestCase {
    /// 调用方按 (百分比, 套餐名) 传参；中文模板需用显式序号把套餐名放在前面。
    func testCycleShareChineseUsesPercentThenPlanArguments() {
        XCTAssertEqual(
            L10n.tr("project.cycle_share", language: "zh-Hans", "37%", "Claude Max 5x"),
            "此仓库：占本账期 Claude Max 5x 用量的 37%")
        XCTAssertEqual(
            L10n.tr("project.cycle_share", language: "en", "37%", "Claude Max 5x"),
            "This repo: 37% of your Claude Max 5x usage this cycle")
    }
}
