import SwiftUI
import KanjoCore

struct ShareImage: View {
    let summary: ShareSummary
    let agentId: String? // If nil, multi-agent view. Else single-agent.

    var body: some View {
        ZStack {
            Color.black // Dark card background
                .edgesIgnoringSafeArea(.all)
            
            VStack(spacing: 16) {
                // Header
                header
                
                if let id = agentId, let row = summary.agentRows.first(where: { $0.agent == id }) {
                    AgentCard(row: row)
                } else {
                    // Multi-agent view
                    ForEach(summary.agentRows, id: \.agent) { row in
                        AgentCard(row: row)
                    }
                    TotalsCard(totals: summary.totals)
                    TopProjectsCard(projects: summary.topProjects)
                }
                
                footer
            }
            .padding(24)
            .frame(width: agentId != nil ? 340 : 380)
        }
    }

    private var header: some View {
        HStack {
            Text("Kanjo")
                .font(.system(size: 20, weight: .bold))
                .foregroundColor(.white)
            Spacer()
            Text(summary.rangeLabel)
                .font(.system(size: 14))
                .foregroundColor(.gray)
        }
    }

    private var footer: some View {
        Text("Updated \(Fmt.clock(summary.updated)) · Kanjo · github.com/mammut001/kanjo")
            .font(.system(size: 10))
            .foregroundColor(.gray)
    }
}

struct AgentCard: View {
    let row: ShareSummary.AgentRow
    
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Circle()
                    .fill(AgentColors.pair(for: row.agent).darkColor)
                    .frame(width: 8, height: 8)
                Text(row.label)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(.white)
            }
            // Metrics grid
            HStack(spacing: 16) {
                MetricView(title: "Tokens", value: Fmt.tokens(row.tokens))
                MetricView(title: "Cost", value: Fmt.money(row.cost))
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.05)))
    }
}

struct MetricView: View {
    let title: String
    let value: String
    
    var body: some View {
        VStack(alignment: .leading) {
            Text(title)
                .font(.system(size: 10))
                .foregroundColor(.gray)
            Text(value)
                .font(.system(size: 14, weight: .medium))
                .foregroundColor(.white)
        }
    }
}

struct TotalsCard: View {
    let totals: ShareSummary.Totals
    
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Totals")
                .font(.system(size: 14, weight: .semibold))
                .foregroundColor(.white)
            HStack {
                MetricView(title: "Tokens", value: Fmt.tokens(totals.tokens))
                MetricView(title: "Cost", value: Fmt.money(totals.cost))
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.05)))
    }
}

struct TopProjectsCard: View {
    let projects: [ShareSummary.ProjectShare]
    
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Top Projects")
                .font(.system(size: 14, weight: .semibold))
                .foregroundColor(.white)
            ForEach(projects, id: \.name) { p in
                HStack {
                    Text(p.name)
                        .font(.system(size: 12))
                        .foregroundColor(.white)
                    Spacer()
                    Text(Fmt.money(p.cost))
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.white)
                }
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.05)))
    }
}
