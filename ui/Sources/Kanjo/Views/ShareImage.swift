import SwiftUI
import KanjoCore

struct ShareImage: View {
    let summary: ShareSummary
    let agentId: String?
    let report: UsageReport
    let rangeRaw: String

    var body: some View {
        if let id = agentId, let row = summary.agentRows.first(where: { $0.agent == id }),
           let summaryRow = summary.agentSummaryRows.first(where: { $0.agent == id }) {
            VStack(spacing: 18) {
                ShareImage.header(title: row.label, rangeLabel: summary.rangeLabel, cost: row.cost, tokens: row.tokens, sessions: row.sessionCount ?? 0)
                AgentDetailCard(row: summaryRow, report: report, rangeRaw: rangeRaw, currency: summary.currency, forShare: true)
                    .padding(14)
                    .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.04)))
                ShareImage.footer(updated: summary.updated)
            }
            .padding(18)
            .frame(width: 420)
            .background(Color(white: 0.11))
            .environment(\.colorScheme, .dark)
        } else {
            MultiImageView(summary: summary)
        }
    }

    static func header(title: String, rangeLabel: String, cost: Double, tokens: Int, sessions: Int) -> some View {
        HStack {
            if let icon = BrandIcon.image ?? NSApp?.applicationIconImage {
                Image(nsImage: icon)
                    .resizable().frame(width: 28, height: 28)
            }
            VStack(alignment: .leading) {
                Text(verbatim: title).font(.system(size: 15, weight: .semibold))
                Text(rangeLabel).font(.system(size: 11)).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing) {
                HeroAmount(value: Fmt.money(cost), size: 24)
                Text(L10n.tr("share.tokens_sessions", Fmt.tokens(tokens), sessions))
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }
        }
    }

    static func footer(updated: Date) -> some View {
        HStack {
            Text(L10n.tr("share.updated_format", Fmt.clock(updated)))
            Spacer()
            Text("github.com/mammut001/kanjo").font(.system(size: 10, design: .monospaced))
        }
        .font(.system(size: 10))
        .foregroundStyle(.secondary)
    }
    
    public static func copy(report: UsageReport, rangeRaw: String, agentId: String?, hiddenProjects: Set<String>) -> Bool {
        let summary = ShareSummary.build(report: report, rangeRaw: rangeRaw, hiddenProjects: hiddenProjects)
        let renderer = ImageRenderer(content: ShareImage(summary: summary, agentId: agentId, report: report, rangeRaw: rangeRaw))
        renderer.scale = 2.0
        if let nsImage = renderer.nsImage {
            ShareImageExporter.copyToPasteboard(image: nsImage)
            return true
        }
        return false
    }
}

struct ShareProportionBar: View {
    let rows: [ShareSummary.AgentRow]
    let totalTokens: Int

    var body: some View {
        GeometryReader { geo in
            let gap: CGFloat = 1.5
            let count = rows.count
            let avail = max(geo.size.width - CGFloat(max(count - 1, 0)) * gap, 0)
            
            HStack(spacing: gap) {
                ForEach(rows, id: \.agent) { row in
                    let share = totalTokens > 0 ? Double(row.tokens) / Double(totalTokens) : 0
                    let w = max(avail * CGFloat(share), 2)
                    Rectangle()
                        .fill(AgentPalette.color(for: row.agent))
                        .frame(width: w)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 3, style: .continuous))
        }
        .frame(height: 6)
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
                .frame(width: 312)
                
                // Right: Agent bar + Legend
                VStack(alignment: .leading, spacing: 8) {
                    Text(L10n.tr("share.agents")).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    
                    ShareProportionBar(rows: summary.agentRows, totalTokens: summary.totals.tokens)
                    
                    Grid(alignment: .trailing, horizontalSpacing: 10, verticalSpacing: 8) {
                        let maxShown = 7
                        let shown = Array(summary.agentRows.prefix(maxShown))
                        let overflow = max(0, summary.agentRows.count - maxShown)
                        
                        ForEach(shown, id: \.agent) { row in
                            GridRow {
                                HStack(spacing: 6) {
                                    Circle().fill(AgentPalette.color(for: row.agent)).frame(width: 6, height: 6)
                                    Text(row.label).font(.system(size: 13)).lineLimit(1)
                                    Spacer(minLength: 10)
                                }
                                .gridColumnAlignment(.leading)
                                .layoutPriority(1)
                                
                                Text(Fmt.tokens(row.tokens)).font(.system(size: 13, design: .monospaced)).foregroundStyle(.secondary)
                                Text(Fmt.money(row.cost)).font(.system(size: 13, design: .monospaced))
                                
                                if let m = row.multiplier, m > 0 {
                                    Text(Fmt.multiple(m)).font(.system(size: 13, weight: .semibold, design: .monospaced)).foregroundStyle(AgentPalette.color(for: row.agent))
                                } else {
                                    Text("")
                                }
                            }
                        }
                        
                        if overflow > 0 {
                            let overflowCost = summary.agentRows.dropFirst(maxShown).reduce(0.0) { $0 + $1.cost }
                            GridRow {
                                HStack(spacing: 6) {
                                    Circle().fill(Color.secondary.opacity(0.5)).frame(width: 6, height: 6)
                                    Text(L10n.tr("share.more_agents", overflow)).font(.system(size: 13)).foregroundStyle(.secondary)
                                    Spacer(minLength: 10)
                                }
                                .gridColumnAlignment(.leading)
                                
                                Text("") // Tokens column empty
                                Text(Fmt.money(overflowCost)).font(.system(size: 13, design: .monospaced))
                                Text("")
                            }
                        }
                    }
                }
                .frame(width: 250)
            }
            
            // Bottom stat chips
            HStack(spacing: 20) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(L10n.tr("share.input")).font(.system(size: 10)).foregroundStyle(.secondary)
                    Text(Fmt.tokens(summary.totals.input)).font(.system(size: 13, weight: .semibold, design: .monospaced))
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(L10n.tr("share.output")).font(.system(size: 10)).foregroundStyle(.secondary)
                    Text(Fmt.tokens(summary.totals.output)).font(.system(size: 13, weight: .semibold, design: .monospaced))
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(L10n.tr("share.cache_read")).font(.system(size: 10)).foregroundStyle(.secondary)
                    Text(Fmt.tokens(summary.totals.cacheRead)).font(.system(size: 13, weight: .semibold, design: .monospaced))
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(L10n.tr("share.cache_hit")).font(.system(size: 10)).foregroundStyle(.secondary)
                    let total = summary.totals.input + summary.totals.cacheRead
                    let hitRate = total > 0 ? Double(summary.totals.cacheRead) / Double(total) : 0.0
                    Text(Fmt.percent(hitRate)).font(.system(size: 13, weight: .semibold, design: .monospaced))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 18)
            
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



