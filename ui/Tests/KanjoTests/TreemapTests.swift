import CoreGraphics
import XCTest
@testable import KanjoCore

final class TreemapTests: XCTestCase {
    private let bounds = CGRect(x: 10, y: 20, width: 352, height: 150)
    private let eps: CGFloat = 1e-6

    private func sample() -> [(id: String, value: Double)] {
        [("a", 1198), ("b", 1035), ("c", 422), ("d", 237), ("e", 226), ("f", 162),
         ("g", 152), ("h", 149), ("i", 96), ("j", 72), ("k", 35), ("l", 25), ("zero", 0), ("neg", -3)]
    }

    func testAreaSumEqualsBounds() {
        let tiles = Treemap.layout(sample(), in: bounds)
        let sum = tiles.reduce(CGFloat(0)) { $0 + $1.rect.width * $1.rect.height }
        XCTAssertEqual(sum, bounds.width * bounds.height, accuracy: 1e-6)
    }

    func testAreasProportionalToValues() {
        let tiles = Treemap.layout(sample(), in: bounds)
        let total = tiles.reduce(0) { $0 + $1.value }
        for t in tiles {
            let expected = t.value / total * Double(bounds.width * bounds.height)
            XCTAssertEqual(Double(t.rect.width * t.rect.height), expected, accuracy: 1e-6, t.id)
        }
    }

    func testNonPositiveValuesExcludedAndSortedDescending() {
        let tiles = Treemap.layout(sample(), in: bounds)
        XCTAssertEqual(tiles.count, 12)
        XCTAssertFalse(tiles.contains { $0.id == "zero" || $0.id == "neg" })
        XCTAssertEqual(tiles.map(\.value), tiles.map(\.value).sorted(by: >))
    }

    func testTilesInsideBounds() {
        for t in Treemap.layout(sample(), in: bounds) {
            XCTAssertGreaterThanOrEqual(t.rect.minX, bounds.minX - eps, t.id)
            XCTAssertGreaterThanOrEqual(t.rect.minY, bounds.minY - eps, t.id)
            XCTAssertLessThanOrEqual(t.rect.maxX, bounds.maxX + eps, t.id)
            XCTAssertLessThanOrEqual(t.rect.maxY, bounds.maxY + eps, t.id)
            XCTAssertGreaterThan(t.rect.width, 0, t.id)
            XCTAssertGreaterThan(t.rect.height, 0, t.id)
        }
    }

    func testTilesDoNotOverlap() {
        let tiles = Treemap.layout(sample(), in: bounds)
        for i in tiles.indices {
            for j in tiles.indices where j > i {
                let inter = tiles[i].rect.intersection(tiles[j].rect)
                let area = inter.isNull ? 0 : inter.width * inter.height
                XCTAssertLessThan(area, 1e-6, "\(tiles[i].id) overlaps \(tiles[j].id)")
            }
        }
    }

    func testSingleItemFillsBounds() {
        let tiles = Treemap.layout([("only", 5)], in: bounds)
        XCTAssertEqual(tiles.count, 1)
        XCTAssertEqual(tiles[0].rect, bounds)
    }

    func testEmptyAndAllNonPositiveInput() {
        XCTAssertTrue(Treemap.layout([(id: String, value: Double)](), in: bounds).isEmpty)
        XCTAssertTrue(Treemap.layout([("a", 0), ("b", -1)], in: bounds).isEmpty)
    }

    func testZeroSizedBoundsDoesNotCrash() {
        let tiles = Treemap.layout([("a", 1), ("b", 2)], in: .zero)
        XCTAssertEqual(tiles.count, 2)
        XCTAssertTrue(tiles.allSatisfy { $0.rect.size == .zero })
    }

    func testEqualValuesAreReasonablySquare() {
        let items = (0..<4).map { (id: "\($0)", value: 1.0) }
        let tiles = Treemap.layout(items, in: CGRect(x: 0, y: 0, width: 100, height: 100))
        for t in tiles {
            XCTAssertEqual(t.rect.width, 50, accuracy: 1e-6)
            XCTAssertEqual(t.rect.height, 50, accuracy: 1e-6)
        }
    }

    func testGroupSmall() {
        let g = Treemap.groupSmall([("big", 90), ("mid", 8.6), ("s1", 1), ("s2", 0.4), ("z", 0)], threshold: 0.015)
        XCTAssertEqual(g.kept.map(\.id), ["big", "mid"])
        XCTAssertEqual(g.merged, ["s1", "s2"])
        XCTAssertEqual(g.mergedValue, 1.4, accuracy: 1e-9)
    }

    func testGroupSmallKeepsLoneSmallItem() {
        let g = Treemap.groupSmall([("big", 99), ("s1", 1)], threshold: 0.015)
        XCTAssertEqual(g.kept.map(\.id), ["big", "s1"])
        XCTAssertTrue(g.merged.isEmpty)
        XCTAssertEqual(g.mergedValue, 0)
    }

    func testGroupSmallEmpty() {
        let g = Treemap.groupSmall([(id: String, value: Double)](), threshold: 0.015)
        XCTAssertTrue(g.kept.isEmpty && g.merged.isEmpty)
    }
}
