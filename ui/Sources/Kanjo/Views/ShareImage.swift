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
                .frame(width: 350)
                
                // Right: Agent bar + Legend
                VStack(alignment: .leading, spacing: 8) {
                    Text(L10n.tr("share.agents")).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    
                    ShareProportionBar(rows: summary.agentRows, totalTokens: summary.totals.tokens)
                    
                    VStack(spacing: 8) {
                        let maxShown = 7
                        let shown = Array(summary.agentRows.prefix(maxShown))
                        let overflow = max(0, summary.agentRows.count - maxShown)
                        
                        ForEach(shown, id: \.agent) { row in
                            HStack(spacing: 6) {
                                Circle().fill(AgentPalette.color(for: row.agent)).frame(width: 6, height: 6)
                                Text(row.label).font(.system(size: 13)).lineLimit(1)
                                Spacer()
                                Text(Fmt.tokens(row.tokens)).font(.system(size: 13, design: .monospaced)).foregroundStyle(.secondary)
                                Text(Fmt.money(row.cost)).font(.system(size: 13, design: .monospaced)).frame(width: 64, alignment: .trailing)
                                
                                if let m = row.multiplier, m > 0 {
                                    Text(Fmt.multiple(m)).font(.system(size: 13, weight: .semibold, design: .monospaced)).foregroundStyle(AgentPalette.color(for: row.agent)).frame(width: 40, alignment: .trailing)
                                } else {
                                    Color.clear.frame(width: 40)
                                }
                            }
                        }
                        
                        if overflow > 0 {
                            let overflowCost = summary.agentRows.dropFirst(maxShown).reduce(0.0) { $0 + $1.cost }
                            HStack(spacing: 6) {
                                Circle().fill(Color.secondary.opacity(0.5)).frame(width: 6, height: 6)
                                Text(L10n.tr("share.more_agents", overflow)).font(.system(size: 13)).foregroundStyle(.secondary)
                                Spacer()
                                Text(Fmt.money(overflowCost)).font(.system(size: 13, design: .monospaced)).frame(width: 64, alignment: .trailing)
                                Color.clear.frame(width: 40)
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
                        
                        if let sub = row.subscription, let m = row.multiplier, m > 0 {
                            Text(L10n.tr("share.agent_subscription_format", sub.planLabel, Fmt.multiple(m)))
                                .font(.system(size: 12)).foregroundStyle(.secondary)
                        }
                    }
                    
                    VStack(alignment: .leading, spacing: 6) {
                        tokenCompositionBar(row.tokenBreakdown)
                        
                        // Legend Grid
                        VStack(spacing: 4) {
                             HStack(spacing: 8) {
                                 tokenStat(L10n.tr("share.input"), row.tokenBreakdown.input, AgentPalette.tokenInput)
                                 tokenStat(L10n.tr("share.output"), row.tokenBreakdown.output, AgentPalette.tokenOutput)
                             }
                             HStack(spacing: 8) {
                                 tokenStat(L10n.tr("share.cache_read"), row.tokenBreakdown.cacheRead, AgentPalette.tokenCacheRead)
                                 tokenStat(L10n.tr("share.cache_write"), row.tokenBreakdown.cacheWrite, AgentPalette.tokenCacheWrite)
                             }
                        }
                        
                        if let rate = row.cacheHitRate {
                            Text(L10n.tr("agents.detail.cache_hit") + " " + Fmt.percent(rate))
                                .font(.system(size: 11)).foregroundStyle(.secondary)
                        }
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
    
    private func tokenCompositionBar(_ t: Tokens) -> some View {
        let parts: [(tokens: Int, color: Color)] = [
            (t.input, AgentPalette.tokenInput),
            (t.output, AgentPalette.tokenOutput),
            (t.cacheRead, AgentPalette.tokenCacheRead),
            (t.cacheWrite, AgentPalette.tokenCacheWrite),
        ].filter { $0.tokens > 0 }
        let total = max(parts.reduce(0) { $0 + $1.tokens }, 1)
        return GeometryReader { geo in
            let avail = max(geo.size.width - CGFloat(max(parts.count - 1, 0)), 0)
            HStack(spacing: 1) {
                ForEach(Array(parts.enumerated()), id: \.offset) { _, p in
                    Rectangle()
                        .fill(p.color)
                        .frame(width: max(avail * CGFloat(p.tokens) / CGFloat(total), 2))
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 4, style: .continuous))
        }
        .frame(height: 8)
    }

    private func tokenStat(_ label: String, _ value: Int, _ color: Color) -> some View {
        HStack(spacing: 4) {
            Circle().fill(color).frame(width: 6, height: 6)
            Text("\(label) \(Fmt.tokens(value))").font(.system(size: 11, design: .monospaced))
        }
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

