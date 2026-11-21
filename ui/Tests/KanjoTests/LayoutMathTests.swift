import CoreGraphics
import XCTest
@testable import KanjoCore

final class LayoutMathTests: KanjoTestCase {
    func testBarWidthRejectsZeroAndNonFinite() {
        XCTAssertEqual(LayoutMath.barWidth(available: 100, fraction: 0), 0)
        XCTAssertEqual(LayoutMath.barWidth(available: 100, fraction: .nan), 0)
        XCTAssertEqual(LayoutMath.barWidth(available: 100, fraction: .infinity), 0)
        XCTAssertEqual(LayoutMath.barWidth(available: 100, fraction: -.infinity), 0)
        XCTAssertEqual(LayoutMath.barWidth(available: 0, fraction: 0.5), 0)
        XCTAssertEqual(LayoutMath.barWidth(available: .nan, fraction: 0.5), 0)
        XCTAssertEqual(LayoutMath.barWidth(available: -10, fraction: 0.5), 0)
        let half = LayoutMath.barWidth(available: 100, fraction: 0.5)
        XCTAssertEqual(half, 50, accuracy: 0.01)
        XCTAssertTrue(half.isFinite)
    }

    func testBarWidthAppliesMinWidthOnlyWhenPositive() {
        let tiny = LayoutMath.barWidth(available: 100, fraction: 0.001, minWidth: 3)
        XCTAssertEqual(tiny, 3, accuracy: 0.01)
        XCTAssertEqual(LayoutMath.barWidth(available: 100, fraction: 0, minWidth: 3), 0)
        // Never exceed the track even when minWidth is large.
        XCTAssertEqual(LayoutMath.barWidth(available: 2, fraction: 0.01, minWidth: 8), 2, accuracy: 0.01)
    }

    func testSegmentWidthsWithZeroTotal() {
        let widths = LayoutMath.segmentWidths(available: 100, weights: [0, 0, 0])
        XCTAssertEqual(widths, [0, 0, 0])
        let mixed = LayoutMath.segmentWidths(available: 100, weights: [1, 0, .nan, 3])
        XCTAssertEqual(mixed.count, 4)
        XCTAssertEqual(mixed[1], 0)
        XCTAssertEqual(mixed[2], 0)
        XCTAssertTrue(mixed[0].isFinite && mixed[0] > 0)
        XCTAssertTrue(mixed[3].isFinite && mixed[3] > 0)
    }

    func testSegmentWidthsRejectsZeroOrNonFiniteTrack() {
        XCTAssertEqual(LayoutMath.segmentWidths(available: 0, weights: [1, 2]), [0, 0])
        XCTAssertEqual(LayoutMath.segmentWidths(available: .nan, weights: [1, 2]), [0, 0])
        XCTAssertEqual(LayoutMath.segmentWidths(available: -5, weights: [1, 2]), [0, 0])
    }

    func testSegmentHeightRejectsNonFinite() {
        XCTAssertEqual(LayoutMath.segmentHeight(available: 16, share: 0), 0)
        XCTAssertEqual(LayoutMath.segmentHeight(available: 16, share: .nan), 0)
        XCTAssertEqual(LayoutMath.segmentHeight(available: 0, share: 0.5), 0)
        XCTAssertEqual(LayoutMath.segmentHeight(available: 16, share: 0.5), 8, accuracy: 0.01)
    }

    /// Zero-cost agents / 0-byte disk rows must not paint a min-width ghost bar.
    func testZeroCostAndZeroBytesDoNotProduceGhostBars() {
        let maxCost = 0.0
        let agentFraction = maxCost > 0 ? 12.0 / maxCost : 0
        XCTAssertEqual(LayoutMath.barWidth(available: 200, fraction: agentFraction, minWidth: 3), 0)

        let maxBytes = 0
        let diskFraction = maxBytes > 0 ? Double(42) / Double(maxBytes) : 0
        XCTAssertEqual(LayoutMath.barWidth(available: 200, fraction: diskFraction, minWidth: 3), 0)

        let tokenWidths = LayoutMath.segmentWidths(available: 200, weights: [0, 0, 0, 0])
        XCTAssertEqual(tokenWidths, [0, 0, 0, 0])
    }
}
