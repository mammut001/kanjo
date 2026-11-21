import SwiftUI
import KanjoCore

struct ShareImage: View {
    let summary: ShareSummary
    let agentId: String?
    let report: UsageReport
    let rangeRaw: String

    var body: some View {
        shareBody.environment(\.isShareRender, true)
    }

    @ViewBuilder
    private var shareBody: some View {
        if let id = agentId, let summaryRow = summary.agentSummaryRows.first(where: { $0.agent == id }) {
            VStack(spacing: 18) {
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
                }
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
    var body: some View {
        GeometryReader { geo in
            let gap: CGFloat = 1.5
            let count = rows.count
            let avail = max(geo.size.width - CGFloat(max(count - 1, 0)) * gap, 0)
            let base = count > 0 ? min(2, avail / CGFloat(count)) : 0
            let remainder = max(0, avail - CGFloat(count) * base)
            let sum = rows.reduce(0.0) { $0 + Double(max(0, $1.tokens)) }
            
            HStack(spacing: gap) {
                ForEach(rows, id: \.agent) { row in
                    let share = sum > 0 ? Double(max(0, row.tokens)) / sum : 0
                    let w = base + remainder * CGFloat(share)
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
        // 640 pt card, 18 pt inset, 16 pt gap → 588 pt for the two columns. 50% mosaic / 50% agents.
        let columns = CGFloat(640 - 18 * 2 - 16)
        let mosaicW = (columns * 0.50).rounded()
        let agentsW = columns - mosaicW
        let mosaicH: CGFloat = 230
        let shown = Array(summary.agentRows.prefix(7))
        let overflowCost = summary.agentRows.dropFirst(7).reduce(0.0) { $0 + $1.cost }
        let tokenW = width(shown.map { Fmt.tokens($0.tokens) })
        let costW = width(shown.map { Fmt.money($0.cost, currency: summary.currency) }
            + (summary.agentRows.count > 7 ? [Fmt.money(overflowCost, currency: summary.currency)] : []))
        let multiplierW = width(shown.map { multiplierText($0) }, weight: .semibold)
        let columnGap: CGFloat = 12
        let nameW = max(0, agentsW - 12 - tokenW - costW - multiplierW - 3 * columnGap)

        VStack(spacing: 18) {
            header
            
            HStack(alignment: .top, spacing: 16) {
                // Left: Mosaic
                VStack(alignment: .leading, spacing: 8) {
                    Text(L10n.tr("share.top_projects")).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    if summary.mosaicProjects.isEmpty {
                        Text(L10n.tr("overview.projects.no_usage_range"))
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                            .frame(width: mosaicW, height: mosaicH, alignment: .topLeading)
                    } else {
                        ShareMosaic(projects: summary.mosaicProjects, currency: summary.currency, size: CGSize(width: mosaicW, height: mosaicH))
                            .frame(width: mosaicW, height: mosaicH)
                    }
                }
                .frame(width: mosaicW, alignment: .leading)
                
                // Right: Agent bar + aligned rows
                VStack(alignment: .leading, spacing: 8) {
                    Text(L10n.tr("share.agents")).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    
                    if summary.agentRows.isEmpty {
                        Text(L10n.tr("agents.empty")).font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                    ShareProportionBar(rows: summary.agentRows)
                    
                    Grid(alignment: .center, horizontalSpacing: columnGap, verticalSpacing: 8) {
                        let maxShown = 7
                        let overflow = max(0, summary.agentRows.count - maxShown)
                        
                        ForEach(shown, id: \.agent) { row in
                            GridRow {
                                HStack(spacing: 6) {
                                    Circle().fill(AgentPalette.color(for: row.agent)).frame(width: 6, height: 6)
                                    Text(row.label)
                                        .font(.system(size: 13))
                                        .lineLimit(1)
                                        .frame(width: nameW, alignment: .leading)
                                }
                                .gridColumnAlignment(.leading)
                                .layoutPriority(1)

                                Text(Fmt.tokens(row.tokens))
                                    .font(.system(size: 13, design: .monospaced))
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.7)
                                    .frame(width: tokenW, alignment: .trailing)
                                    .gridColumnAlignment(.trailing)

                                Text(Fmt.money(row.cost, currency: summary.currency))
                                    .font(.system(size: 13, design: .monospaced))
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.6)
                                    .frame(width: costW, alignment: .trailing)
                                    .gridColumnAlignment(.trailing)

                                Text(multiplierText(row))
                                    .font(.system(size: 13, weight: .semibold, design: .monospaced))
                                    .foregroundStyle(multiplierColor(row))
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.6)
                                    .frame(width: multiplierW, alignment: .trailing)
                                    .gridColumnAlignment(.trailing)
                            }
                        }
                        
                        if overflow > 0 {
                            GridRow {
                                HStack(spacing: 6) {
                                    Circle().fill(Color.secondary.opacity(0.5)).frame(width: 6, height: 6)
                                    Text(L10n.tr("share.more_agents", overflow))
                                        .font(.system(size: 13))
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                        .frame(width: nameW, alignment: .leading)
                                }
                                .gridColumnAlignment(.leading)

                                Text(verbatim: " ")
                                    .font(.system(size: 13, design: .monospaced))
                                    .gridColumnAlignment(.trailing)
                                Text(Fmt.money(overflowCost, currency: summary.currency))
                                    .font(.system(size: 13, design: .monospaced))
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.6)
                                    .frame(width: costW, alignment: .trailing)
                                    .gridColumnAlignment(.trailing)
                                Text(verbatim: " ")
                                    .font(.system(size: 13, weight: .semibold, design: .monospaced))
                                    .gridColumnAlignment(.trailing)
                            }
                        }
                    }
                }
                .frame(width: agentsW, alignment: .leading)
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

    private func width(_ values: [String], weight: NSFont.Weight = .regular) -> CGFloat {
        let font = NSFont.monospacedSystemFont(ofSize: 13, weight: weight)
        return ceil(values.map { ($0 as NSString).size(withAttributes: [.font: font]).width }.max() ?? 0)
    }

    private func multiplierText(_ row: ShareSummary.AgentRow) -> String {
        if let m = row.multiplier, m > 0 { return Fmt.multiple(m) }
        return " "
    }

    private func multiplierColor(_ row: ShareSummary.AgentRow) -> Color {
        if let m = row.multiplier, m > 0 { return AgentPalette.color(for: row.agent) }
        return .clear
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
                HeroAmount(value: Fmt.money(summary.totals.cost, currency: summary.currency), size: 24)
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
    let currency: String
    let size: CGSize
    
    var body: some View {
        let tiles = MosaicView.tiles(projects, size: size)
        ZStack(alignment: .topLeading) {
            ForEach(tiles) { tile in
                ZStack(alignment: .topLeading) {
                    RoundedRectangle(cornerRadius: 4).fill(tile.color)
                    if tile.rect.width >= 56 && tile.rect.height >= 40 {
                        VStack(alignment: .leading, spacing: 0) {
                            Text(name(for: tile)).font(.system(size: 11, weight: .semibold)).foregroundStyle(.white).lineLimit(1)
                            ViewThatFits(in: .horizontal) {
                                Text(Fmt.money(tile.cost, currency: currency))
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(.white.opacity(0.8))
                                    .fixedSize()
                                Color.clear.frame(width: 0, height: 0)
                            }
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



