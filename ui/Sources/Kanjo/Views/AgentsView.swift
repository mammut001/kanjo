import AppKit
import SwiftUI
import KanjoCore

/// `--route agents:expanded:<agent>`：固定展开指定 agent 的行内详情，供截图检查。
enum AgentsRoute {
    static let expandedPrefix = "agents:expanded:"

    static func expandedAgent(in anchor: String?) -> String? {
        guard let a = anchor, a.hasPrefix(expandedPrefix) else { return nil }
        let agent = String(a.dropFirst(expandedPrefix.count))
        return agent.isEmpty ? nil : agent
    }
}

/// 终端风 Agent 视图：顶部范围选择 + 总计与 token 占比条 + 每个活跃 agent 一行（含分段刻度额度条）。
/// 悬停预览详情，点击固定展开，再次点击或按 Esc 收起。
struct AgentsView: View {
    let report: UsageReport
    var scrollAnchor: String? = nil
    let onSelectProject: (String) -> Void

    @Environment(\.isSnapshotMode) private var isSnapshotMode
    @AppStorage(SettingsKeys.appLanguage, store: AppDefaults.store) private var appLanguage = AppLanguage.system.rawValue
    @AppStorage(SettingsKeys.timeRange, store: AppDefaults.store) private var rangeRaw = TimeRange.all.rawValue

    @State private var pinnedAgent: String?
    @State private var hoveredAgent: String?
    @State private var hoverTask: Task<Void, Never>?
    @State private var escMonitor: Any?

    init(
        report: UsageReport,
        scrollAnchor: String? = nil,
        onSelectProject: @escaping (String) -> Void
    ) {
        self.report = report
        self.scrollAnchor = scrollAnchor
        self.onSelectProject = onSelectProject
        _pinnedAgent = State(initialValue: AgentsRoute.expandedAgent(in: scrollAnchor))
    }

    private var cur: String { report.currency }

    var body: some View {
        let ctx = RangeContext(report: report, raw: rangeRaw)
        let filtered = ctx.filtered()
        let summary = AgentSummary.build(report: report, filtered: filtered, quotaNow: effectiveQuotaNow)

        ScrollViewReader { proxy in
            OptionalScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    header(ctx: ctx, summary: summary)

                    if summary.rows.isEmpty {
                        Text(L10n.tr("agents.empty"))
                            .font(.system(size: 11.5))
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, Metrics.listInset)
                            .padding(.vertical, 12)
                    } else {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(Array(summary.rows.enumerated()), id: \.element.id) { index, row in
                                if index > 0 {
                                    RowDivider(inset: Metrics.listInset, trailing: Metrics.listInset)
                                }
                                let isPinned = pinnedAgent == row.agent
                                let isPreviewed = pinnedAgent == nil && hoveredAgent == row.agent
                                let isExpanded = isPinned || isPreviewed
                                AgentDetailRow(
                                    row: row,
                                    currency: cur,
                                    isExpanded: isExpanded,
                                    isPinned: isPinned,
                                    onTogglePin: {
                                        withAnimation(.easeOut(duration: 0.16)) {
                                            if pinnedAgent == row.agent {
                                                pinnedAgent = nil
                                            } else {
                                                pinnedAgent = row.agent
                                            }
                                            hoveredAgent = nil
                                        }
                                    },
                                    onHoverChange: { hovering in
                                        handleHover(agent: row.agent, hovering: hovering)
                                    },
                                    onSelectProject: onSelectProject
                                )
                                .id(rowAnchor(row.agent))
                            }
                        }
                    }

                    Text(L10n.tr("overview.generated_footer", Fmt.timestamp(report.generatedAt), report.schemaVersion))
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, Metrics.listInset)
                        .padding(.top, 2)
                }
                .padding(.horizontal, Metrics.flatPagePadding)
                .padding(.top, 8)
                .padding(.bottom, 10)
            }
            .onChange(of: scrollAnchor) { newValue in
                if let agent = AgentsRoute.expandedAgent(in: newValue) {
                    pinnedAgent = agent
                }
            }
            .task(id: scrollAnchor) {
                guard let agent = AgentsRoute.expandedAgent(in: scrollAnchor) else { return }
                try? await Task.sleep(nanoseconds: 250_000_000)
                proxy.scrollTo(rowAnchor(agent), anchor: .top)
            }
        }
        .onAppear { installEscMonitor() }
        .onDisappear {
            hoverTask?.cancel()
            removeEscMonitor()
        }
    }

    private var effectiveQuotaNow: Date {
        let realNow = Date()
        guard isSnapshotMode, let windows = report.quotaWindows, !windows.isEmpty else {
            return realNow
        }
        let allEnded = windows.values.allSatisfy { w in
            (ReportDates.parseTimestamp(w.weeklyResetsAt) ?? .distantPast) <= realNow
        }
        guard allEnded else { return realNow }
        let fiveHourResets = windows.values.compactMap { $0.fiveHourResetsAt.flatMap(ReportDates.parseTimestamp) }
        if let earliest5h = fiveHourResets.min() {
            return earliest5h.addingTimeInterval(-6660)
        }
        return ReportDates.parseTimestamp(report.generatedAt) ?? realNow
    }

    private func rowAnchor(_ agent: String) -> String {
        "agents:row:\(agent)"
    }

    private func handleHover(agent: String, hovering: Bool) {
        hoverTask?.cancel()
        if hovering {
            guard pinnedAgent == nil else { return }
            hoverTask = Task { @MainActor in
                try? await Task.sleep(nanoseconds: 280_000_000)
                guard !Task.isCancelled, pinnedAgent == nil else { return }
                withAnimation(.easeOut(duration: 0.15)) {
                    hoveredAgent = agent
                }
            }
        } else if hoveredAgent == agent {
            withAnimation(.easeOut(duration: 0.12)) {
                hoveredAgent = nil
            }
        }
    }

    private func installEscMonitor() {
        removeEscMonitor()
        escMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.keyCode == 53, pinnedAgent != nil {
                withAnimation(.easeOut(duration: 0.15)) {
                    pinnedAgent = nil
                }
                return nil
            }
            return event
        }
    }

    private func removeEscMonitor() {
        if let escMonitor {
            NSEvent.removeMonitor(escMonitor)
            self.escMonitor = nil
        }
    }

    // MARK: - 顶部汇总与占比条

    private func header(ctx: RangeContext, summary: AgentSummaryReport) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 6) {
                if let note = report.costNoteDisplayText {
                    Image(systemName: "info.circle")
                        .font(.system(size: 10.5))
                        .foregroundStyle(.secondary)
                        .hoverTip(note)
                }
                Spacer(minLength: 4)
                RangePicker(
                    raw: $rangeRaw,
                    effective: ctx.range,
                    resetAvailable: ctx.resetAvailable,
                    cycleAvailable: ctx.cycleAvailable
                )
            }

            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(Fmt.money(summary.totalCost, currency: cur))
                    .font(.system(size: 22, weight: .semibold, design: .rounded).monospacedDigit())
                    .lineLimit(1)
                Text("·")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(.tertiary)
                Text(L10n.tr("overview.tokens_count", Fmt.tokens(summary.totalTokens)))
                    .font(.system(size: 13.5, weight: .medium, design: .rounded).monospacedDigit())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .hoverTip(report.costNoteDisplayText)

            if let caption = ctx.caption {
                RangeCaption(text: caption, help: ctx.captionHelp)
            }

            if !summary.rows.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    proportionBar(rows: summary.rows)
                    topLegend(rows: summary.rows)
                }
            }
        }
        .padding(.horizontal, Metrics.listInset)
    }

    private func proportionBar(rows: [AgentSummaryRow]) -> some View {
        GeometryReader { geo in
            let gap: CGFloat = 1.5
            let count = rows.count
            let avail = max(geo.size.width - CGFloat(max(count - 1, 0)) * gap, 0)
            HStack(spacing: gap) {
                ForEach(rows) { row in
                    let w = max(avail * CGFloat(max(row.share, 0)), 2)
                    Rectangle()
                        .fill(AgentPalette.color(for: row.agent))
                        .frame(width: w)
                        .hoverTip("\(row.label) · \(Fmt.tokens(row.tokens)) (\(Fmt.percent(row.share)))")
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 3.5, style: .continuous))
        }
        .frame(height: 8)
        .accessibilityLabel(L10n.tr("agents.tokens_share_help"))
    }

    private func topLegend(rows: [AgentSummaryRow]) -> some View {
        let maxShown = 4
        let shown = Array(rows.prefix(maxShown))
        let overflow = max(0, rows.count - maxShown)
        return FlowLayout(spacing: 9, lineSpacing: 3) {
            ForEach(shown) { row in
                HStack(spacing: 4) {
                    RoundedRectangle(cornerRadius: 1.5, style: .continuous)
                        .fill(AgentPalette.color(for: row.agent))
                        .frame(width: 6, height: 6)
                    Text("\(row.label) \(Fmt.percent(row.share))")
                        .font(.system(size: 10).monospacedDigit())
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            if overflow > 0 {
                Text("+\(overflow)")
                    .font(.system(size: 10).monospacedDigit())
                    .foregroundStyle(.tertiary)
            }
        }
    }
}

// MARK: - 单个 Agent 行 + 行内详情

private struct AgentDetailRow: View {
    let row: AgentSummaryRow
    let currency: String
    let isExpanded: Bool
    let isPinned: Bool
    let onTogglePin: () -> Void
    let onHoverChange: (Bool) -> Void
    let onSelectProject: (String) -> Void

    @State private var headerHover = false

    private var accentColor: Color { AgentPalette.color(for: row.agent) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button(action: onTogglePin) {
                rowHeader
                    .padding(.horizontal, Metrics.listInset)
                    .padding(.vertical, 8)
                    .contentShape(Rectangle())
            }
            .buttonStyle(RowButtonStyle(highlighted: headerHover || isPinned, cornerRadius: Metrics.rowRadius))
            .onHover { headerHover = $0 }
            .hoverTip(isPinned ? L10n.tr("agents.row.collapse_help") : L10n.tr("agents.row.expand_help"))

            if isExpanded {
                expandedDrawer
                    .padding(.horizontal, Metrics.listInset)
                    .padding(.bottom, 10)
                    .padding(.top, 2)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .onHover(perform: onHoverChange)
    }

    // MARK: Line 1 + Quota tick bars

    private var rowHeader: some View {
        VStack(alignment: .leading, spacing: 5) {
            ViewThatFits(in: .horizontal) {
                // 优先单行展示：色点 + agent 名 + (订阅与月费) ... token + 花费 + 倍数
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    agentIdentity(inlinePlan: true)
                    Spacer(minLength: 6)
                    metricsCluster
                }
                // 放不下时把订阅名与月费折到第二行小字，保证 token 数、花费、倍数始终完整可见
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: 5) {
                        agentIdentity(inlinePlan: false)
                        Spacer(minLength: 6)
                        metricsCluster
                    }
                    if let sub = row.subscription {
                        planCaption(sub)
                            .padding(.leading, 13)
                    }
                }
            }

            if !row.quotaRows.isEmpty {
                let labelWidth = quotaLabelWidth(for: row.quotaRows)
                VStack(alignment: .leading, spacing: 3.5) {
                    ForEach(row.quotaRows) { q in
                        QuotaTickRow(
                            agent: row.agent,
                            row: q,
                            labelWidth: labelWidth
                        )
                    }
                }
                .padding(.leading, 13)
            }
        }
        .monospacedDigit()
    }

    @ViewBuilder
    private func agentIdentity(inlinePlan: Bool) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Circle()
                .fill(accentColor)
                .frame(width: 7, height: 7)
                .alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
            Text(row.label)
                .font(.system(size: 12.5, weight: .semibold))
                .lineLimit(1)
                .fixedSize(horizontal: true, vertical: false)
            if inlinePlan, let sub = row.subscription {
                planCaption(sub)
                    .fixedSize(horizontal: true, vertical: false)
            }
        }
    }

    private func planCaption(_ sub: Subscription) -> some View {
        let price = Fmt.perMonth(sub.monthlyPriceUsd, currency: currency)
        let text = sub.monthlyPriceUsd != nil ? "\(sub.planLabel) · \(price)" : sub.planLabel
        return Text(text)
            .font(.system(size: 10))
            .foregroundStyle(.secondary)
            .lineLimit(1)
    }

    private var metricsCluster: some View {
        HStack(alignment: .firstTextBaseline, spacing: 5) {
            Text(Fmt.tokens(row.tokens))
                .font(.system(size: 12, weight: .semibold, design: .rounded))
                .foregroundStyle(.primary)
                .fixedSize(horizontal: true, vertical: false)
            Text(Fmt.money(row.cost, currency: currency))
                .font(.system(size: 11, weight: .medium, design: .rounded))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: true, vertical: false)
            if let m = row.multiplier {
                Text(Fmt.multiple(m))
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(accentColor)
                    .fixedSize(horizontal: true, vertical: false)
            }
        }
    }

    private func quotaLabelWidth(for rows: [QuotaRow]) -> CGFloat {
        let hasLongExtra = rows.contains { $0.title.count > 10 }
        return hasLongExtra ? 78 : 46
    }

    // MARK: 行内展开详情

    private var expandedDrawer: some View {
        HStack(alignment: .top, spacing: 6) {
            RoundedRectangle(cornerRadius: 1, style: .continuous)
                .fill(accentColor)
                .frame(width: 2.5)
                .padding(.vertical, 2)

            VStack(alignment: .leading, spacing: 9) {
                tokensBlock
                Divider().opacity(0.45)
                perfBlock
                if !row.models.isEmpty {
                    Divider().opacity(0.45)
                    modelsBlock
                }
                if !row.projectShares.isEmpty {
                    Divider().opacity(0.45)
                    whereMoneyWentBlock
                }
            }
            .padding(9)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(AgentPalette.groupFill)
            )
        }
        .monospacedDigit()
    }

    private var tokensBlock: some View {
        let t = row.tokenBreakdown
        return VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                SectionTitle(L10n.tr("agents.detail.tokens"))
                Spacer(minLength: 6)
                Text("\(L10n.tr("agents.detail.cache_hit")) \(row.cacheHitRate.map(Fmt.percent) ?? "—")")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.secondary)
            }
            tokenCompositionBar(t)
            HStack(spacing: 8) {
                tokenStat(L10n.tr("project.token.input"), t.input, AgentPalette.tokenInput)
                tokenStat(L10n.tr("project.token.output"), t.output, AgentPalette.tokenOutput)
                tokenStat(L10n.tr("project.token.cache_read"), t.cacheRead, AgentPalette.tokenCacheRead)
                tokenStat(L10n.tr("project.token.cache_write"), t.cacheWrite, AgentPalette.tokenCacheWrite)
            }
        }
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
            .clipShape(Capsule())
        }
        .frame(height: 3.5)
    }

    private func tokenStat(_ label: String, _ count: Int, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            HStack(spacing: 3.5) {
                Circle().fill(color).frame(width: 5, height: 5)
                Text(label)
                    .font(.system(size: 9.5))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Text(Fmt.tokens(count))
                .font(.system(size: 11, weight: .medium, design: .rounded))
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var perfBlock: some View {
        let perf = row.perf
        let speedStr = perf?.tps.map { L10n.tr("agents.detail.tok_per_sec", PerfStats.formatSpeedNumber($0)) } ?? "—"
        let ttftStr = PerfStats.formatTTFT(perf?.ttftMedian)
        let sampleCaption: String = {
            guard let n = perf?.sampleCount, n > 0 else {
                return L10n.tr("agents.detail.no_samples")
            }
            return n == 1
                ? L10n.tr("agents.detail.samples.singular", n)
                : L10n.tr("agents.detail.samples.plural", n)
        }()

        return VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline) {
                SectionTitle(L10n.tr("agents.detail.performance"))
                Spacer(minLength: 6)
                Text(sampleCaption)
                    .font(.system(size: 9.5))
                    .foregroundStyle(.tertiary)
            }
            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(L10n.tr("agents.detail.output_speed"))
                        .font(.system(size: 9.5))
                        .foregroundStyle(.secondary)
                    Text(speedStr)
                        .font(.system(size: 11.5, weight: .medium, design: .rounded))
                        .foregroundStyle(perf?.tps == nil ? .tertiary : .primary)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(L10n.tr("agents.detail.ttft_median"))
                        .font(.system(size: 9.5))
                        .foregroundStyle(.secondary)
                    Text(ttftStr)
                        .font(.system(size: 11.5, weight: .medium, design: .rounded))
                        .foregroundStyle(perf?.ttftMedian == nil ? .tertiary : .primary)
                }
                Spacer(minLength: 0)
            }
        }
    }

    private var modelsBlock: some View {
        VStack(alignment: .leading, spacing: 5) {
            SectionTitle(L10n.tr("agents.detail.models"))
            Grid(alignment: .leading, horizontalSpacing: 4.5, verticalSpacing: 4) {
                GridRow {
                    Text(L10n.tr("project.model")).frame(maxWidth: .infinity, alignment: .leading)
                    Text(L10n.tr("project.section.tokens")).gridColumnAlignment(.trailing)
                    Text(L10n.tr("agents.detail.models.hit")).gridColumnAlignment(.trailing)
                    Text(L10n.tr("agents.detail.models.speed")).gridColumnAlignment(.trailing)
                    Text(L10n.tr("project.cost")).gridColumnAlignment(.trailing)
                }
                .font(.system(size: 9.5))
                .foregroundStyle(.tertiary)

                ForEach(row.models) { m in
                    let speed = m.perf?.tps.map { "\(PerfStats.formatSpeedNumber($0))/s" } ?? "—"
                    let hit = m.cacheHitRate.map(Fmt.percent) ?? "—"
                    GridRow {
                        HStack(spacing: 3) {
                            Text(m.model)
                                .font(.system(size: 9.5, design: .monospaced))
                                .lineLimit(1)
                                .truncationMode(.middle)
                            if m.estimated {
                                Badge(text: L10n.tr("project.estimated"), style: .warn,
                                      help: L10n.tr("project.estimated_help"))
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)

                        Text(Fmt.tokens(m.tokens.total))
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                        Text(hit)
                            .font(.system(size: 9.5))
                            .foregroundStyle(m.cacheHitRate == nil ? .tertiary : .secondary)
                        Text(speed)
                            .font(.system(size: 9.5))
                            .foregroundStyle(m.perf?.tps == nil ? .tertiary : .secondary)
                        Text(Fmt.money(m.cost, currency: currency))
                            .font(.system(size: 10, weight: .medium))
                    }
                }
            }
        }
    }

    private var whereMoneyWentBlock: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionTitle(L10n.tr("agents.detail.where_money_went"))
            projectProportionBar
            FlowLayout(spacing: 8, lineSpacing: 4) {
                ForEach(Array(row.projectShares.enumerated()), id: \.element.id) { idx, seg in
                    Button {
                        onSelectProject(seg.projectId)
                    } label: {
                        HStack(spacing: 4) {
                            RoundedRectangle(cornerRadius: 1.5, style: .continuous)
                                .fill(projectSegmentColor(index: idx))
                                .frame(width: 6, height: 6)
                            Text("\(seg.projectName) \(Fmt.percent(seg.share))")
                                .font(.system(size: 10))
                                .foregroundStyle(.primary)
                                .lineLimit(1)
                        }
                        .padding(.horizontal, 4)
                        .padding(.vertical, 1.5)
                        .background(RoundedRectangle(cornerRadius: 4, style: .continuous).fill(Color.primary.opacity(0.05)))
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .hoverTip("\(seg.projectName) · \(Fmt.money(seg.cost, currency: currency)) (\(Fmt.percent(seg.share))) · \(L10n.tr("agents.detail.open_project_help", seg.projectName))")
                }
                if let others = row.othersProjectShare {
                    HStack(spacing: 4) {
                        RoundedRectangle(cornerRadius: 1.5, style: .continuous)
                            .fill(AgentPalette.neutral)
                            .frame(width: 6, height: 6)
                        Text("\(L10n.tr("agents.detail.others")) (\(others.count)) \(Fmt.percent(others.share))")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    .padding(.horizontal, 4)
                    .padding(.vertical, 1.5)
                    .hoverTip("\(L10n.tr("agents.detail.others")) (\(others.count)) · \(Fmt.money(others.cost, currency: currency)) (\(Fmt.percent(others.share)))")
                }
            }
        }
    }

    private var projectProportionBar: some View {
        let segCount = row.projectShares.count + (row.othersProjectShare == nil ? 0 : 1)
        let gap: CGFloat = 1.5
        return GeometryReader { geo in
            let avail = max(geo.size.width - CGFloat(max(segCount - 1, 0)) * gap, 0)
            HStack(spacing: gap) {
                ForEach(Array(row.projectShares.enumerated()), id: \.element.id) { idx, seg in
                    Button {
                        onSelectProject(seg.projectId)
                    } label: {
                        Rectangle()
                            .fill(projectSegmentColor(index: idx))
                            .frame(width: max(avail * CGFloat(max(seg.share, 0)), 3))
                    }
                    .buttonStyle(.plain)
                    .hoverTip("\(seg.projectName) · \(Fmt.money(seg.cost, currency: currency)) (\(Fmt.percent(seg.share)))")
                }
                if let others = row.othersProjectShare {
                    Rectangle()
                        .fill(AgentPalette.neutral)
                        .frame(width: max(avail * CGFloat(max(others.share, 0)), 3))
                        .hoverTip("\(L10n.tr("agents.detail.others")) (\(others.count)) · \(Fmt.money(others.cost, currency: currency)) (\(Fmt.percent(others.share)))")
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 3, style: .continuous))
        }
        .frame(height: 7)
    }

    private func projectSegmentColor(index: Int) -> Color {
        if index == 0 {
            return accentColor
        }
        let paletteKeys = ["codex", "grok", "antigravity", "opencode", "copilot"]
            .filter { $0 != row.agent }
        let key = paletteKeys[(index - 1) % paletteKeys.count]
        return AgentPalette.color(for: key)
    }
}

// MARK: - 分段刻度进度条（终端风）

/// 20 根圆角竖条组成的额度刻度条：已用部分用 agent 色（≥80% 警示色，≥95% 红色），空刻度淡色。
struct QuotaTickBar: View {
    let percent: Double?
    let color: Color
    var segments: Int = 20

    var body: some View {
        let filled: Int = {
            guard let p = percent else { return 0 }
            let clamped = min(100, max(0, p))
            return Int((clamped / 100.0 * Double(segments)).rounded())
        }()

        HStack(spacing: 1) {
            ForEach(0..<segments, id: \.self) { i in
                RoundedRectangle(cornerRadius: 0.75, style: .continuous)
                    .fill(i < filled ? color : Color.primary.opacity(0.14))
                    .frame(width: 2, height: 9)
            }
        }
        .fixedSize()
    }
}

private struct QuotaTickRow: View {
    let agent: String
    let row: QuotaRow
    let labelWidth: CGFloat

    private var barColor: Color {
        switch SubscriptionValue.level(row.percent) {
        case .normal: return AgentPalette.color(for: agent)
        case .warning: return AgentPalette.quotaWarn
        case .critical: return AgentPalette.bad
        }
    }

    var body: some View {
        HStack(alignment: .center, spacing: 4.5) {
            Text(row.title)
                .font(.system(size: 9.5))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
                .frame(width: labelWidth, alignment: .leading)

            QuotaTickBar(percent: row.percent, color: barColor)

            Text(row.percent.map { "\(Int($0.rounded()))%" } ?? "—")
                .font(.system(size: 10, weight: .semibold, design: .rounded))
                .foregroundStyle(row.percent == nil ? AnyShapeStyle(.tertiary) : AnyShapeStyle(barColor))
                .frame(width: 24, alignment: .trailing)

            Text(row.detail)
                .font(.system(size: 9))
                .foregroundStyle(row.percent == nil ? .tertiary : .secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
                .frame(maxWidth: .infinity, alignment: .trailing)
                .hoverTip(row.detail)
        }
        .monospacedDigit()
    }
}
