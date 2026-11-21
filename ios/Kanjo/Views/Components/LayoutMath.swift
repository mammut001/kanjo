import CoreGraphics
import Foundation

/// Shared layout arithmetic for proportion bars. Keeps widths finite so SwiftUI
/// never logs "Invalid frame dimension (negative or non-finite)".
enum LayoutMath {
    /// Width for a filled proportion segment.
    /// - Returns `0` when `available` or `fraction` is non-finite, ≤ 0, or the product would be non-finite.
    /// - Otherwise returns `max(available * clamp(fraction, 0…1), min(minWidth, available))`.
    static func barWidth(available: CGFloat, fraction: Double, minWidth: CGFloat = 2) -> CGFloat {
        guard available.isFinite, available > 0,
              fraction.isFinite, fraction > 0 else { return 0 }
        let clamped = min(max(fraction, 0), 1)
        let raw = available * CGFloat(clamped)
        guard raw.isFinite else { return 0 }
        return max(raw, min(minWidth, available))
    }

    /// Split `available` across `weights` (e.g. token counts) without NaN or
    /// overflowing a zero/near-zero track. Zero and non-finite weights are skipped.
    static func segmentWidths(available: CGFloat, weights: [Double], gap: CGFloat = 1, minWidth: CGFloat = 2) -> [CGFloat] {
        guard available.isFinite, available > 0 else {
            return Array(repeating: 0, count: weights.count)
        }
        let positive = weights.map { w -> Double in
            guard w.isFinite, w > 0 else { return 0 }
            return w
        }
        let count = positive.filter { $0 > 0 }.count
        guard count > 0 else { return Array(repeating: 0, count: weights.count) }
        let gaps = gap * CGFloat(max(count - 1, 0))
        let track = max(available - gaps, 0)
        guard track > 0 else { return Array(repeating: 0, count: weights.count) }
        let total = positive.reduce(0, +)
        guard total > 0, total.isFinite else { return Array(repeating: 0, count: weights.count) }
        let floor = min(minWidth, track / CGFloat(count))
        return positive.map { w in
            guard w > 0 else { return 0 }
            let raw = track * CGFloat(w / total)
            guard raw.isFinite else { return 0 }
            return max(raw, floor)
        }
    }
}
