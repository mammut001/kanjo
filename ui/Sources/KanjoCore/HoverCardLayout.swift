import CoreGraphics
import Foundation

/// 悬停卡布局纯逻辑：根据锚点矩形、卡片大小、容器大小及安全边距，计算卡片左上角原点。
public enum HoverCardLayout {
    /// 计算悬停卡在容器坐标系中的左上角原点。
    /// - Parameters:
    ///   - anchor: 锚点视图在容器坐标系中的矩形。
    ///   - cardSize: 悬停卡本身的大小。
    ///   - container: 容器大小（例如窗口或面板大小，360×620）。
    ///   - inset: 边缘安全边距（默认 16）。
    ///   - gap: 悬停卡与锚点之间的间距（默认 4）。
    /// - Returns: 悬停卡左上角在容器中的位置。
    public static func origin(
        anchor: CGRect,
        cardSize: CGSize,
        container: CGSize,
        inset: CGFloat = 16,
        gap: CGFloat = 4
    ) -> CGPoint {
        origin(
            anchor: anchor,
            cardSize: cardSize,
            container: container,
            horizontalInset: inset,
            verticalInset: inset,
            gap: gap
        )
    }

    /// 支持分别指定水平与垂直安全边距的布局计算。
    public static func origin(
        anchor: CGRect,
        cardSize: CGSize,
        container: CGSize,
        horizontalInset: CGFloat,
        verticalInset: CGFloat,
        gap: CGFloat = 4
    ) -> CGPoint {
        // 水平方向：默认左对齐锚点，并限制在安全边距内
        let minX = horizontalInset
        let maxX = max(minX, container.width - horizontalInset - cardSize.width)
        let x = min(max(anchor.minX, minX), maxX)

        // 垂直方向：默认置于锚点下方 gap 处
        let yBelow = anchor.maxY + gap
        let fitsBelow = (yBelow + cardSize.height) <= (container.height - verticalInset)

        // 向上翻转：置于锚点上方 gap 处
        let yAbove = anchor.minY - gap - cardSize.height
        let fitsAbove = yAbove >= verticalInset

        let y: CGFloat
        if fitsBelow {
            y = yBelow
        } else if fitsAbove {
            y = yAbove
        } else {
            // 当上下空间均不足时，尽可能居中/留在安全边距内
            let minY = verticalInset
            let maxY = max(minY, container.height - verticalInset - cardSize.height)
            y = min(max(yBelow, minY), maxY)
        }

        return CGPoint(x: x, y: y)
    }
}

/// 悬停卡数据行项与构建纯逻辑。
public struct HoverCardRowItem: Equatable, Identifiable {
    public let id: String
    public let label: String
    public let cost: Double
    public let tokens: Int
    public let fraction: Double

    public init(id: String, label: String, cost: Double, tokens: Int, fraction: Double) {
        self.id = id
        self.label = label
        self.cost = cost
        self.tokens = tokens
        self.fraction = fraction
    }
}

public enum HoverCardRowBuilder {
    /// 将 agent 列表按花费降序（花费相同时按名称升序）排序，并计算相对最大花费的比例。
    public static func agentRows(
        agents: [(agent: String, label: String, cost: Double, tokens: Int)]
    ) -> [HoverCardRowItem] {
        let filtered = agents.filter { $0.cost > 0 || $0.tokens > 0 }
        let sorted = filtered.sorted {
            if $0.cost != $1.cost {
                return $0.cost > $1.cost
            }
            return $0.label < $1.label
        }
        let peak = sorted.map(\.cost).max() ?? 0
        return sorted.map {
            HoverCardRowItem(
                id: $0.agent,
                label: $0.label,
                cost: $0.cost,
                tokens: $0.tokens,
                fraction: peak > 0 ? $0.cost / peak : 0
            )
        }
    }

    /// 计算 4 种 token 类型的构成比例（input, output, cacheRead, cacheWrite）。
    public static func tokenRows(tokens: Tokens) -> [(id: String, labelKey: String, count: Int, fraction: Double)] {
        let total = max(tokens.total, 1)
        let items: [(id: String, labelKey: String, count: Int)] = [
            ("input", "project.token.input", tokens.input),
            ("output", "project.token.output", tokens.output),
            ("cache_read", "project.token.cache_read", tokens.cacheRead),
            ("cache_write", "project.token.cache_write", tokens.cacheWrite),
        ]
        return items.filter { $0.count > 0 }.map {
            ($0.id, $0.labelKey, $0.count, Double($0.count) / Double(total))
        }
    }
}
