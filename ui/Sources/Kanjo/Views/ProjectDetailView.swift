import SwiftUI
import KanjoCore

/// 详情页 Locations 一节展开后的路径列表：只列主路径，临时目录（scratchpad / worktree 等）折叠在一个文字按钮后面。
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
                .help(L10n.tr("project.locations.temporary_help"))
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
        let noun = temporary.count == 1
            ? L10n.tr("project.locations.temporary.singular", temporary.count)
            : L10n.tr("project.locations.temporary.plural", temporary.count)
        if showTemporary {
            return temporary.count == 1
                ? L10n.tr("project.locations.hide_temp.singular", temporary.count)
                : L10n.tr("project.locations.hide_temp.plural", temporary.count)
        }
        return noun
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
    var scrollTo: String? = nil     // 开发开关 --route 用：出现后滚到这个 id
    let onBack: () -> Void
    @ViewBuilder var content: () -> Content

    var body: some View {
        ScrollViewReader { proxy in
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
            .task(id: scrollTo) {
                guard let a = scrollTo else { return }
                try? await Task.sleep(nanoseconds: 300_000_000)
                proxy.scrollTo(a, anchor: .bottom)
            }
        }
    }
}

struct ProjectDetailView: View {
    static let bottomAnchor = "detail-bottom"
    static let locationsOpenAnchor = "detail-locations-open"

    let project: Project
    let report: UsageReport
    var devAnchor: String? = nil
    let onBack: () -> Void

    @AppStorage(SettingsKeys.appLanguage) private var appLanguage = AppLanguage.system.rawValue
    @AppStorage(SettingsKeys.timeRange) private var rangeRaw = TimeRange.all.rawValue
    @State private var showAllModels = false
    @State private var showAllBranches = false
    @State private var showLocations = false
    private let collapsedLimit = 8

    private var cur: String { report.currency }
    private var devScrollTarget: String? {
        devAnchor == Self.bottomAnchor || devAnchor == Self.locationsOpenAnchor ? Self.bottomAnchor : nil
    }

    // 范围下：金额、tokens（只有 total）、By agent、By day、热力条、Sessions 按范围；
    // By model / By branch 没有按天数据，不过滤，标题旁标「All time」。
    var body: some View {
        let ctx = RangeContext(report: report, raw: rangeRaw)
        let f = ctx.filter(project)
        let shown = f.projected
        DetailPage(backTitle: L10n.tr("project.navigation.projects"), scrollTo: devScrollTarget, onBack: onBack) {
            header(ctx, shown)
            tokensSection(shown, isAll: ctx.isAll)
            agentsSection(shown)
            modelsSection(isAll: ctx.isAll)
            PanelSection(L10n.tr("project.section.by_day"), inset: true) {
                DayChart(days: shown.byDay, currency: cur, color: ProjectTint.color(of: shown))
            }
            branchesSection(isAll: ctx.isAll)
            PanelSection(L10n.tr("project.section.sessions", shown.sessionsDetail.count), inset: true) {
                SessionList(sessions: shown.sessionsDetail,
                            threshold: report.config.dominantThreshold, currency: cur)
            }
            locationsSection.id(Self.bottomAnchor)
        }
        .id(project.id)
        .onAppear { if devAnchor == Self.locationsOpenAnchor { showLocations = true } }
    }

    // hero：项目名 + 范围控件 + 金额（含 cost_note tooltip 和 info 图标）；日期、范围说明、remote 是小字注脚。本地路径放在页面最底部的 Locations。
    private func header(_ ctx: RangeContext, _ shown: Project) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(project.name).font(.system(size: 15, weight: .semibold)).lineLimit(2)
                    .textSelection(.enabled)
                if project.pathMissing {
                    Badge(text: L10n.tr("overview.badge.path_missing"), style: .warn, help: L10n.tr("overview.badge.path_missing_help"))
                }
                if project.remote == nil {
                    Badge(text: L10n.tr("overview.badge.local"), help: L10n.tr("overview.badge.local_help"))
                }
            }
            RangePicker(raw: $rangeRaw, effective: ctx.range, resetAvailable: ctx.resetAvailable,
                        cycleAvailable: ctx.cycleAvailable)
                .padding(.top, 4).padding(.bottom, 2)
            HStack(alignment: .bottom, spacing: 10) {
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    HeroAmount(value: Fmt.money(shown.cost, currency: cur), size: 30)
                    if let note = report.costNoteDisplayText {
                        Image(systemName: "info.circle")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                            .help(note)
                    }
                }
                .helpIfPresent(report.costNoteDisplayText)
                Spacer(minLength: 0)
                VStack(alignment: .trailing, spacing: 3) {
                    Text(L10n.tr("project.last_8_weeks")).font(.system(size: 9.5)).foregroundStyle(.secondary)
                    HeatStripView(weeks: shown.heatWeeks(endingOn: report.heatEndDate),
                                  agentLabels: report.agentLabels, currency: cur,
                                  cell: CGSize(width: 12, height: 20), radius: 3)
                }
                .padding(.bottom, 5)
            }
            let usageStr = shown.firstActive == nil ? L10n.tr("project.no_usage") : ShortDate.range(shown.firstActive, shown.lastActive)
            let sessKey = shown.sessions == 1 ? "project.subtitle.singular" : "project.subtitle.plural"
            Text(L10n.tr(sessKey, shown.sessions, usageStr))
                .font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
            if let caption = ctx.caption {
                RangeCaption(text: caption).padding(.top, 1)
            }

            Group {
                if let r = project.remote {
                    Label(r, systemImage: "link")
                } else {
                    Label(L10n.tr("project.local_repo"), systemImage: "internaldrive")
                }
            }
            .font(.system(size: 10.5)).foregroundStyle(.secondary)
            .labelStyle(TightLabelStyle())
            .lineLimit(1).truncationMode(.middle)
            .textSelection(.enabled)
            .padding(.top, 8)
        }
        .padding(.horizontal, Metrics.rowInset)
    }

    /// 最底部的本地路径：默认折叠成一行「7 paths · 16 temporary」+ Show；展开后是主路径和折叠的临时路径。
    private var locationsSection: some View {
        let split = splitPaths(project.paths)
        return VStack(alignment: .leading, spacing: 6) {
            SectionTitle(L10n.tr("project.section.locations"))
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(locationsCaption(primary: split.primary.count, temporary: split.temporary.count))
                    .font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                if project.pathMissing {
                    Badge(text: L10n.tr("overview.badge.path_missing"), style: .warn, help: L10n.tr("overview.badge.path_missing_help"))
                }
                Spacer(minLength: 8)
                if !project.paths.isEmpty {
                    Button {
                        withAnimation(.easeOut(duration: 0.15)) { showLocations.toggle() }
                    } label: {
                        HStack(spacing: 3) {
                            Text(showLocations ? L10n.tr("common.hide") : L10n.tr("common.show"))
                            Image(systemName: showLocations ? "chevron.down" : "chevron.right")
                                .font(.system(size: 8, weight: .semibold))
                        }
                        .font(.system(size: 11))
                        .foregroundStyle(Color.accentColor)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            if showLocations {
                ProjectPathsView(paths: project.paths, pathMissing: project.pathMissing)
                    .padding(.top, 2)
            }
        }
        .padding(.horizontal, Metrics.rowInset)
    }

    private func locationsCaption(primary: Int, temporary: Int) -> String {
        if primary + temporary == 0 { return L10n.tr("project.locations.no_local_paths") }
        if primary == 0 {
            let key = temporary == 1 ? "project.locations.temporary.singular" : "project.locations.temporary.plural"
            return L10n.tr(key, temporary)
        }
        let mainKey = primary == 1 ? "project.locations.path.singular" : "project.locations.path.plural"
        let main = L10n.tr(mainKey, primary)
        return temporary == 0 ? main : L10n.tr("project.locations.combined", main, temporary)
    }

    /// 输入 / 输出 / 缓存的拆分只有全量数据：非 All 范围只显示 total。
    @ViewBuilder private func tokensSection(_ shown: Project, isAll: Bool) -> some View {
        if isAll {
            tokensBreakdown(shown.tokens)
        } else {
            PanelSection(L10n.tr("project.section.tokens"), inset: true) {
                Text(L10n.tr("project.tokens_total", Fmt.tokens(shown.tokens.total))).font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
            } content: {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(Fmt.tokens(shown.tokens.total))
                        .font(.system(size: 13, weight: .medium, design: .rounded).monospacedDigit())
                    Text(L10n.tr("project.breakdown_all_only"))
                        .font(.system(size: 10.5)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func tokensBreakdown(_ t: Tokens) -> some View {
        PanelSection(L10n.tr("project.section.tokens"), inset: true) {
            Text(L10n.tr("project.tokens_total", Fmt.tokens(t.total))).font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
        } content: {
            tokenBar(t)
                .padding(.bottom, 2)
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 8) {
                GridRow {
                    tok(L10n.tr("project.token.input"), t.input, AgentPalette.tokenInput, L10n.tr("project.token.input_help"))
                    tok(L10n.tr("project.token.output"), t.output, AgentPalette.tokenOutput, L10n.tr("project.token.output_help"))
                    tok(L10n.tr("project.token.thinking"), t.thinking, nil, L10n.tr("project.token.thinking_help"))
                }
                GridRow {
                    tok(L10n.tr("project.token.cache_read"), t.cacheRead, AgentPalette.tokenCacheRead, L10n.tr("project.token.cache_read_help"))
                    tok(L10n.tr("project.token.cache_write"), t.cacheWrite, AgentPalette.tokenCacheWrite, L10n.tr("project.token.cache_write_help"))
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

    private func agentsSection(_ shown: Project) -> some View {
        let maxCost = shown.byAgent.map(\.cost).max() ?? 0
        let shares = SubscriptionValue.shares(project: project.id, report: report)
        return PanelSection(L10n.tr("project.section.by_agent"), inset: true) {
            VStack(alignment: .leading, spacing: 10) {
                if shown.byAgent.isEmpty {
                    Text(L10n.tr("project.no_usage_range")).font(.system(size: 11)).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                ForEach(shown.byAgent) { a in
                    HBarRow(label: a.label, color: AgentPalette.color(for: a.agent),
                            fraction: maxCost > 0 ? a.cost / maxCost : 0,
                            value: Fmt.money(a.cost, currency: cur),
                            detail: L10n.tr("project.agent_detail", a.sessions, Fmt.tokens(a.tokens.total), Fmt.percent(shown.cost > 0 ? a.cost / shown.cost : 0)))
                }
                if !shares.isEmpty {
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(shares) { s in
                            Text(L10n.tr("project.cycle_share", Self.shareText(s.share), s.planLabel))
                                .fixedSize(horizontal: false, vertical: true)
                                .help(report.subscriptions?[s.agent].map {
                                    Fmt.cycleCaption($0, timezone: RangeEngine.timezone(of: report))
                                } ?? L10n.tr("fmt.cycle_dates_unavailable"))
                        }
                    }
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .padding(.top, 1)
                }
            }
        }
    }

    /// 0 显示成「0%」，其余沿用 Fmt.percent（38% / 0.4%）。
    private static func shareText(_ share: Double) -> String {
        share == 0 ? "0%" : Fmt.percent(share)
    }

    private func modelsSection(isAll: Bool) -> some View {
        let all = project.byModel
        let shown = showAllModels ? all : Array(all.prefix(collapsedLimit))
        return PanelSection(L10n.tr("project.section.by_model"), inset: true) {
            if !isAll { AllTimeBadge(what: L10n.tr("project.noun.models")) }
        } content: {
            Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 6) {
                GridRow {
                    Text(L10n.tr("project.model")).frame(maxWidth: .infinity, alignment: .leading); Text(L10n.tr("project.section.tokens")).gridColumnAlignment(.trailing); Text(L10n.tr("project.cost")).gridColumnAlignment(.trailing)
                }
                .font(.system(size: 10)).foregroundStyle(.tertiary)
                ForEach(shown) { m in
                    GridRow {
                        HStack(spacing: 5) {
                            AgentDot(agent: m.agent, size: 6)
                            Text(m.model).font(.system(size: 11, design: .monospaced)).lineLimit(1).truncationMode(.middle)
                            if m.estimated {
                                Badge(text: L10n.tr("project.estimated"), style: .warn,
                                      help: L10n.tr("project.estimated_help"))
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
                ShowAllButton(expanded: $showAllModels, total: all.count, noun: L10n.tr("project.noun.models"))
            }
        }
    }

    private func branchesSection(isAll: Bool) -> some View {
        let all = project.byBranch
        let shown = showAllBranches ? all : Array(all.prefix(collapsedLimit))
        return PanelSection(L10n.tr("project.section.by_branch"), inset: true) {
            if !isAll { AllTimeBadge(what: L10n.tr("project.noun.branches")) }
        } content: {
            if all.isEmpty {
                Text(L10n.tr("project.no_branch_info")).font(.system(size: 11)).foregroundStyle(.secondary)
            } else {
                Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 6) {
                    GridRow {
                        Text(L10n.tr("project.branch")).frame(maxWidth: .infinity, alignment: .leading); Text(L10n.tr("project.noun.sessions").capitalized).gridColumnAlignment(.trailing); Text(L10n.tr("project.cost")).gridColumnAlignment(.trailing)
                    }
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
                    ForEach(shown) { b in
                        GridRow {
                            Text(b.branch == "(unknown)" ? L10n.tr("common.unknown") : b.branch)
                                .font(.system(size: 11, design: .monospaced)).lineLimit(1).truncationMode(.middle)
                                .foregroundStyle(b.branch == "(unknown)" ? .secondary : .primary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .help(b.branch)
                            Text("\(b.sessions)").font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
                            Text(Fmt.money(b.cost, currency: cur)).font(.system(size: 11, weight: .medium)).monospacedDigit()
                        }
                    }
                }
                if all.count > collapsedLimit {
                    ShowAllButton(expanded: $showAllBranches, total: all.count, noun: L10n.tr("project.noun.branches"))
                }
            }
        }
    }
}

/// 范围下不能按天过滤的一节（By model / By branch）：标题右侧的「All time」小标签。
struct AllTimeBadge: View {
    let what: String
    var body: some View {
        Badge(text: L10n.tr("project.badge.all_time"), help: L10n.tr("project.badge.all_time_help", what))
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

    @AppStorage(SettingsKeys.appLanguage) private var appLanguage = AppLanguage.system.rawValue
    @AppStorage(SettingsKeys.timeRange) private var rangeRaw = TimeRange.all.rawValue

    // 桶没有 by_day：范围下按会话的 started 过滤，金额是这些会话之和。
    var body: some View {
        let ctx = RangeContext(report: report, raw: rangeRaw)
        let raw = kind == .unattributed ? report.buckets.unattributed : report.buckets.excluded
        let b = RangeEngine.filter(raw, range: ctx.spec)
        DetailPage(backTitle: L10n.tr("disk.navigation.overview"), onBack: onBack) {
            VStack(alignment: .leading, spacing: 3) {
                Text(kind == .unattributed ? L10n.tr("overview.unattributed") : L10n.tr("overview.excluded")).font(.system(size: 15, weight: .semibold))
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    HeroAmount(value: Fmt.money(b.cost, currency: report.currency), size: 30)
                    if let note = report.costNoteDisplayText {
                        Image(systemName: "info.circle")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                            .help(note)
                    }
                }
                .helpIfPresent(report.costNoteDisplayText)
                let usageStr = b.firstActive == nil ? L10n.tr("project.no_usage") : ShortDate.range(b.firstActive, b.lastActive)
                let sessKey = b.sessions == 1 ? "project.subtitle.singular" : "project.subtitle.plural"
                Text(L10n.tr(sessKey, b.sessions, usageStr))
                    .font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
                if let caption = ctx.caption {
                    RangeCaption(text: caption + L10n.tr("project.bucket.by_session_start")).padding(.top, 1)
                }
                Text(AttributionInfo.explanation(kind == .unattributed ? "none" : "excluded",
                                                 threshold: report.config.dominantThreshold))
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 8)
            }
            .padding(.horizontal, Metrics.rowInset)
            PanelSection(L10n.tr("project.section.sessions", b.sessionsDetail.count), inset: true) {
                SessionList(sessions: b.sessionsDetail, threshold: report.config.dominantThreshold,
                            currency: report.currency)
            }
        }
    }
}
