import SwiftUI
import AICostCore

/// 详情页头部的路径列表：只列主路径，临时目录（scratchpad / worktree 等）折叠在一个文字按钮后面。
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
        VStack(alignment: .leading, spacing: 2) {
            ForEach(primary, id: \.self) { pathRow($0) }
            if !temporary.isEmpty {
                Button {
                    withAnimation(.easeOut(duration: 0.15)) { showTemporary.toggle() }
                } label: {
                    HStack(spacing: 3) {
                        Image(systemName: showTemporary ? "chevron.down" : "chevron.right")
                            .font(.system(size: 7.5, weight: .bold))
                        Text(toggleTitle)
                    }
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.top, 1)
                .help("Scratchpads, worktrees and other temporary directories agents worked in.")
                if showTemporary {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(temporary, id: \.self) { pathRow($0, size: 9.5) }
                    }
                    .padding(.leading, 10)
                }
            }
        }
    }

    private var toggleTitle: String {
        let noun = temporary.count == 1 ? "temporary path" : "temporary paths"
        return showTemporary ? "Hide \(temporary.count) \(noun)" : "\(temporary.count) \(noun)"
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

/// 详情页 / 桶详情页通用的页面骨架：返回按钮 + 各节，等间距排列。
struct DetailPage<Content: View>: View {
    let backTitle: String
    let onBack: () -> Void
    @ViewBuilder var content: () -> Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Metrics.sectionSpacing) {
                BackButton(title: backTitle, action: onBack)
                    .padding(.leading, Metrics.rowInset - 4)
                    .padding(.bottom, -6)
                content()
            }
            .padding(.horizontal, Metrics.pagePadding)
            .padding(.top, 12).padding(.bottom, 10)
        }
    }
}

struct ProjectDetailView: View {
    let project: Project
    let report: UsageReport
    let onBack: () -> Void

    @State private var showAllModels = false
    @State private var showAllBranches = false
    private let collapsedLimit = 8

    private var cur: String { report.currency }

    var body: some View {
        DetailPage(backTitle: "Projects", onBack: onBack) {
            header
            tokensSection
            agentsSection
            modelsSection
            PanelSection("By day", inset: true) {
                DayChart(days: project.byDay, currency: cur)
            }
            branchesSection
            PanelSection("Sessions · \(project.sessionsDetail.count)", inset: true) {
                SessionList(sessions: project.sessionsDetail,
                            threshold: report.config.dominantThreshold, currency: cur)
            }
        }
        .id(project.id)
    }

    // hero：项目名 + 金额；remote、路径、日期是小字注脚。
    private var header: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(project.name).font(.system(size: 15, weight: .semibold)).lineLimit(2)
                    .textSelection(.enabled)
                if project.pathMissing {
                    Badge(text: "path missing", style: .warn, help: "None of this project's local paths exist any more.")
                }
                if project.remote == nil {
                    Badge(text: "local", help: "No git remote; identified by its absolute path.")
                }
            }
            HeroAmount(value: Fmt.money(project.cost, currency: cur), size: 30)
            Text("\(project.sessions) session\(project.sessions == 1 ? "" : "s") · \(ShortDate.range(project.firstActive, project.lastActive))")
                .font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
            CostNote(text: report.costNote).padding(.top, 2)

            VStack(alignment: .leading, spacing: 2) {
                Group {
                    if let r = project.remote {
                        Label(r, systemImage: "link")
                    } else {
                        Label("No remote — local repository", systemImage: "internaldrive")
                    }
                }
                .font(.system(size: 10.5)).foregroundStyle(.secondary)
                .labelStyle(TightLabelStyle())
                .textSelection(.enabled)
                ProjectPathsView(paths: project.paths, pathMissing: project.pathMissing)
            }
            .padding(.top, 8)
        }
        .padding(.horizontal, Metrics.rowInset)
    }

    private var tokensSection: some View {
        let t = project.tokens
        return PanelSection("Tokens", inset: true) {
            Text("\(Fmt.tokens(t.total)) total").font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
        } content: {
            tokenBar(t)
                .padding(.bottom, 2)
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 8) {
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
        }
    }

    private func tok(_ label: String, _ v: Int, _ color: Color?, _ help: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            HStack(spacing: 4) {
                if let color { Circle().fill(color).frame(width: 6, height: 6) }
                else { Circle().strokeBorder(Color.secondary, lineWidth: 1).frame(width: 6, height: 6) }
                Text(label).font(.system(size: 10.5)).foregroundStyle(.secondary)
            }
            Text(Fmt.tokens(v)).font(.system(size: 13, weight: .medium, design: .rounded).monospacedDigit())
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
            let avail = max(geo.size.width - CGFloat(max(visible.count - 1, 0)), 0)
            HStack(spacing: 1) {
                ForEach(Array(visible.enumerated()), id: \.offset) { _, p in
                    Rectangle().fill(p.1)
                        .frame(width: max(avail * CGFloat(p.0) / CGFloat(total), 2))
                }
            }
            .clipShape(Capsule())
        }
        .frame(height: 4)
    }

    private var agentsSection: some View {
        let maxCost = project.byAgent.map(\.cost).max() ?? 0
        return PanelSection("By agent", inset: true) {
            VStack(spacing: 10) {
                ForEach(project.byAgent) { a in
                    HBarRow(label: a.label, color: AgentPalette.color(for: a.agent),
                            fraction: maxCost > 0 ? a.cost / maxCost : 0,
                            value: Fmt.money(a.cost, currency: cur),
                            detail: "\(a.sessions) sess · \(Fmt.tokens(a.tokens.total)) tok · \(Fmt.percent(project.cost > 0 ? a.cost / project.cost : 0))")
                }
            }
        }
    }

    private var modelsSection: some View {
        let all = project.byModel
        let shown = showAllModels ? all : Array(all.prefix(collapsedLimit))
        return PanelSection("By model", inset: true) {
            Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 6) {
                GridRow {
                    Text("Model").frame(maxWidth: .infinity, alignment: .leading); Text("Tokens").gridColumnAlignment(.trailing); Text("Cost").gridColumnAlignment(.trailing)
                }
                .font(.system(size: 10)).foregroundStyle(.tertiary)
                ForEach(shown) { m in
                    GridRow {
                        HStack(spacing: 5) {
                            AgentDot(agent: m.agent, size: 6)
                            Text(m.model).font(.system(size: 11, design: .monospaced)).lineLimit(1).truncationMode(.middle)
                            if m.estimated {
                                Badge(text: "est.", style: .warn,
                                      help: "Price unknown for this model; estimated from the most expensive tier of its family.")
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .help("\(m.model) (\(m.agent))")
                        Text(Fmt.tokens(m.tokens.total)).font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
                        Text(Fmt.money(m.cost, currency: cur)).font(.system(size: 11, weight: .medium)).monospacedDigit()
                    }
                }
            }
            if all.count > collapsedLimit {
                ShowAllButton(expanded: $showAllModels, total: all.count, noun: "models")
            }
        }
    }

    private var branchesSection: some View {
        let all = project.byBranch
        let shown = showAllBranches ? all : Array(all.prefix(collapsedLimit))
        return PanelSection("By branch", inset: true) {
            if all.isEmpty {
                Text("No branch information for this project.").font(.system(size: 11)).foregroundStyle(.secondary)
            } else {
                Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 6) {
                    GridRow {
                        Text("Branch").frame(maxWidth: .infinity, alignment: .leading); Text("Sessions").gridColumnAlignment(.trailing); Text("Cost").gridColumnAlignment(.trailing)
                    }
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
                    ForEach(shown) { b in
                        GridRow {
                            Text(b.branch).font(.system(size: 11, design: .monospaced)).lineLimit(1).truncationMode(.middle)
                                .foregroundStyle(b.branch == "(unknown)" ? .secondary : .primary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .help(b.branch)
                            Text("\(b.sessions)").font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
                            Text(Fmt.money(b.cost, currency: cur)).font(.system(size: 11, weight: .medium)).monospacedDigit()
                        }
                    }
                }
                if all.count > collapsedLimit {
                    ShowAllButton(expanded: $showAllBranches, total: all.count, noun: "branches")
                }
            }
        }
    }
}

/// 图标与文字间距收紧的 Label（系统默认间距在小字号下太松）。
struct TightLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            configuration.icon.font(.system(size: 9))
            configuration.title
        }
    }
}

struct BucketDetailView: View {
    let kind: BucketKind
    let report: UsageReport
    let onBack: () -> Void

    var body: some View {
        let b = kind == .unattributed ? report.buckets.unattributed : report.buckets.excluded
        DetailPage(backTitle: "Overview", onBack: onBack) {
            VStack(alignment: .leading, spacing: 3) {
                Text(kind == .unattributed ? "Unattributed" : "Excluded").font(.system(size: 15, weight: .semibold))
                HeroAmount(value: Fmt.money(b.cost, currency: report.currency), size: 30)
                Text("\(b.sessions) session\(b.sessions == 1 ? "" : "s") · \(ShortDate.range(b.firstActive, b.lastActive))")
                    .font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
                CostNote(text: report.costNote).padding(.top, 2)
                Text(AttributionInfo.explanation(kind == .unattributed ? "none" : "excluded",
                                                 threshold: report.config.dominantThreshold))
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 8)
            }
            .padding(.horizontal, Metrics.rowInset)
            PanelSection("Sessions · \(b.sessionsDetail.count)", inset: true) {
                SessionList(sessions: b.sessionsDetail, threshold: report.config.dominantThreshold,
                            currency: report.currency)
            }
        }
    }
}
