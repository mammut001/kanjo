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
                // Left: Placeholder for Mosaic
                VStack(alignment: .leading, spacing: 8) {
                    Text(L10n.tr("share.top_projects")).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    Rectangle().fill(Color.secondary.opacity(0.1)).frame(height: 230)
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
            // Placeholder for icon, assuming KanjoApp is in the same module
            Image(nsImage: NSApp?.applicationIconImage ?? NSImage())
                .resizable().frame(width: 28, height: 28)
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

struct SingleImageView: View {
    let row: ShareSummary.AgentRow
    let summary: ShareSummary

    var body: some View {
        VStack(spacing: 18) {
            header
            
            Text(Fmt.tokens(row.tokens)).font(.system(size: 24, weight: .bold))
            
            footer
        }
        .padding(18)
        .frame(width: 480)
        .background(Color(white: 0.11))
        .environment(\.colorScheme, .dark)
    }

    private var header: some View {
        HStack {
            Image(nsImage: NSApp?.applicationIconImage ?? NSImage())
                .resizable().frame(width: 28, height: 28)
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
