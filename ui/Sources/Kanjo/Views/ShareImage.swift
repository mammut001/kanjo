import SwiftUI
import KanjoCore

struct ShareImage: View {
    let summary: ShareSummary
    let agentId: String?

    var body: some View {
        if let id = agentId, let row = summary.agentRows.first(where: { $0.agent == id }) {
            SingleImageView(row: row, summary: summary)
        } else {
            MultiImageView(summary: summary)
        }
    }
    
    public static func copy(report: UsageReport, rangeRaw: String, agentId: String?, hiddenProjects: Set<String>) -> Bool {
        let summary = ShareSummary.build(report: report, rangeRaw: rangeRaw, hiddenProjects: hiddenProjects)
        let renderer = ImageRenderer(content: ShareImage(summary: summary, agentId: agentId))
        renderer.scale = 2.0
        if let nsImage = renderer.nsImage {
            ShareImageExporter.copyToPasteboard(image: nsImage)
            return true
        }
        return false
    }
}

struct MultiImageView: View {
    let summary: ShareSummary

    var body: some View {
        VStack(spacing: 18) {
            header
            
            HStack(alignment: .top, spacing: 16) {
                // Left: Mosaic
                VStack(alignment: .leading, spacing: 8) {
                    Text(L10n.tr("share.top_projects")).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    ShareMosaic(projects: summary.mosaicProjects, size: CGSize(width: 350, height: 230))
                        .frame(width: 350, height: 230)
                }
                .frame(width: 350)
                
                // Right: Agent bar + Legend
                VStack(alignment: .leading, spacing: 12) {
                    Text(L10n.tr("share.agents")).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    ForEach(summary.agentRows, id: \.agent) { row in
                        HStack {
                            Circle().fill(AgentPalette.color(for: row.agent)).frame(width: 8, height: 8)
                            Text(row.label).font(.system(size: 12))
                            Spacer()
                            Text(Fmt.tokens(row.tokens)).font(.system(size: 12, design: .monospaced))
                        }
                    }
                }
                .frame(width: 250)
            }
            
            // Bottom stat chips
            HStack(spacing: 12) {
                Text(L10n.tr("share.input") + ": " + Fmt.tokens(summary.totals.input))
                Text(L10n.tr("share.output") + ": " + Fmt.tokens(summary.totals.output))
            }
            .font(.system(size: 10)).foregroundStyle(.secondary)
            
            footer
        }
        .padding(18)
        .frame(width: 640)
        .background(Color(white: 0.11))
        .environment(\.colorScheme, .dark)
    }

    private var header: some View {
        HStack {
            if let icon = BrandIcon.image ?? NSApp?.applicationIconImage {
                Image(nsImage: icon)
                    .resizable().frame(width: 28, height: 28)
            }
            VStack(alignment: .leading) {
                Text(verbatim: "Kanjo").font(.system(size: 15, weight: .semibold))
                Text(summary.rangeLabel).font(.system(size: 11)).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing) {
                HeroAmount(value: Fmt.money(summary.totals.cost), size: 24)
                Text(L10n.tr("share.tokens_sessions", Fmt.tokens(summary.totals.tokens), summary.totals.sessions))
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }
        }
    }
    
    private var footer: some View {
        HStack {
            Text(L10n.tr("share.updated_format", Fmt.clock(summary.updated)))
            Spacer()
            Text("github.com/mammut001/kanjo").font(.system(size: 10, design: .monospaced))
        }
        .font(.system(size: 10))
        .foregroundStyle(.secondary)
    }
}

struct ShareMosaic: View {
    let projects: [Project]
    let size: CGSize
    
    var body: some View {
        let tiles = MosaicView.tiles(projects, size: size)
        ZStack(alignment: .topLeading) {
            ForEach(tiles) { tile in
                ZStack(alignment: .topLeading) {
                    RoundedRectangle(cornerRadius: 4).fill(tile.color)
                    if tile.rect.width >= 56 && tile.rect.height >= 30 {
                        VStack(alignment: .leading, spacing: 0) {
                            Text(name(for: tile)).font(.system(size: 11, weight: .semibold)).foregroundStyle(.white).lineLimit(1)
                            Text(Fmt.money(tile.cost)).font(.system(size: 10, design: .monospaced)).foregroundStyle(.white.opacity(0.8)).lineLimit(1)
                        }
                        .padding(6)
                    }
                }
                .frame(width: tile.rect.width, height: tile.rect.height)
                .position(x: tile.rect.midX, y: tile.rect.midY)
            }
        }
        .frame(width: size.width, height: size.height, alignment: .topLeading)
        .clipped()
    }
    
    func name(for tile: MosaicView.Tile) -> String {
        switch tile.kind {
        case .project(let p): return p.name
        case .more(let ps): return "+\(ps.count)"
        }
    }
}

struct SingleMosaic: View {
    let projects: [(name: String, cost: Double)]
    let agentColor: Color
    let size: CGSize
    
    var body: some View {
        let maxCost = projects.map(\.cost).max() ?? 1
        let items = projects.enumerated().map { (id: $0.offset, value: $0.element.cost) }
        let tiles = Treemap.layout(items, in: CGRect(origin: .zero, size: size))
        
        ZStack(alignment: .topLeading) {
            ForEach(0..<tiles.count, id: \.self) { i in
                let tile = tiles[i]
                let p = projects[tile.id]
                ZStack(alignment: .topLeading) {
                    RoundedRectangle(cornerRadius: 4)
                        .fill(agentColor.opacity(0.55 + 0.45 * (p.cost / maxCost)))
                    if tile.rect.width >= 56 && tile.rect.height >= 30 {
                        VStack(alignment: .leading, spacing: 0) {
                            Text(p.name).font(.system(size: 11, weight: .semibold)).foregroundStyle(.white).lineLimit(1)
                            Text(Fmt.money(p.cost)).font(.system(size: 10, design: .monospaced)).foregroundStyle(.white.opacity(0.8)).lineLimit(1)
                        }
                        .padding(6)
                    }
                }
                .frame(width: tile.rect.width, height: tile.rect.height)
                .position(x: tile.rect.midX, y: tile.rect.midY)
            }
        }
        .frame(width: size.width, height: size.height, alignment: .topLeading)
        .clipped()
    }
}


struct SingleImageView: View {
    let row: ShareSummary.AgentRow
    let summary: ShareSummary

    var body: some View {
        VStack(spacing: 18) {
            header
            
            HStack(alignment: .top, spacing: 16) {
                // Left column: tokens headline + token breakdown bar + legend
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading) {
                        Text(L10n.tr("share.tokens")).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                        Text(Fmt.tokens(row.tokens)).font(.system(size: 24, weight: .bold))
                    }
                    
                    // Token breakdown bar
                    HStack(spacing: 0) {
                        let total = CGFloat(max(1, row.tokens))
                        Color.blue.frame(width: CGFloat(row.tokenBreakdown.input) / total * 100, height: 6)
                        Color.purple.frame(width: CGFloat(row.tokenBreakdown.output) / total * 100, height: 6)
                    }
                    .clipShape(RoundedRectangle(cornerRadius: 3))
                    
                    // Legend
                    HStack {
                        Circle().fill(AgentPalette.color(for: row.agent)).frame(width: 8, height: 8)
                        Text(row.label).font(.system(size: 12))
                    }
                }
                .frame(width: 150)
                
                // Right column: mosaic
                SingleMosaic(projects: row.projectShares.map { ($0.name, $0.cost) }, agentColor: AgentPalette.color(for: row.agent), size: CGSize(width: 250, height: 180))
                    .frame(width: 250, height: 180)
            }
            
            footer
        }
        .padding(18)
        .frame(width: 480)
        .background(Color(white: 0.11))
        .environment(\.colorScheme, .dark)
    }

    private var header: some View {
        HStack {
            if let icon = BrandIcon.image ?? NSApp?.applicationIconImage {
                Image(nsImage: icon)
                    .resizable().frame(width: 28, height: 28)
            }
            Text(row.label).font(.system(size: 15, weight: .semibold))
            Spacer()
            HeroAmount(value: Fmt.money(row.cost), size: 24)
        }
    }
    
    private var footer: some View {
        HStack {
            Text(L10n.tr("share.updated_format", Fmt.clock(summary.updated)))
            Spacer()
            Text("github.com/mammut001/kanjo").font(.system(size: 10, design: .monospaced))
        }
        .font(.system(size: 10))
        .foregroundStyle(.secondary)
    }
}

