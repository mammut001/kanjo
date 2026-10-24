import CoreGraphics
import Foundation

// Squarified treemap（Bruls, Huizing, van Wijk 2000）。纯函数，不依赖 SwiftUI。
// 按 value 降序逐行铺排：每一行沿当前剩余矩形的短边排列，只要加入下一个块
// 不会让这一行里最差的长宽比变得更差就继续加；否则把这一行定下来，剩余矩形缩小后重复。

public enum Treemap {
    public struct Tile<ID: Hashable>: Equatable {
        public var id: ID
        public var value: Double
        public var rect: CGRect
    }

    /// 把 `items` 铺进 `rect`。value ≤ 0（或非有限值）的不参与。
    /// 结果按 value 降序（同值保持输入顺序），面积与 value 成正比，铺满 `rect`、互不重叠。
    public static func layout<ID: Hashable>(_ items: [(id: ID, value: Double)], in rect: CGRect) -> [Tile<ID>] {
        let positive = items.enumerated()
            .filter { $0.element.value > 0 && $0.element.value.isFinite }
            .sorted { $0.element.value != $1.element.value ? $0.element.value > $1.element.value : $0.offset < $1.offset }
            .map { $0.element }
        guard !positive.isEmpty else { return [] }

        let total = positive.reduce(0) { $0 + $1.value }
        let area = Double(rect.width * rect.height)
        guard area > 0, rect.width.isFinite, rect.height.isFinite else {
            return positive.map { Tile(id: $0.id, value: $0.value, rect: CGRect(origin: rect.origin, size: .zero)) }
        }
        // 把 value 缩放成面积。
        let scaled = positive.map { (id: $0.id, value: $0.value, area: $0.value / total * area) }

        var result: [Tile<ID>] = []
        result.reserveCapacity(scaled.count)
        var free = rect
        var start = 0
        while start < scaled.count {
            let side = Double(min(free.width, free.height))
            // 贪心地扩展这一行。
            var end = start + 1
            var rowArea = scaled[start].area
            var rowMax = scaled[start].area, rowMin = scaled[start].area
            var best = worst(sum: rowArea, max: rowMax, min: rowMin, side: side)
            while end < scaled.count {
                let a = scaled[end].area
                let s = rowArea + a, mx = Swift.max(rowMax, a), mn = Swift.min(rowMin, a)
                let w = worst(sum: s, max: mx, min: mn, side: side)
                if w > best { break }
                best = w; rowArea = s; rowMax = mx; rowMin = mn; end += 1
            }
            let isLast = end == scaled.count
            let row = scaled[start..<end]

            if free.width >= free.height {
                // 竖着放在左侧一列。最后一行吃掉全部剩余宽度，消除浮点误差。
                let colW = isLast ? free.width : CGFloat(rowArea / Double(free.height))
                var y = free.minY
                for (k, item) in row.enumerated() {
                    let h = k == row.count - 1 ? free.maxY - y : CGFloat(item.area / Double(colW))
                    result.append(Tile(id: item.id, value: item.value,
                                       rect: CGRect(x: free.minX, y: y, width: colW, height: h)))
                    y += h
                }
                free = CGRect(x: free.minX + colW, y: free.minY, width: max(free.width - colW, 0), height: free.height)
            } else {
                // 横着放在顶部一行。
                let rowH = isLast ? free.height : CGFloat(rowArea / Double(free.width))
                var x = free.minX
                for (k, item) in row.enumerated() {
                    let w = k == row.count - 1 ? free.maxX - x : CGFloat(item.area / Double(rowH))
                    result.append(Tile(id: item.id, value: item.value,
                                       rect: CGRect(x: x, y: free.minY, width: w, height: rowH)))
                    x += w
                }
                free = CGRect(x: free.minX, y: free.minY + rowH, width: free.width, height: max(free.height - rowH, 0))
            }
            start = end
        }
        return result
    }

    /// 一行里最差（最大）的长宽比。
    private static func worst(sum: Double, max: Double, min: Double, side: Double) -> Double {
        guard sum > 0, side > 0, min > 0 else { return .infinity }
        let s2 = sum * sum, w2 = side * side
        return Swift.max(w2 * max / s2, s2 / (w2 * min))
    }

    /// 合并小块：占总值比例小于 `threshold` 的项合并成一组（只有一个时不合并，原样保留）。
    /// value ≤ 0 的项直接丢弃。`kept` 保持输入顺序。
    public static func groupSmall<ID: Hashable>(_ items: [(id: ID, value: Double)], threshold: Double)
        -> (kept: [(id: ID, value: Double)], merged: [ID], mergedValue: Double) {
        let positive = items.filter { $0.value > 0 && $0.value.isFinite }
        let total = positive.reduce(0) { $0 + $1.value }
        guard total > 0 else { return ([], [], 0) }
        let small = positive.filter { $0.value / total < threshold }
        guard small.count >= 2 else { return (positive, [], 0) }
        let smallIDs = Set(small.map(\.id))
        return (positive.filter { !smallIDs.contains($0.id) },
                small.map(\.id),
                small.reduce(0) { $0 + $1.value })
    }
}
