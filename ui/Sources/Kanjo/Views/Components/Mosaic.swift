import AppKit
import SwiftUI
import KanjoCore

/// 项目的代表色：by_agent 里占比最大的 agent 的颜色（全饱和，不按占比降饱和）；没有花费时中性灰。
enum ProjectTint {
    static func color(of p: Project) -> Color {
        dominantAgent(p.byAgent).map { AgentPalette.color(for: $0.agent) } ?? AgentPalette.neutral
    }
}

/// 总览的马赛克：每个项目一块，面积 = 花费，颜色 = 主力 agent（全饱和）。
/// 小于总面积 1.5% 的项目合并成一块灰色「+N more」。圆角 4、间距 2、不描边。
struct MosaicView: View {
    static let height: CGFloat = 160
    static let gap: CGFloat = 2
    static let mergeThreshold = 0.015

    let projects: [Project]
    let currency: String
    let onSelect: (String) -> Void
    @State private var hovered: String?

    struct Tile: Identifiable {
        enum Kind { case project(Project), more([Project]) }
        let id: String
        let kind: Kind
        let cost: Double
        let rect: CGRect
    }

    var body: some View {
        GeometryReader { geo in
            let tiles = Self.tiles(projects, size: geo.size)
            ZStack(alignment: .topLeading) {
                ZStack(alignment: .topLeading) {
                    ForEach(tiles) { t in
                        MosaicTileView(tile: t, currency: currency, onSelect: onSelect,
                                       onHover: { h in
                                           if h { hovered = t.id } else if hovered == t.id { hovered = nil }
                                       })
                            .frame(width: t.rect.width, height: t.rect.height)
                            .position(x: t.rect.midX, y: t.rect.midY)
                    }
                }
                .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
                // 颜色层和文字单独叠在玻璃上面：放进玻璃内容里会被系统按 vibrancy 处理，
                // 文字在浅色模式下看不清，窗口失焦时颜色也会被洗掉。
                Group {
                    ForEach(tiles) { t in
                        MosaicWash(color: t.color, hover: hovered == t.id && t.isProject)
                            .frame(width: t.rect.width, height: t.rect.height)
                            .position(x: t.rect.midX, y: t.rect.midY)
                    }
                    ForEach(tiles) { t in
                        MosaicLabel(tile: t, currency: currency)
                            .frame(width: t.rect.width, height: t.rect.height)
                            .position(x: t.rect.midX, y: t.rect.midY)
                    }
                }
                .allowsHitTesting(false)
                .animation(.easeOut(duration: 0.12), value: hovered)
            }
        }
        .frame(height: Self.height)
    }

    private static let moreID = "\u{0}more"

    static func tiles(_ projects: [Project], size: CGSize) -> [Tile] {
        let byID = Dictionary(projects.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        let grouped = Treemap.groupSmall(projects.map { (id: $0.id, value: $0.cost) }, threshold: mergeThreshold)
        var items = grouped.kept
        if !grouped.merged.isEmpty { items.append((id: moreID, value: grouped.mergedValue)) }
        // 先在外扩 gap/2 的矩形里铺，再把每块内缩 gap/2：块间距 = gap，外缘与容器齐平。
        let half = gap / 2
        let bounds = CGRect(origin: .zero, size: size).insetBy(dx: -half, dy: -half)
        return Treemap.layout(items, in: bounds).compactMap { t in
            let r = t.rect.insetBy(dx: half, dy: half)
            guard r.width > 0.5, r.height > 0.5 else { return nil }
            if t.id == moreID {
                let merged = grouped.merged.compactMap { byID[$0] }
                return Tile(id: t.id, kind: .more(merged), cost: t.value, rect: r)
            }
            guard let p = byID[t.id] else { return nil }
            return Tile(id: t.id, kind: .project(p), cost: t.value, rect: r)
        }
    }
}

extension MosaicView.Tile {
    var isProject: Bool {
        if case .project = kind { return true }
        return false
    }

    /// 方块上可用的名字，从长到短；放不下长的就试短的。
    var names: [String] {
        switch kind {
        case .project(let p): return [p.name]
        case .more(let ps): return [L10n.tr("mosaic.more.format", ps.count), "+\(ps.count)"]
        }
    }

    var color: Color {
        switch kind {
        case .project(let p): return ProjectTint.color(of: p)
        case .more: return AgentPalette.neutral
        }
    }

    func help(currency: String) -> String {
        switch kind {
        case .project(let p):
            let lead = dominantAgent(p.byAgent).map { L10n.tr("mosaic.mostly", $0.label, Fmt.percent($0.share)) } ?? ""
            return "\(p.name) · \(Fmt.money(p.cost, currency: currency))\(lead)"
        case .more(let ps):
            return L10n.tr("mosaic.smaller_projects", ps.count, Fmt.money(cost, currency: currency))
                + ps.map { "\($0.name)  \(Fmt.money($0.cost, currency: currency))" }.joined(separator: "\n")
        }
    }
}

/// 一块方块的底（玻璃 / 实色）+ 点击 + tooltip。颜色层、悬停提亮和文字在上面单独画。
private struct MosaicTileView: View {
    let tile: MosaicView.Tile
    let currency: String
    let onSelect: (String) -> Void
    let onHover: (Bool) -> Void

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: MosaicTile.cornerRadius, style: .continuous)
        let base = Color.clear
            .frame(width: tile.rect.width, height: tile.rect.height)
            .contentShape(shape)
        Group {
            if case .project(let p) = tile.kind {
                Button { onSelect(p.id) } label: { base }
                    .buttonStyle(.plain)
            } else {
                base
            }
        }
        .mosaicTile(color: tile.color)
        .onHover(perform: onHover)
        .help(tile.help(currency: currency))
    }
}

/// 方块左上角的名字和金额。规则（绝不截断、不出现省略号）：
/// - 宽 ≥ 72 且高 ≥ 40：名字 + 金额（金额放不下就只画名字）；
/// - 宽 ≥ 72 但高 < 40：只画名字一行；
/// - 更小：什么都不画；
/// - 名字按实际字宽测量，放不下就整块不画（「+N more」先试短写「+N」）。
/// 全名和金额始终在方块的 `.help` 里。
private struct MosaicLabel: View {
    let tile: MosaicView.Tile
    let currency: String

    static let minWidth: CGFloat = 72, fullHeight: CGFloat = 40
    private static let nameFont = NSFont.systemFont(ofSize: 11, weight: .semibold)
    private static let amountFont = NSFont.monospacedDigitSystemFont(ofSize: 10, weight: .regular)
    private static let padX: CGFloat = 6, padTop: CGFloat = 5
    private static let ink = Color.white.opacity(0.92)

    var body: some View {
        let amount = Fmt.money(tile.cost, currency: currency)
        let fit = Self.fit(names: tile.names, amount: amount, size: tile.rect.size)
        VStack(alignment: .leading, spacing: 1) {
            if let name = fit.name {
                Text(name)
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(1).fixedSize()
            }
            if fit.amount {
                Text(amount)
                    .font(.system(size: 10).monospacedDigit())
                    .lineLimit(1).fixedSize()
            }
        }
        .foregroundColor(Self.ink)
        .shadow(color: .black.opacity(0.25), radius: 1, x: 0, y: 0.5)
        .padding(.horizontal, Self.padX).padding(.top, Self.padTop)
        .frame(width: tile.rect.width, height: tile.rect.height, alignment: .topLeading)
        .clipped()
    }

    static func fit(names: [String], amount: String, size: CGSize) -> (name: String?, amount: Bool) {
        guard size.width >= minWidth, size.height >= 20 else { return (nil, false) }
        let avail = size.width - padX * 2
        let width = { (s: String, f: NSFont) in ceil((s as NSString).size(withAttributes: [.font: f]).width) }
        guard let name = names.first(where: { width($0, nameFont) <= avail }) else { return (nil, false) }
        let showAmount = size.height >= fullHeight && width(amount, amountFont) <= avail
        return (name, showAmount)
    }
}
