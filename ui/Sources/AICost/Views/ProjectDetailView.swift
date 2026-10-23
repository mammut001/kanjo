import SwiftUI
import AICostCore

struct BackButton: View {
    let title: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 3) {
                Image(systemName: "chevron.left")
                Text(title)
            }
            .font(.system(size: 11.5, weight: .medium))
        }
        .glassButtonStyle()
    }
}

/// 详情页头部的路径列表：只列主路径，临时目录（scratchpad / worktree 等）折叠在胶囊按钮后面。
/// 全部是临时路径时默认展开。
struct ProjectPathsView: View {
    let primary: [String]
    let temporary: [String]
    let pathMissing: Bool
    @State private var showTemporary: Bool

    init(paths: [String], pathMissing: Bool) {
        let split = splitPaths(paths)
        primary = split.primary
        temporary = split.temporary
        self.pathMissing = pathMissing
        _showTemporary = State(initialValue: split.primary.isEmpty)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(primary, id: \.self) { pathRow($0) }
            if !temporary.isEmpty {
                Button {
                    withAnimation(.easeOut(duration: 0.15)) { showTemporary.toggle() }
                } label: {
                    HStack(spacing: 3) {
                        Image(systemName: showTemporary ? "chevron.up" : "chevron.down")
                            .font(.system(size: 8, weight: .semibold))
                        Text(toggleTitle)
                    }
                    .font(.system(size: 10, weight: .medium))
                }
                .glassButtonStyle()
                .controlSize(.small)
                .help("Scratchpads, worktrees and other temporary directories agents worked in.")
                if showTemporary {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(temporary, id: \.self) { pathRow($0, size: 9.5) }
                    }
                    .padding(.leading, 4)
                }
            }
        }
    }

    private var toggleTitle: String {
        let noun = temporary.count == 1 ? "temporary path" : "temporary paths"
        return showTemporary ? "Hide \(temporary.count) \(noun)" : "+\(temporary.count) \(noun)"
    }

    private func pathRow(_ p: String, size: CGFloat = 10) -> some View {
        Text(p)
            .font(.system(size: size, design: .monospaced))
            .foregroundStyle(.secondary)
            .strikethrough(pathMissing)
            .lineLimit(1)
            .truncationMode(.middle)
            .textSelection(.enabled)
            .help(p)
    }
}

struct ProjectDetailView: View {
    let project: Project
    let report: UsageReport
    let onBack: () -> Void

    private var cur: String { report.currency }

    var body: some View {
        ScrollView {
            GlassGroup(spacing: 6) {
                VStack(alignment: .leading, spacing: 10) {
                    BackButton(title: "Projects", action: onBack)
                    header
                    tokensCard
                    agentsCard
                    modelsCard
                    SectionCard("Daily cost") {
                        DayChart(days: project.byDay, currency: cur)
                    }
                    branchesCard
                    SectionCard("Sessions (\(project.sessionsDetail.count))") {
                        SessionList(sessions: project.sessionsDetail,
                                    threshold: report.config.dominantThreshold, currency: cur)
                    }
                }
                .padding(10)
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(project.name).font(.system(size: 17, weight: .bold)).lineLimit(2)
                if project.pathMissing {
                    Badge(text: "path missing", style: .warn, help: "None of this project's local paths exist any more.")
                }
                Spacer(minLength: 6)
                Text(Fmt.money(project.cost, currency: cur))
                    .font(.system(size: 19, weight: .bold, design: .rounded).monospacedDigit())
            }
            Group {
                if let r = project.remote {
                    Label(r, systemImage: "link")
                } else {
                    Label("No remote — local repository", systemImage: "internaldrive")
                }
            }
            .font(.system(size: 11)).foregroundStyle(.secondary)
            .textSelection(.enabled)
            ProjectPathsView(paths: project.paths, pathMissing: project.pathMissing)
                .id(project.id)
            Text("\(project.sessions) sessions · \(Fmt.day(project.firstActive)) – \(Fmt.day(project.lastActive))")
                .font(.system(size: 10.5)).foregroundStyle(.secondary)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassSurface(cornerRadius: 14)
    }

    private var tokensCard: some View {
        let t = project.tokens
        return SectionCard("Tokens") {
            Text("\(Fmt.tokens(t.total)) total").font(.system(size: 10.5)).foregroundStyle(.secondary)
        } content: {
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                GridRow {
                    tok("Input", t.input, AgentPalette.tokenInput, "Non-cached input tokens")
                    tok("Output", t.output, AgentPalette.tokenOutput, "Output tokens, including thinking")
                    tok("Thinking", t.thinking, nil, "Subset of output; shown for reference, not added to the total. Some agents report 0.")
                }
                GridRow {
                    tok("Cache read", t.cacheRead, AgentPalette.tokenCacheRead, "Tokens read from prompt cache")
                    tok("Cache write", t.cacheWrite, AgentPalette.tokenCacheWrite, "Tokens written to prompt cache")
                    Color.clear.frame(height: 1)
                }
            }
            tokenBar(t)
        }
    }

    private func tok(_ label: String, _ v: Int, _ color: Color?, _ help: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            HStack(spacing: 4) {
                if let color { RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 8, height: 8) }
                else { RoundedRectangle(cornerRadius: 2).stroke(Color.secondary, lineWidth: 1).frame(width: 8, height: 8) }
                Text(label).font(.system(size: 10)).foregroundStyle(.secondary)
            }
            Text(Fmt.tokens(v)).font(.system(size: 13.5, weight: .semibold, design: .rounded).monospacedDigit())
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .help(help)
    }

    /// 四类计费 token 的构成条（thinking 是 output 子集，不单列）。
    private func tokenBar(_ t: Tokens) -> some View {
        let parts: [(Int, Color)] = [(t.input, AgentPalette.tokenInput), (t.output, AgentPalette.tokenOutput),
                                     (t.cacheRead, AgentPalette.tokenCacheRead), (t.cacheWrite, AgentPalette.tokenCacheWrite)]
        let total = max(parts.reduce(0) { $0 + $1.0 }, 1)
        return GeometryReader { geo in
            let visible = parts.filter { $0.0 > 0 }
            let avail = max(geo.size.width - CGFloat(max(visible.count - 1, 0)) * 2, 0)
            HStack(spacing: 2) {
                ForEach(Array(visible.enumerated()), id: \.offset) { _, p in
                    RoundedRectangle(cornerRadius: 2).fill(p.1)
                        .frame(width: max(avail * CGFloat(p.0) / CGFloat(total), 2))
                }
            }
        }
        .frame(height: 6)
    }

    private var agentsCard: some View {
        SectionCard("By agent") {
            let maxCost = project.byAgent.map(\.cost).max() ?? 0
            VStack(spacing: 8) {
                ForEach(project.byAgent) { a in
                    HBarRow(label: a.label, color: AgentPalette.color(for: a.agent),
                            fraction: maxCost > 0 ? a.cost / maxCost : 0,
                            value: Fmt.money(a.cost, currency: cur),
                            detail: "\(a.sessions) sess · \(Fmt.tokens(a.tokens.total)) tok · \(Fmt.percent(project.cost > 0 ? a.cost / project.cost : 0))")
                }
            }
        }
    }

    private var modelsCard: some View {
        SectionCard("By model") {
            Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 5) {
                GridRow {
                    Text("Model"); Text("Tokens").gridColumnAlignment(.trailing); Text("Cost").gridColumnAlignment(.trailing)
                }
                .font(.system(size: 9.5, weight: .medium)).foregroundStyle(.secondary)
                ForEach(project.byModel) { m in
                    GridRow {
                        HStack(spacing: 4) {
                            AgentDot(agent: m.agent, size: 6)
                            Text(m.model).font(.system(size: 10.5, design: .monospaced)).lineLimit(1).truncationMode(.middle)
                            if m.estimated {
                                Badge(text: "est.", style: .warn,
                                      help: "Price unknown for this model; estimated from the most expensive tier of its family.")
                            }
                        }
                        .help("\(m.model) (\(m.agent))")
                        Text(Fmt.tokens(m.tokens.total)).font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                        Text(Fmt.money(m.cost, currency: cur)).font(.system(size: 10.5, weight: .medium)).monospacedDigit()
                    }
                }
            }
        }
    }

    private var branchesCard: some View {
        SectionCard("By branch") {
            if project.byBranch.isEmpty {
                Text("No branch information for this project.").font(.system(size: 11)).foregroundStyle(.secondary)
            } else {
                Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 5) {
                    GridRow {
                        Text("Branch"); Text("Sessions").gridColumnAlignment(.trailing); Text("Cost").gridColumnAlignment(.trailing)
                    }
                    .font(.system(size: 9.5, weight: .medium)).foregroundStyle(.secondary)
                    ForEach(project.byBranch) { b in
                        GridRow {
                            Text(b.branch).font(.system(size: 10.5, design: .monospaced)).lineLimit(1).truncationMode(.middle)
                                .foregroundStyle(b.branch == "(unknown)" ? .secondary : .primary)
                            Text("\(b.sessions)").font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                            Text(Fmt.money(b.cost, currency: cur)).font(.system(size: 10.5, weight: .medium)).monospacedDigit()
                        }
                    }
                }
            }
        }
    }
}

struct BucketDetailView: View {
    let kind: BucketKind
    let report: UsageReport
    let onBack: () -> Void

    var body: some View {
        let b = kind == .unattributed ? report.buckets.unattributed : report.buckets.excluded
        ScrollView {
            GlassGroup(spacing: 6) {
                VStack(alignment: .leading, spacing: 10) {
                    BackButton(title: "Overview", action: onBack)
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(kind == .unattributed ? "Unattributed" : "Excluded").font(.system(size: 17, weight: .bold))
                            Spacer()
                            Text(Fmt.money(b.cost, currency: report.currency))
                                .font(.system(size: 19, weight: .bold, design: .rounded).monospacedDigit())
                        }
                        Text(AttributionInfo.explanation(kind == .unattributed ? "none" : "excluded",
                                                         threshold: report.config.dominantThreshold))
                            .font(.system(size: 10.5)).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .glassSurface(cornerRadius: 14)
                    SectionCard("Sessions (\(b.sessionsDetail.count))") {
                        SessionList(sessions: b.sessionsDetail, threshold: report.config.dominantThreshold,
                                    currency: report.currency)
                    }
                }
                .padding(10)
            }
        }
    }
}
