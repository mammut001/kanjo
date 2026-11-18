import XCTest
@testable import KanjoCore

final class SideCardPlacementTests: KanjoTestCase {
    private let visibleFrame = CGRect(x: 0, y: 40, width: 1440, height: 835)
    private let cardSize = CGSize(width: 340, height: 300)

    func testLeftPreferredAlignedWithRowTop() {
        let panelFrame = CGRect(x: 1000, y: 200, width: 360, height: 620)
        let rowFrame = CGRect(x: 1008, y: 700, width: 344, height: 48)

        let result = SideCardPlacement.place(
            panelFrame: panelFrame,
            rowFrame: rowFrame,
            cardSize: cardSize,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result.side, .left)
        XCTAssertEqual(result.origin.x, 1000 - 8 - 340)
        XCTAssertEqual(result.origin.y + result.size.height, rowFrame.maxY)
        XCTAssertEqual(result.origin.y, 748 - 300)
        XCTAssertEqual(result.size, cardSize)
        XCTAssertNil(result.maxHeight)
    }

    func testRightFallbackNearLeftScreenEdge() {
        let panelFrame = CGRect(x: 120, y: 200, width: 360, height: 620)
        let rowFrame = CGRect(x: 128, y: 650, width: 344, height: 40)

        let result = SideCardPlacement.place(
            panelFrame: panelFrame,
            rowFrame: rowFrame,
            cardSize: cardSize,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result.side, .right)
        XCTAssertEqual(result.origin.x, 120 + 360 + 8)
        XCTAssertEqual(result.origin.y + result.size.height, rowFrame.maxY)
        XCTAssertNil(result.maxHeight)
    }

    func testVerticalClampedAtBottom() {
        let panelFrame = CGRect(x: 1000, y: 60, width: 360, height: 620)
        let rowFrame = CGRect(x: 1008, y: 70, width: 344, height: 40)

        let result = SideCardPlacement.place(
            panelFrame: panelFrame,
            rowFrame: rowFrame,
            cardSize: cardSize,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result.origin.y, visibleFrame.minY)
        XCTAssertGreaterThanOrEqual(result.origin.y, visibleFrame.minY)
        XCTAssertLessThanOrEqual(result.origin.y + result.size.height, visibleFrame.maxY)
    }

    func testVerticalClampedAtTop() {
        let panelFrame = CGRect(x: 1000, y: 260, width: 360, height: 620)
        let rowFrame = CGRect(x: 1008, y: 860, width: 344, height: 30)

        let result = SideCardPlacement.place(
            panelFrame: panelFrame,
            rowFrame: rowFrame,
            cardSize: cardSize,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result.origin.y + result.size.height, visibleFrame.maxY)
        XCTAssertEqual(result.origin.y, visibleFrame.maxY - cardSize.height)
    }

    func testTallerThanScreenCapsMaxHeight() {
        let panelFrame = CGRect(x: 1000, y: 200, width: 360, height: 620)
        let rowFrame = CGRect(x: 1008, y: 600, width: 344, height: 40)
        let tallCard = CGSize(width: 340, height: 1100)

        let result = SideCardPlacement.place(
            panelFrame: panelFrame,
            rowFrame: rowFrame,
            cardSize: tallCard,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result.maxHeight, visibleFrame.height)
        XCTAssertEqual(result.size.height, visibleFrame.height)
        XCTAssertEqual(result.origin.y, visibleFrame.minY)
    }

    func testSecondaryDisplayOriginSupported() {
        let secondaryVisible = CGRect(x: -1920, y: 120, width: 1920, height: 1000)
        let panelFrame = CGRect(x: -1850, y: 300, width: 360, height: 620)
        let rowFrame = CGRect(x: -1842, y: 780, width: 344, height: 44)

        let result = SideCardPlacement.place(
            panelFrame: panelFrame,
            rowFrame: rowFrame,
            cardSize: cardSize,
            visibleFrame: secondaryVisible
        )

        XCTAssertEqual(result.side, .right)
        XCTAssertEqual(result.origin.x, -1850 + 360 + 8)
        XCTAssertEqual(result.origin.y + result.size.height, rowFrame.maxY)
    }
}
