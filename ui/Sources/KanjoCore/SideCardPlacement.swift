import CoreGraphics

/// 侧边浮卡放在主面板的哪一侧。
public enum SideCardSide: Equatable {
    case left
    case right
}

/// 侧边浮卡布局结果：屏幕坐标系中的左下角原点、尺寸、所在侧及内部滚动高度上限。
public struct SideCardLayoutResult: Equatable {
    public let origin: CGPoint
    public let size: CGSize
    public let side: SideCardSide
    public let maxHeight: CGFloat?

    public init(origin: CGPoint, size: CGSize, side: SideCardSide, maxHeight: CGFloat?) {
        self.origin = origin
        self.size = size
        self.side = side
        self.maxHeight = maxHeight
    }
}

/// 侧边浮卡定位纯逻辑（AppKit 屏幕坐标系：左下角为原点，+Y 向上）。
public enum SideCardPlacement {
    /// 根据主面板窗口区域、触发行区域（屏幕坐标）、卡片自然尺寸与屏幕可见区域计算侧边浮卡的位置与高度上限。
    /// - Parameters:
    ///   - panelFrame: 主面板窗口在屏幕坐标系中的矩形。
    ///   - rowFrame: 触发行在屏幕坐标系中的矩形（顶部为 `maxY`）。
    ///   - cardSize: 卡片的自然尺寸。
    ///   - visibleFrame: 当前屏幕的 `visibleFrame`。
    ///   - gap: 卡片与主面板之间的水平间距（默认 8pt）。
    /// - Returns: 侧边浮卡的原点、尺寸、左右侧以及超屏高时的 `maxHeight`。
    public static func place(
        panelFrame: CGRect,
        rowFrame: CGRect,
        cardSize: CGSize,
        visibleFrame: CGRect,
        gap: CGFloat = 8
    ) -> SideCardLayoutResult {
        let maxAllowedHeight = max(1, visibleFrame.height)
        let naturalHeight = max(1, cardSize.height)
        let needsScroll = naturalHeight > maxAllowedHeight
        let effectiveHeight = needsScroll ? maxAllowedHeight : naturalHeight
        let maxHeight: CGFloat? = needsScroll ? maxAllowedHeight : nil

        let cardWidth = max(1, cardSize.width)
        let size = CGSize(width: cardWidth, height: effectiveHeight)

        // 水平方向：优先放主面板左侧；左侧不够时放到右侧；两侧都不足时选余量更大的一侧并钳制在可见区域内。
        let leftX = panelFrame.minX - gap - cardWidth
        let rightX = panelFrame.maxX + gap
        let leftFits = leftX >= visibleFrame.minX
        let rightFits = (rightX + cardWidth) <= visibleFrame.maxX

        let side: SideCardSide
        let rawX: CGFloat
        if leftFits {
            side = .left
            rawX = leftX
        } else if rightFits {
            side = .right
            rawX = rightX
        } else {
            let spaceLeft = panelFrame.minX - gap - visibleFrame.minX
            let spaceRight = visibleFrame.maxX - (panelFrame.maxX + gap)
            if spaceLeft >= spaceRight {
                side = .left
                rawX = leftX
            } else {
                side = .right
                rawX = rightX
            }
        }

        let minX = visibleFrame.minX
        let maxX = max(minX, visibleFrame.maxX - cardWidth)
        let x = min(max(rawX, minX), maxX)

        // 垂直方向：卡片顶部对齐行顶部（rowFrame.maxY），再钳制到屏幕可见区域内。
        let idealY = rowFrame.maxY - effectiveHeight
        let minY = visibleFrame.minY
        let maxY = max(minY, visibleFrame.maxY - effectiveHeight)
        let y = min(max(idealY, minY), maxY)

        return SideCardLayoutResult(
            origin: CGPoint(x: x, y: y),
            size: size,
            side: side,
            maxHeight: maxHeight
        )
    }
}
