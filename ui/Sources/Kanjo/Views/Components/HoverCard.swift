import SwiftUI
import KanjoCore

/// 悬停卡的外观（订阅额度卡、马赛克方块卡共用）：实底 + 材质、细描边、柔和阴影、圆角 10。
struct HoverCardChrome: ViewModifier {
    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: 10, style: .continuous)
        content
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(shape.fill(.regularMaterial)
                .background(shape.fill(Color(nsColor: .windowBackgroundColor).opacity(0.85))))
            .overlay(shape.strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5))
            .shadow(color: .black.opacity(0.18), radius: 10, y: 4)
    }
}

extension View {
    func hoverCard() -> some View { modifier(HoverCardChrome()) }
}

/// 悬停卡里的细进度条：浅底轨 + 彩色填充。
struct QuotaBar: View {
    let fraction: Double
    let color: Color
    var height: CGFloat = 4

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.08))
                if fraction > 0 {
                    Capsule().fill(color).frame(width: max(height, geo.size.width * min(fraction, 1)))
                }
            }
        }
        .frame(height: height)
    }
}

/// 马赛克方块的悬停卡：标题行（色点 + 名字 + 金额），下面一行总 token；
/// 每个 agent（「+N more」块则是每个项目）一行：色点、名字、金额 · token，下方按占比的彩色细条。
struct MosaicHoverCard: View {
    let tile: MosaicView.Tile
    let currency: String

    private struct Line: Identifiable {
        let id: String, label: String, color: Color, cost: Double, tokens: Int
    }

    var body: some View {
        let lines = self.lines
        let peak = max(lines.map(\.cost).max() ?? 0, 0)
        VStack(alignment: .leading, spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Circle().fill(tile.color).frame(width: 7, height: 7)
                    Text(title).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                    Spacer(minLength: 8)
                    Text(Fmt.money(tile.cost, currency: currency))
                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                }
                Text(L10n.tr("overview.tokens_count", Fmt.tokens(totalTokens)))
                    .font(.system(size: 10)).foregroundStyle(.secondary)
                    .padding(.leading, 13)
            }
            ForEach(lines.prefix(6)) { l in
                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Circle().fill(l.color).frame(width: 6, height: 6)
                        Text(l.label).font(.system(size: 11)).lineLimit(1)
                        Spacer(minLength: 8)
                        Text(Fmt.money(l.cost, currency: currency))
                            .font(.system(size: 11, weight: .medium, design: .rounded))
                        Text(L10n.tr("overview.tokens_count", Fmt.tokens(l.tokens)))
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                            .frame(minWidth: 62, alignment: .trailing)
                    }
                    QuotaBar(fraction: peak > 0 ? l.cost / peak : 0, color: l.color, height: 3)
                        .padding(.leading, 12)
                }
            }
            if lines.count > 6 {
                Text("+\(lines.count - 6)").font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
        .monospacedDigit()
        .hoverCard()
    }

    private var title: String {
        switch tile.kind {
        case .project(let p): return p.name
        case .more(let ps): return L10n.tr("mosaic.more.format", ps.count)
        }
    }

    private var totalTokens: Int {
        switch tile.kind {
        case .project(let p): return p.tokens.total
        case .more(let ps): return ps.reduce(0) { $0 + $1.tokens.total }
        }
    }

    private var lines: [Line] {
        let raw: [Line]
        switch tile.kind {
        case .project(let p):
            raw = p.byAgent.filter { $0.cost > 0 || $0.tokens.total > 0 }.map {
                Line(id: $0.agent, label: $0.label, color: AgentPalette.color(for: $0.agent),
                     cost: $0.cost, tokens: $0.tokens.total)
            }
        case .more(let ps):
            raw = ps.map { Line(id: $0.id, label: $0.name, color: ProjectTint.color(of: $0),
                                cost: $0.cost, tokens: $0.tokens.total) }
        }
        return raw.sorted { $0.cost != $1.cost ? $0.cost > $1.cost : $0.label < $1.label }
    }
}
