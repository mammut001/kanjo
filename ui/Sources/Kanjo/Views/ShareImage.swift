import SwiftUI
import KanjoCore

struct ShareImage: View {
    let summary: ShareSummary
    let agentId: String?

    var body: some View {
        VStack(spacing: 14) {
            header
            
            if let id = agentId, let row = summary.agentRows.first(where: { $0.agent == id }) {
                AgentCard(row: row, rangeLabel: summary.rangeLabel)
            } else {
                let sortedAgents = summary.agentRows.sorted { $0.cost > $1.cost }
                let topAgents = sortedAgents.prefix(4)
                let others = sortedAgents.dropFirst(4)
                
                ForEach(topAgents, id: \.agent) { row in
                    AgentCard(row: row, rangeLabel: summary.rangeLabel)
                }
                
                if !others.isEmpty {
                    OtherAgentsCard(others: Array(others))
                }
                
                TotalsCard(totals: summary.totals, rangeLabel: summary.rangeLabel)
                TopProjectsCard(projects: summary.topProjects)
            }
            
            footer
        }
        .padding(14)
        .frame(width: agentId != nil ? 340 : 380)
        .background(Color(white: 0.11))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(Color.white.opacity(0.08), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .environment(\.colorScheme, .dark)
    }

    private var header: some View {
        HStack(spacing: 8) {
            RoundedRectangle(cornerRadius: 6)
                .fill(Color.accentColor)
                .frame(width: 22, height: 22)
                .overlay(Text("K").font(.system(size: 14, weight: .bold)).foregroundColor(.white))
            
            VStack(alignment: .leading, spacing: 1) {
                Text(verbatim: "Kanjo")
                    .font(.system(size: 15, weight: .bold))
                Text(summary.rangeLabel)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
    }

    private var footer: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading) {
                Text(L10n.tr("share.updated_format", Fmt.clock(summary.updated)))
                Text("github.com/mammut001/kanjo")
                    .font(.system(size: 8))
            }
            Spacer()
            Text(verbatim: "Kanjo")
        }
        .font(.system(size: 10, design: .monospaced))
        .foregroundStyle(.secondary)
    }
}

struct AgentCard: View {
    let row: ShareSummary.AgentRow
    let rangeLabel: String
    
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 6) {
                let agentColor = AgentColors.pair(for: row.agent).darkColor
                Circle()
                    .fill(agentColor.opacity(0.15))
                    .frame(width: 22, height: 22)
                    .overlay(Circle().stroke(agentColor, lineWidth: 1))
                    .overlay(Image(systemName: "person").font(.system(size: 10)).foregroundColor(agentColor)) 
                
                Text(row.label)
                    .font(.system(size: 14, weight: .semibold))
                
                if let sub = row.subscription, let mult = row.multiplier {
                    Text(L10n.tr("share.agent_subscription_format", sub.planLabel, Fmt.multiple(mult)))
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
            }
            
            VStack(alignment: .leading, spacing: 2) {
                Text("\(Fmt.tokens(row.tokens))")
                    .font(.system(size: 26, weight: .bold, design: .rounded))
                Text(L10n.tr("share.total_suffix_format", rangeLabel))
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            
            let agentColor = AgentColors.pair(for: row.agent).darkColor
            let grid = [
                row.cost > 0 ? (icon: "dollarsign.circle", caption: L10n.tr("share.cost"), value: Fmt.money(row.cost), color: agentColor, rate: nil) : nil,
                row.cacheHitRate != nil ? (icon: "circle", caption: L10n.tr("share.cache_hit"), value: String(format: "%.1f%%", (row.cacheHitRate!)*100), color: agentColor, rate: row.cacheHitRate!) : nil,
                row.tokenBreakdown.input > 0 ? (icon: "arrow.down", caption: L10n.tr("share.input"), value: Fmt.tokens(row.tokenBreakdown.input), color: agentColor, rate: nil) : nil,
                row.tokenBreakdown.output > 0 ? (icon: "arrow.up", caption: L10n.tr("share.output"), value: Fmt.tokens(row.tokenBreakdown.output), color: agentColor, rate: nil) : nil,
                row.tokenBreakdown.cacheRead > 0 ? (icon: "bolt", caption: L10n.tr("share.cache_read"), value: Fmt.tokens(row.tokenBreakdown.cacheRead), color: agentColor, rate: nil) : nil,
                row.tokenBreakdown.cacheWrite > 0 ? (icon: "square.stack.3d.up", caption: L10n.tr("share.cache_write"), value: Fmt.tokens(row.tokenBreakdown.cacheWrite), color: agentColor, rate: nil) : nil,
                row.tokenBreakdown.thinking > 0 ? (icon: "brain", caption: L10n.tr("share.reasoning"), value: Fmt.tokens(row.tokenBreakdown.thinking), color: agentColor, rate: nil) : nil
            ].compactMap { $0 }
            
            LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)], spacing: 8) {
                ForEach(0..<grid.count, id: \.self) { i in
                    AgentMetric(icon: grid[i].icon, caption: grid[i].caption, value: grid[i].value, color: grid[i].color, rate: grid[i].rate)
                }
            }
        }
        .padding(14)
        .background(Color.white.opacity(0.05))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.white.opacity(0.06), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }
}

struct OtherAgentsCard: View {
    let others: [ShareSummary.AgentRow]
    
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.tr("share.other_agents"))
                .font(.system(size: 14, weight: .semibold))
            ForEach(others, id: \.agent) { row in
                HStack(spacing: 8) {
                    Circle().fill(AgentColors.pair(for: row.agent).darkColor).frame(width: 6, height: 6)
                    Text(row.label).font(.system(size: 12))
                    Spacer()
                    Text(Fmt.tokens(row.tokens)).font(.system(size: 12, design: .monospaced))
                    Text(Fmt.money(row.cost)).font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
                }
            }
        }
        .padding(14)
        .background(Color.white.opacity(0.05))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.white.opacity(0.06), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }
}

struct AgentMetric: View {
    let icon: String
    let caption: String
    let value: String
    let color: Color
    let rate: Double?
    
    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            if let rate = rate {
                ZStack {
                    Circle().stroke(Color.white.opacity(0.12), lineWidth: 3)
                    Circle().trim(from: 0, to: rate).stroke(color, style: StrokeStyle(lineWidth: 3, lineCap: .round)).rotationEffect(.degrees(-90))
                }
                .frame(width: 22, height: 22)
            } else {
                ZStack {
                    Circle().fill(color.opacity(0.15)).frame(width: 22, height: 22)
                    Image(systemName: icon).font(.system(size: 10)).foregroundStyle(color)
                }
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(caption).font(.system(size: 10)).foregroundStyle(.secondary)
                Text(value).font(.system(size: 13, weight: .semibold, design: .monospaced))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct TotalsCard: View {
    let totals: ShareSummary.Totals
    let rangeLabel: String
    
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(L10n.tr("share.total"))
                .font(.system(size: 14, weight: .semibold))
            
            Text("\(Fmt.tokens(totals.tokens))")
                .font(.system(size: 26, weight: .bold, design: .rounded))
            
            let accentColor = Color.accentColor
            
            let grid: [(icon: String, caption: String, value: String, color: Color)] = [
                (icon: "square.grid.2x2", caption: L10n.tr("share.agents"), value: "\(totals.agentsCount)", color: accentColor),
                (icon: "bubble.left.and.bubble.right", caption: L10n.tr("share.sessions"), value: "\(totals.sessions)", color: accentColor),
                (icon: "dollarsign.circle", caption: L10n.tr("share.cost"), value: Fmt.money(totals.cost), color: accentColor),
                (icon: "arrow.down", caption: L10n.tr("share.input"), value: Fmt.tokens(totals.input), color: accentColor),
                (icon: "arrow.up", caption: L10n.tr("share.output"), value: Fmt.tokens(totals.output), color: accentColor),
                (icon: "bolt", caption: L10n.tr("share.cache_read"), value: Fmt.tokens(totals.cacheRead), color: accentColor),
                (icon: "square.stack.3d.up", caption: L10n.tr("share.cache_write"), value: Fmt.tokens(totals.cacheWrite), color: accentColor),
                (icon: "brain", caption: L10n.tr("share.reasoning"), value: Fmt.tokens(totals.thinking), color: accentColor)
            ]
            let filteredGrid = grid.filter { $0.value != "0" && $0.value != "0.00" }
            
            LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)], spacing: 8) {
                ForEach(0..<filteredGrid.count, id: \.self) { i in
                    AgentMetric(icon: filteredGrid[i].icon, caption: filteredGrid[i].caption, value: filteredGrid[i].value, color: filteredGrid[i].color, rate: nil)
                }
            }
        }
        .padding(14)
        .background(Color.white.opacity(0.05))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.white.opacity(0.06), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }
}

struct TopProjectsCard: View {
    let projects: [ShareSummary.ProjectShare]
    
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(L10n.tr("share.top_projects"))
                .font(.system(size: 14, weight: .semibold))
            ForEach(projects, id: \.name) { p in
                VStack(spacing: 2) {
                    HStack {
                        Text(p.name).font(.system(size: 12)).truncationMode(.middle)
                        Spacer()
                        Text("\(Fmt.money(p.cost))").font(.system(size: 12, weight: .medium, design: .monospaced))
                        Text(Fmt.percent(p.share)).font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
                    }
                    GeometryReader { geom in
                        ZStack(alignment: .leading) {
                            RoundedRectangle(cornerRadius: 1).foregroundColor(Color.white.opacity(0.1))
                            RoundedRectangle(cornerRadius: 1).foregroundColor(Color.accentColor).frame(width: geom.size.width * CGFloat(p.share))
                        }
                    }
                    .frame(height: 3)
                }
            }
        }
        .padding(14)
        .background(Color.white.opacity(0.05))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.white.opacity(0.06), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }
}
