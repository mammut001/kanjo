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
                ForEach(summary.agentRows, id: \.agent) { row in
                    AgentCard(row: row, rangeLabel: summary.rangeLabel)
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
            Image(nsImage: NSWorkspace.shared.icon(forFile: Bundle.main.bundlePath))
                .resizable()
                .frame(width: 22, height: 22)
            VStack(alignment: .leading, spacing: 1) {
                Text("share.kanjo")
                    .font(.system(size: 15, weight: .bold))
                Text(summary.rangeLabel)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
    }

    private var footer: some View {
        HStack {
            Text(String(format: NSLocalizedString("share.updated_format", comment: ""), Fmt.clock(summary.updated)))
            Spacer()
            Text("Kanjo · github.com/mammut001/kanjo")
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
                Circle()
                    .fill(AgentColors.pair(for: row.agent).darkColor)
                    .frame(width: 8, height: 8)
                Text(row.label)
                    .font(.system(size: 14, weight: .semibold))
                if let sub = row.subscription, let mult = row.multiplier {
                    Text(String(format: NSLocalizedString("share.agent_subscription_format", comment: ""), sub.planLabel, Fmt.multiple(mult).dropLast()))
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
            }
            
            VStack(alignment: .leading, spacing: 2) {
                Text("\(Fmt.tokens(row.tokens))")
                    .font(.system(size: 26, weight: .bold, design: .rounded))
                Text(String(format: NSLocalizedString("share.total_suffix_format", comment: ""), rangeLabel))
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            
            // Grid metrics
            let grid = [
                row.cost > 0 ? (icon: "dollarsign.circle", caption: NSLocalizedString("share.cost", comment: ""), value: Fmt.money(row.cost), color: Color.green) : nil,
                row.cacheHitRate != nil ? (icon: "circle", caption: NSLocalizedString("share.cache_hit", comment: ""), value: String(format: "%.1f%%", (row.cacheHitRate!)*100), color: Color.blue) : nil,
                row.tokenBreakdown.input > 0 ? (icon: "arrow.down", caption: NSLocalizedString("share.input", comment: ""), value: Fmt.tokens(row.tokenBreakdown.input), color: Color.orange) : nil,
                row.tokenBreakdown.output > 0 ? (icon: "arrow.up", caption: NSLocalizedString("share.output", comment: ""), value: Fmt.tokens(row.tokenBreakdown.output), color: Color.purple) : nil,
                row.tokenBreakdown.cacheRead > 0 ? (icon: "bolt", caption: NSLocalizedString("share.cache_read", comment: ""), value: Fmt.tokens(row.tokenBreakdown.cacheRead), color: Color.yellow) : nil,
                row.tokenBreakdown.cacheWrite > 0 ? (icon: "square.stack.3d.up", caption: NSLocalizedString("share.cache_write", comment: ""), value: Fmt.tokens(row.tokenBreakdown.cacheWrite), color: Color.blue) : nil,
                row.tokenBreakdown.thinking > 0 ? (icon: "brain", caption: NSLocalizedString("share.reasoning", comment: ""), value: Fmt.tokens(row.tokenBreakdown.thinking), color: Color.pink) : nil
            ].compactMap { $0 }
            
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                ForEach(0..<grid.count, id: \.self) { i in
                    AgentMetric(icon: grid[i].icon, caption: grid[i].caption, value: grid[i].value, color: grid[i].color)
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
    
    var body: some View {
        HStack(spacing: 6) {
            ZStack {
                Circle().fill(color.opacity(0.15)).frame(width: 22, height: 22)
                Image(systemName: icon).font(.system(size: 10)).foregroundStyle(color)
            }
            VStack(alignment: .leading, spacing: 0) {
                Text(caption).font(.system(size: 10)).foregroundStyle(.secondary)
                Text(value).font(.system(size: 13, weight: .semibold, design: .monospaced))
            }
        }
    }
}

struct TotalsCard: View {
    let totals: ShareSummary.Totals
    let rangeLabel: String
    
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("share.total")
                .font(.system(size: 14, weight: .semibold))
            
            Text("\(Fmt.tokens(totals.tokens))")
                .font(.system(size: 26, weight: .bold, design: .rounded))
            
            let grid: [(icon: String, caption: String, value: String, color: Color)] = [
                (icon: "square.grid.2x2", caption: NSLocalizedString("share.agents", comment: ""), value: "\(totals.agentsCount)", color: Color.blue),
                (icon: "bubble.left.and.bubble.right", caption: NSLocalizedString("share.sessions", comment: ""), value: "\(totals.sessions)", color: Color.green),
                (icon: "dollarsign.circle", caption: NSLocalizedString("share.cost", comment: ""), value: Fmt.money(totals.cost), color: Color.green),
                (icon: "arrow.down", caption: NSLocalizedString("share.input", comment: ""), value: Fmt.tokens(totals.input), color: Color.orange),
                (icon: "arrow.up", caption: NSLocalizedString("share.output", comment: ""), value: Fmt.tokens(totals.output), color: Color.purple),
                (icon: "bolt", caption: NSLocalizedString("share.cache_read", comment: ""), value: Fmt.tokens(totals.cacheRead), color: Color.yellow),
                (icon: "square.stack.3d.up", caption: NSLocalizedString("share.cache_write", comment: ""), value: Fmt.tokens(totals.cacheWrite), color: Color.blue),
                (icon: "brain", caption: NSLocalizedString("share.reasoning", comment: ""), value: Fmt.tokens(totals.thinking), color: Color.pink)
            ]
            let filteredGrid = grid.filter { $0.value != "0" && $0.value != "0.00" }
            
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                ForEach(0..<filteredGrid.count, id: \.self) { i in
                    AgentMetric(icon: filteredGrid[i].icon, caption: filteredGrid[i].caption, value: filteredGrid[i].value, color: filteredGrid[i].color)
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
            Text("share.top_projects")
                .font(.system(size: 14, weight: .semibold))
            ForEach(projects, id: \.name) { p in
                VStack(spacing: 2) {
                    HStack {
                        Text(p.name).font(.system(size: 12))
                        Spacer()
                        Text("\(Fmt.money(p.cost))").font(.system(size: 12, weight: .medium, design: .monospaced))
                    }
                    GeometryReader { geom in
                        ZStack(alignment: .leading) {
                            RoundedRectangle(cornerRadius: 1).foregroundColor(Color.white.opacity(0.1))
                            RoundedRectangle(cornerRadius: 1).foregroundColor(Color.accentColor).frame(width: geom.size.width * CGFloat(p.share))
                        }
                    }
                    .frame(height: 2)
                }
            }
        }
        .padding(14)
        .background(Color.white.opacity(0.05))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.white.opacity(0.06), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }
}
