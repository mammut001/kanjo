import KanjoCore
import SwiftUI
import UIKit

/// 总览的马赛克：每个项目一块，面积 = 花费，颜色 = 主力 agent。
/// 和 Mac 的 MosaicView 一样的合并规则：小于总面积 1.5% 的项目并成一块灰色「+N」。
struct ProjectMosaic: View {
    let projects: [FilteredProject]
    let report: UsageReport
    let range: TimeRange
    let currency: String

    static let height: CGFloat = 160
    static let gap: CGFloat = 2
    static let mergeThreshold = 0.015
    private static let moreID = "\u{0}more"

    struct Tile: Identifiable {
        enum Kind {
            case project(FilteredProject)
            case more([FilteredProject])
        }

        let id: String
        let kind: Kind
        let cost: Double
        let rect: CGRect

        var color: Color {
            switch kind {
            case .project(let item):
                return dominantAgent(item.byAgent).map { IOSPalette.agent($0.agent) } ?? IOSPalette.neutral
            case .more:
                return IOSPalette.neutral
            }
        }

        var names: [String] {
            switch kind {
            case .project(let item):
                return [item.project.name]
            case .more(let items):
                return [L10n.tr("mosaic.more.format", items.count), "+\(items.count)"]
            }
        }
    }

    var body: some View {
        GeometryReader { geo in
            let tiles = Self.tiles(projects, size: geo.size)
            ZStack(alignment: .topLeading) {
                ForEach(tiles) { tile in
                    tileView(tile)
                        .frame(width: tile.rect.width, height: tile.rect.height)
                        .position(x: tile.rect.midX, y: tile.rect.midY)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
        }
        .frame(height: Self.height)
    }

    @ViewBuilder
    private func tileView(_ tile: Tile) -> some View {
        switch tile.kind {
        case .project(let item):
            NavigationLink {
                ProjectDetailView(project: item.project, report: report, range: range)
            } label: {
                tileBody(tile)
            }
            .buttonStyle(.plain)
        case .more:
            tileBody(tile)
        }
    }

    private func tileBody(_ tile: Tile) -> some View {
        let shape = RoundedRectangle(cornerRadius: 4, style: .continuous)
        return ZStack(alignment: .topLeading) {
            shape.fill(tile.color)
            MosaicLabel(tile: tile, currency: currency)
        }
        .frame(width: tile.rect.width, height: tile.rect.height)
        .clipShape(shape)
        .contentShape(shape)
    }

    static func tiles(_ projects: [FilteredProject], size: CGSize) -> [Tile] {
        let byID = Dictionary(projects.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        let grouped = Treemap.groupSmall(projects.map { (id: $0.id, value: $0.cost) },
                                         threshold: mergeThreshold)
        var items: [(id: String, value: Double)] = grouped.kept
        if !grouped.merged.isEmpty {
            items.append((id: moreID, value: grouped.mergedValue))
        }
        let half = gap / 2
        let bounds = CGRect(origin: .zero, size: size).insetBy(dx: -half, dy: -half)
        return Treemap.layout(items, in: bounds).compactMap { t in
            let rect = t.rect.insetBy(dx: half, dy: half)
            guard rect.width > 0.5, rect.height > 0.5 else { return nil }
            if t.id == moreID {
                let merged = grouped.merged.compactMap { byID[$0] }
                return Tile(id: t.id, kind: .more(merged), cost: t.value, rect: rect)
            }
            guard let project = byID[t.id] else { return nil }
            return Tile(id: t.id, kind: .project(project), cost: t.value, rect: rect)
        }
    }
}

private struct MosaicLabel: View {
    let tile: ProjectMosaic.Tile
    let currency: String

    private static let minWidth: CGFloat = 72
    private static let fullHeight: CGFloat = 40
    private static let padX: CGFloat = 6
    private static let padTop: CGFloat = 5
    private static let nameFont = UIFont.systemFont(ofSize: 11, weight: .semibold)
    private static let amountFont = UIFont.monospacedDigitSystemFont(ofSize: 10, weight: .regular)
    private static let ink = Color.white.opacity(0.92)

    var body: some View {
        let amount = Fmt.money(tile.cost, currency: currency)
        let fit = Self.fit(names: tile.names, amount: amount, size: tile.rect.size)
        VStack(alignment: .leading, spacing: 1) {
            if let name = fit.name {
                Text(name)
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(1)
                    .fixedSize()
            }
            if fit.amount {
                Text(amount)
                    .font(.system(size: 10).monospacedDigit())
                    .lineLimit(1)
                    .fixedSize()
            }
        }
        .foregroundColor(Self.ink)
        .shadow(color: .black.opacity(0.25), radius: 1, x: 0, y: 0.5)
        .padding(.horizontal, Self.padX)
        .padding(.top, Self.padTop)
        .frame(width: tile.rect.width, height: tile.rect.height, alignment: .topLeading)
        .clipped()
    }

    static func fit(names: [String], amount: String, size: CGSize) -> (name: String?, amount: Bool) {
        guard size.width >= minWidth, size.height >= 20 else { return (nil, false) }
        let available = size.width - padX * 2
        let width = { (text: String, font: UIFont) in
            ceil((text as NSString).size(withAttributes: [.font: font]).width)
        }
        guard let name = names.first(where: { width($0, nameFont) <= available }) else {
            return (nil, false)
        }
        let showAmount = size.height >= fullHeight && width(amount, amountFont) <= available
        return (name, showAmount)
    }
}
