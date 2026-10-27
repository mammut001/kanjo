import XCTest
@testable import KanjoCore

final class HoverCardLayoutTests: KanjoTestCase {
    private let container = CGSize(width: 360, height: 620)
    private let cardSize = CGSize(width: 200, height: 80)
    private let inset: CGFloat = 16
    private let gap: CGFloat = 4

    func testBelowByDefault() {
        // 锚点位于面板上方，下方空间充裕
        let anchor = CGRect(x: 30, y: 50, width: 100, height: 30)
        let pt = HoverCardLayout.origin(
            anchor: anchor,
            cardSize: cardSize,
            container: container,
            inset: inset,
            gap: gap
        )

        // 水平对齐 anchor.minX = 30
        XCTAssertEqual(pt.x, 30)
        // 垂直默认在下方：anchor.maxY (80) + gap (4) = 84
        XCTAssertEqual(pt.y, 84)
        // 确认在安全区域内
        XCTAssertGreaterThanOrEqual(pt.x, inset)
        XCTAssertLessThanOrEqual(pt.x + cardSize.width, container.width - inset)
        XCTAssertLessThanOrEqual(pt.y + cardSize.height, container.height - inset)
    }

    func testFlipsAboveNearBottom() {
        // 锚点靠近面板底部，下方空间不足
        let anchor = CGRect(x: 30, y: 560, width: 100, height: 30)
        let pt = HoverCardLayout.origin(
            anchor: anchor,
            cardSize: cardSize,
            container: container,
            inset: inset,
            gap: gap
        )

        // 水平对齐 anchor.minX = 30
        XCTAssertEqual(pt.x, 30)
        // 下方放不下（590 + 4 + 80 = 674 > 620 - 16），应向上翻转
        // 上方：anchor.minY (560) - gap (4) - cardSize.height (80) = 476
        XCTAssertEqual(pt.y, 476)
        XCTAssertGreaterThanOrEqual(pt.y, inset)
    }

    func testClampedLeftAndRight() {
        // 锚点过于靠左（小于 inset）
        let leftAnchor = CGRect(x: 5, y: 100, width: 50, height: 20)
        let leftPt = HoverCardLayout.origin(
            anchor: leftAnchor,
            cardSize: cardSize,
            container: container,
            inset: inset,
            gap: gap
        )
        XCTAssertEqual(leftPt.x, inset)

        // 锚点过于靠右（cardSize.width 超出右边距）
        let rightAnchor = CGRect(x: 250, y: 100, width: 50, height: 20)
        let rightPt = HoverCardLayout.origin(
            anchor: rightAnchor,
            cardSize: cardSize,
            container: container,
            inset: inset,
            gap: gap
        )
        // 容器宽 360 - 16 - 200 = 144
        XCTAssertEqual(rightPt.x, 144)
        XCTAssertEqual(rightPt.x + cardSize.width, container.width - inset)
    }

    func testStaysInsideWhenNeitherFits() {
        // 容器高度很矮（例如 180），卡片高 100，锚点居中于 (30, 40, 100, 100)
        let smallContainer = CGSize(width: 360, height: 180)
        let tallCard = CGSize(width: 200, height: 100)
        let midAnchor = CGRect(x: 30, y: 40, width: 100, height: 100)

        let pt = HoverCardLayout.origin(
            anchor: midAnchor,
            cardSize: tallCard,
            container: smallContainer,
            inset: inset,
            gap: gap
        )

        // 下方：140 + 4 + 100 = 244 > 180 - 16
        // 上方：40 - 4 - 100 = -64 < 16
        // 上下都放不下，仍应被限制在安全区域 [inset, container.height - inset - cardSize.height]
        XCTAssertGreaterThanOrEqual(pt.y, inset)
        XCTAssertLessThanOrEqual(pt.y + tallCard.height, smallContainer.height - inset)
    }

    func testHoverCardRowBuilderAgentRows() {
        let rawAgents: [(agent: String, label: String, cost: Double, tokens: Int)] = [
            ("cursor", "Cursor", 10.0, 100),
            ("claude", "Claude Code", 30.0, 300),
            ("zero", "Zero Cost", 0.0, 0),
            ("codegpt", "CodeGPT", 20.0, 200),
        ]

        let rows = HoverCardRowBuilder.agentRows(agents: rawAgents)
        // 过滤掉花费与 token 均为 0 的项
        XCTAssertEqual(rows.count, 3)

        // 验证降序排序：Claude (30) -> CodeGPT (20) -> Cursor (10)
        XCTAssertEqual(rows[0].id, "claude")
        XCTAssertEqual(rows[1].id, "codegpt")
        XCTAssertEqual(rows[2].id, "cursor")

        // 验证比例：相对于 peak = 30
        XCTAssertEqual(rows[0].fraction, 1.0, accuracy: 0.0001)
        XCTAssertEqual(rows[1].fraction, 20.0 / 30.0, accuracy: 0.0001)
        XCTAssertEqual(rows[2].fraction, 10.0 / 30.0, accuracy: 0.0001)
    }

    func testHoverCardRowBuilderTokenRows() {
        let tokens = Tokens(input: 400, output: 200, cacheRead: 300, cacheWrite: 100, thinking: 50, total: 1000)
        let rows = HoverCardRowBuilder.tokenRows(tokens: tokens)

        XCTAssertEqual(rows.count, 4)
        let inputRow = rows.first { $0.id == "input" }
        XCTAssertNotNil(inputRow)
        XCTAssertEqual(inputRow?.count, 400)
        XCTAssertEqual(inputRow?.fraction ?? 0, 0.4, accuracy: 0.0001)

        let outputRow = rows.first { $0.id == "output" }
        XCTAssertNotNil(outputRow)
        XCTAssertEqual(outputRow?.count, 200)
        XCTAssertEqual(outputRow?.fraction ?? 0, 0.2, accuracy: 0.0001)
    }
}
