import SwiftUI
import KanjoCore

struct OverviewView: View {
    static let bottomAnchor = "overview-bottom"

    let report: UsageReport
    var scrollAnchor: String? = nil
    let onSelect: (Route) -> Void
    let onSetRenewalDay: (String) -> Void

    @AppStorage(SettingsKeys.hiddenProjects) private var hiddenRaw = ""
    @AppStorage(SettingsKeys.pinnedProjects) private var pinnedRaw = ""
    @AppStorage(SettingsKeys.timeRange) private var rangeRaw = TimeRange.all.rawValue
    @State private var showHidden = false

    private var cur: String { report.currency }

    /// 报告中出现的所有 agent（按总花费降序），用于图例。
    private var agents: [(key: String, label: String)] {
        var cost: [String: Double] = [:], label: [String: String] = [:]
        for p in report.projects {
            for a in p.byAgent { cost[a.agent, default: 0] += a.cost; label[a.agent] = a.label }
        }
        return cost.sorted { $0.value > $1.value }.map { ($0.key, label[$0.key] ?? $0.key) }
    }

    /// 列表里的项目都是按当前范围过滤后的值（`projected`）。
    /// 按范围内 cost 降序；然后置顶的在前、隐藏的分出去；范围内没有用量的（All 下不会有）单独计数、不显示。
    private struct Lists {
        var visible: [Project]
        var hidden: [Project]
        var idle: Int
    }

    private func arrange(_ f: FilteredReport, isAll: Bool) -> Lists {
        let sorted = f.projects.sorted { $0.cost > $1.cost }
        let a = ProjectPrefs.arrange(sorted, id: \.id,
                                     pinned: ProjectPrefs.parse(pinnedRaw), hidden: ProjectPrefs.parse(hiddenRaw))
        let shown = isAll ? a.visible : a.visible.filter(\.hasUsage)
        return Lists(visible: shown.map(\.projected), hidden: a.hidden.map(\.projected),
                     idle: a.visible.count - shown.count)
    }

    // 三段节奏：文字（hero）→ 图形（马赛克）→ 列表。列表行直接放在面板上，没有分组底色。
    var body: some View {
        let ctx = RangeContext(report: report, raw: rangeRaw)
        let f = ctx.filtered()
        let lists = arrange(f, isAll: ctx.isAll)
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: Metrics.sectionSpacing) {
                    VStack(alignment: .leading, spacing: 14) {
                        hero(ctx, f, visible: lists.visible, hiddenCount: lists.hidden.count)
                        // 订阅价值紧挨 hero（cost note 下面、马赛克上面）。始终按各 agent 自己的账期，不跟当前范围走。
                        if !(report.subscriptions ?? [:]).isEmpty {
                            SubscriptionValueCard(report: report, onSetRenewalDay: onSetRenewalDay)
                        }
                        if lists.visible.contains(where: { $0.cost > 0 }) {
                            MosaicView(projects: lists.visible, currency: cur) { onSelect(.project($0)) }
                                .padding(.horizontal, Metrics.listInset - Metrics.flatPagePadding)
                        }
                    }
                    projectsSection(visible: lists.visible, hidden: lists.hidden, idle: lists.idle, isAll: ctx.isAll)
                    bucketsSection(f)
                    VStack(alignment: .leading, spacing: 8) {
                        // 对账只在 All 下有意义（契约 6.1）。
                        if ctx.isAll { ReconciliationView(report: report) }
                        Text("Generated \(Fmt.timestamp(report.generatedAt)) · schema v\(report.schemaVersion)")
                            .font(.system(size: 10)).foregroundStyle(.tertiary)
                    }
                    .padding(.horizontal, Metrics.listInset)
                    .id(Self.bottomAnchor)
                }
                .padding(.horizontal, Metrics.flatPagePadding)
                .padding(.top, 16).padding(.bottom, 10)
            }
            .task(id: scrollAnchor) {
                guard let a = scrollAnchor else { return }
                try? await Task.sleep(nanoseconds: 300_000_000)
                proxy.scrollTo(a, anchor: .bottom)
            }
        }
    }

    // 唯一的 hero：总金额（All 下是报告总额，对账也按它；其他范围是范围内各项之和）。
    // 「Total cost」右侧是范围分段控件。下面一行小字汇总日期范围和三个计数；非 All 时再加一行范围说明；
    // 最后是 cost_note（任何范围都显示）。
    private func hero(_ ctx: RangeContext, _ f: FilteredReport, visible: [Project], hiddenCount: Int) -> some View {
        let t = report.totals
        let failed = report.buckets.parseFailed.sessions
        let projects = Self.count(visible.count, "project") + (hiddenCount > 0 ? " (\(hiddenCount) hidden)" : "")
        let range = f.firstActive == nil && !ctx.isAll
            ? "No usage" : ShortDate.range(f.firstActive, f.lastActive, compact: true)
        let counts = [projects, Self.count(f.sessions, "session"),
                      "\(Fmt.tokens(f.tokens)) tokens"].joined(separator: " · ")
        var help = [f.firstActive == nil ? "No usage in this range." : "\(ShortDate.range(f.firstActive, f.lastActive)).",
                    ctx.isAll ? "\(Fmt.tokens(t.tokens.cacheRead)) of the tokens are cache reads."
                              : "Cost and tokens summed from daily data; sessions counted by start time."]
        if hiddenCount > 0 {
            help.insert("\(report.projects.count) projects in the report; \(hiddenCount) hidden from the list and mosaic.", at: 1)
        }
        if failed > 0 {
            help.append("Plus \(failed) log file\(failed == 1 ? "" : "s") that failed to parse (not counted in sessions).")
        }
        return VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .center, spacing: 8) {
                Text("Total cost").font(.system(size: 11)).foregroundStyle(.secondary)
                Spacer(minLength: 4)
                RangePicker(raw: $rangeRaw, effective: ctx.range, resetAvailable: ctx.resetAvailable,
                            cycleAvailable: ctx.cycleAvailable)
            }
            HeroAmount(value: Fmt.money(f.cost, currency: cur))
            // 一行放下就一行（先 11pt，再 10.5pt）；还放不下就在日期后面换行，不在词中间折。
            ViewThatFits(in: .horizontal) {
                Text("\(range) · \(counts)").font(.system(size: 11)).fixedSize()
                Text("\(range) · \(counts)").font(.system(size: 10.5)).fixedSize()
                VStack(alignment: .leading, spacing: 1) {
                    Text(range)
                    Text(counts)
                }
                .font(.system(size: 11))
            }
            .foregroundStyle(.secondary).monospacedDigit()
            .help(help.joined(separator: "\n"))
            if let caption = ctx.caption {
                RangeCaption(text: caption).padding(.top, 1)
            }
            CostNote(text: report.costNote).padding(.top, 4)
        }
        .padding(.horizontal, Metrics.listInset)
    }

    private static func count(_ n: Int, _ noun: String) -> String {
        "\(n) \(noun)\(n == 1 ? "" : "s")"
    }

    private func projectsSection(visible: [Project], hidden: [Project], idle: Int, isAll: Bool) -> some View {
        let pinned = ProjectPrefs.parse(pinnedRaw)
        let end = report.heatEndDate
        let labels = report.agentLabels
        return PanelSection("Projects", flat: true) {
            Legend(agents: agents)
        } content: {
            if visible.isEmpty {
                Text(report.projects.isEmpty ? "No projects."
                     : idle > 0 ? "No project usage in this range." : "All projects are hidden.")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .padding(.horizontal, Metrics.listInset).padding(.vertical, 8)
            }
            ForEach(Array(visible.enumerated()), id: \.element.id) { i, p in
                if i > 0 { RowDivider(inset: Metrics.listInset, trailing: Metrics.listInset) }
                ProjectRow(project: p, currency: cur,
                           weeks: p.heatWeeks(endingOn: end), agentLabels: labels,
                           pinned: pinned.contains(p.id),
                           onOpen: { onSelect(.project(p.id)) },
                           onTogglePin: { pinnedRaw = ProjectPrefs.toggle(p.id, in: pinnedRaw) },
                           onHide: { hide(p.id) })
            }
            if !hidden.isEmpty {
                if !visible.isEmpty { RowDivider(inset: Metrics.listInset, trailing: Metrics.listInset) }
                hiddenFooter(hidden)
            }
            if !isAll && idle > 0 {
                Text("\(Self.count(idle, "project")) with no usage in this range")
                    .font(.system(size: 10.5)).foregroundStyle(.tertiary)
                    .padding(.horizontal, Metrics.listInset).padding(.vertical, 6)
            }
        }
    }

    private func hide(_ id: String) {
        withAnimation(.easeOut(duration: 0.2)) {
            hiddenRaw = ProjectPrefs.serialize(ProjectPrefs.parse(hiddenRaw).union([id]))
        }
    }

    private func unhide(_ id: String) {
        withAnimation(.easeOut(duration: 0.2)) {
            var s = ProjectPrefs.parse(hiddenRaw)
            s.remove(id)
            hiddenRaw = ProjectPrefs.serialize(s)
        }
    }

    /// 「N hidden · $X · Show」；展开后在下面列出隐藏的项目（次要色），每行可取消隐藏。
    @ViewBuilder private func hiddenFooter(_ hidden: [Project]) -> some View {
        let cost = hidden.reduce(0) { $0 + $1.cost }
        HStack(spacing: 4) {
            Image(systemName: "eye.slash").font(.system(size: 9))
            Text("\(hidden.count) hidden · \(Fmt.money(cost, currency: cur)) ·").monospacedDigit()
            Button(showHidden ? "Hide" : "Show") {
                withAnimation(.easeOut(duration: 0.15)) { showHidden.toggle() }
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color.accentColor)
            Spacer(minLength: 0)
        }
        .font(.system(size: 10.5))
        .foregroundStyle(.secondary)
        .padding(.horizontal, Metrics.listInset).padding(.vertical, 8)

        if showHidden {
            VStack(spacing: 0) {
                ForEach(Array(hidden.enumerated()), id: \.element.id) { i, p in
                    if i > 0 { RowDivider(inset: Metrics.listInset, trailing: Metrics.listInset) }
                    HiddenProjectRow(project: p, currency: cur,
                                     onOpen: { onSelect(.project(p.id)) },
                                     onUnhide: { unhide(p.id) })
                }
            }
        }
    }

    private func bucketsSection(_ f: FilteredReport) -> some View {
        let b = report.buckets
        let u = f.unattributed, e = f.excluded
        return PanelSection("Not in any project", flat: true) {
            BucketRow(name: "Unattributed",
                      desc: "No file signal, and no cwd or scratchpad that maps to a project",
                      sessions: u.sessions,
                      value: Fmt.money(u.cost, currency: cur),
                      action: u.sessionsDetail.isEmpty ? nil : { onSelect(.bucket(.unattributed)) })
            RowDivider(inset: Metrics.listInset, trailing: Metrics.listInset)
            BucketRow(name: "Excluded",
                      desc: "Matched an exclude path in your config",
                      sessions: e.sessions,
                      value: Fmt.money(e.cost, currency: cur),
                      action: e.sessionsDetail.isEmpty ? nil : { onSelect(.bucket(.excluded)) })
            RowDivider(inset: Metrics.listInset, trailing: Metrics.listInset)
            ParseFailedRow(bucket: b.parseFailed)
        }
    }
}

/// 项目行，两行文字：
/// 第一行 名字 + agent 色点（1–3 个，按该项目用过的 agent）+ local / path missing 标签，右侧金额；
/// 第二行 sessions · tokens · 最近活跃，右侧 8 周热力条（每格按那周各 agent 份额分色带）。
/// 悬停时第二行热力条左边出现置顶 / 隐藏两个小按钮；右键菜单有更多动作。
/// 订阅价值：每个有订阅的 agent 一行。左边是月费，右边是本账期 API 等价用量和倍数。
/// 没有新的卡片描边，和总览其他节一样直接放在面板上。底部那句说明固定显示。
private struct SubscriptionValueCard: View {
    let report: UsageReport
    let onSetRenewalDay: (String) -> Void
    @AppStorage("renewalNudgeDismissed") private var dismissedRaw = ""

    private var cur: String { report.currency }

    var body: some View {
        let rows = SubscriptionValue.rows(of: report)
        return PanelSection("Subscription value", flat: true) {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(rows.enumerated()), id: \.element.id) { i, row in
                    if i > 0 { RowDivider(inset: Metrics.listInset, trailing: Metrics.listInset) }
                    line(row)
                }
                Text(subscriptionValueExplanation)
                    .font(.system(size: 10.5))
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, Metrics.listInset)
                    .padding(.top, 3)
                    .padding(.bottom, 6)
                renewalNudge
            }
        }
    }

    @ViewBuilder private var renewalNudge: some View {
        let subs = report.subscriptions ?? [:]
        let dismissed = RenewalNudge.parseDismissed(dismissedRaw)
        let pending = RenewalNudge.pendingAgents(subscriptions: subs, dismissed: dismissed)
        if let agent = pending.first {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Button { onSetRenewalDay(agent) } label: {
                    (Text("Renewal days not set for \(pending.map { subs[$0]?.planLabel ?? $0 }.joined(separator: ", ")) · ")
                        .foregroundColor(.secondary)
                     + Text("Set now").foregroundColor(.accentColor))
                        .fixedSize(horizontal: false, vertical: true)
                        .multilineTextAlignment(.leading)
                        .contentShape(Rectangle())
                }
                Spacer(minLength: 0)
                Button("×") {
                    dismissedRaw = RenewalNudge.serializeDismissed(dismissed.union(pending))
                }
                .foregroundStyle(.secondary)
                .help("Dismiss renewal day reminder")
                .accessibilityLabel("Dismiss renewal day reminder")
            }
            .buttonStyle(.plain)
            .font(.system(size: 10.5))
            .padding(.horizontal, Metrics.listInset)
            .padding(.bottom, 6)
        }
    }

    private func line(_ row: SubscriptionRow) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                AgentDot(agent: row.agent, size: 6)
                    .alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
                Text(row.planLabel)
                    .font(.system(size: 12))
                    .lineLimit(1)
                    .layoutPriority(-1)
                Text("· \(Fmt.perMonth(row.monthlyPriceUsd, currency: cur))")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                if row.extraUsageEnabled {
                    Badge(text: "extra usage on", style: .warn,
                          help: "Extra usage is enabled, so overage is billed on top of the flat fee.")
                        .fixedSize()
                }
                Spacer(minLength: 8)
                Text(Fmt.money(row.usage, currency: cur))
                    .font(.system(size: 12, weight: .medium, design: .rounded))
                    .lineLimit(1)
                    .layoutPriority(1)
                Text("·")
                    .font(.system(size: 11))
                    .foregroundStyle(.tertiary)
                Text(Fmt.multiple(row.multiplier))
                    .font(.system(size: 11.5, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .layoutPriority(1)
                    .frame(minWidth: 42, alignment: .trailing)
            }
            .help(help(row))
            if let sub = report.subscriptions?[row.agent] {
                Group {
                    if SubscriptionValue.needsRenewalDay(sub) {
                        Button { onSetRenewalDay(row.agent) } label: {
                            Text(Fmt.cycleCaption(sub, timezone: RangeEngine.timezone(of: report)))
                                .multilineTextAlignment(.leading)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .help(SubscriptionValue.assumedDayHelp)
                    } else {
                        Text(Fmt.cycleCaption(sub, timezone: RangeEngine.timezone(of: report)))
                            .help(Fmt.cycleDates(sub, timezone: RangeEngine.timezone(of: report)))
                    }
                }
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.leading, 11)
            }
        }
        .monospacedDigit()
        .padding(.horizontal, Metrics.listInset)
        .padding(.vertical, 6)
    }

    private func help(_ row: SubscriptionRow) -> String {
        let price = Fmt.perMonth(row.monthlyPriceUsd, currency: cur)
        let usage = Fmt.money(row.usage, currency: cur)
        if let m = row.multiplier {
            return "\(row.planLabel) is \(price) flat. \(usage) is the API-equivalent cost this billing cycle, \(Fmt.multiple(m)) the flat fee. Not an extra charge."
        }
        return "\(row.planLabel): monthly price unknown. \(usage) is the API-equivalent cost this billing cycle. Not an extra charge."
    }
}

struct ProjectRow: View {
    let project: Project
    let currency: String
    let weeks: [WeekCost]
    let agentLabels: [String: String]
    let pinned: Bool
    let onOpen: () -> Void
    let onTogglePin: () -> Void
    let onHide: () -> Void
    @State private var hover = false

    private static let padV: CGFloat = 7

    var body: some View {
        let strip = HeatStripView(weeks: weeks, agentLabels: agentLabels, currency: currency)
        ZStack(alignment: .bottomTrailing) {
            Button(action: onOpen) {
                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .center, spacing: 6) {
                        if pinned {
                            Image(systemName: "pin.fill")
                                .font(.system(size: 8.5, weight: .semibold))
                                .foregroundStyle(AgentPalette.pin)
                                .help("Pinned")
                        }
                        Text(project.name).font(.system(size: 12.5, weight: .medium)).lineLimit(1)
                        AgentDots(agents: project.byAgent)
                        if project.pathMissing {
                            Badge(text: "path missing", style: .warn,
                                  help: "None of this project's local paths exist any more.")
                        }
                        if project.remote == nil {
                            Badge(text: "local", help: "No git remote; identified by its absolute path.")
                        }
                        Spacer(minLength: 8)
                        Text(Fmt.money(project.cost, currency: currency))
                            .font(.system(size: 12.5, weight: .medium, design: .rounded).monospacedDigit())
                            .lineLimit(1)
                    }
                    HStack(alignment: .center, spacing: 8) {
                        Text("\(project.sessions) session\(project.sessions == 1 ? "" : "s") · \(Fmt.tokens(project.tokens.total)) tokens · active \(ShortDate.relative(project.lastActive))")
                            .font(.system(size: 10.5))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .help("Last active \(Fmt.day(project.lastActive))")
                        Spacer(minLength: 8)
                        strip
                    }
                }
                .padding(.horizontal, Metrics.listInset).padding(.vertical, Self.padV)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowButtonStyle(highlighted: hover, cornerRadius: Metrics.rowRadius))
            .help(project.id)

            HStack(spacing: 0) {
                RowIconButton(systemName: pinned ? "pin.fill" : "pin",
                              tint: pinned ? AgentPalette.pin : nil,
                              help: pinned ? "Unpin" : "Pin to top", action: onTogglePin)
                RowIconButton(systemName: "eye.slash", help: "Hide from list and mosaic", action: onHide)
            }
            .padding(.trailing, Metrics.listInset + strip.width + 6)
            .padding(.bottom, Self.padV - 1)
            .opacity(hover ? 1 : 0)
            .allowsHitTesting(hover)
        }
        .onHover { hover = $0 }
        .contextMenu {
            ProjectContextMenu(project: project, pinned: pinned, hidden: false,
                               onTogglePin: onTogglePin, onToggleHidden: onHide)
        }
    }
}

/// 隐藏列表里的一行：次要色，右侧一个 eye 按钮取消隐藏。
struct HiddenProjectRow: View {
    let project: Project
    let currency: String
    let onOpen: () -> Void
    let onUnhide: () -> Void

    var body: some View {
        HStack(spacing: 6) {
            Button(action: onOpen) {
                HStack(spacing: 6) {
                    Text(project.name).font(.system(size: 11.5)).lineLimit(1)
                    Spacer(minLength: 6)
                    Text(Fmt.money(project.cost, currency: currency))
                        .font(.system(size: 11.5, design: .rounded).monospacedDigit())
                }
                .foregroundStyle(.secondary)
                .padding(.vertical, 5)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(project.id)
            RowIconButton(systemName: "eye", help: "Unhide", action: onUnhide)
        }
        .padding(.leading, Metrics.listInset).padding(.trailing, Metrics.listInset - 4)
        .contextMenu {
            ProjectContextMenu(project: project, pinned: false, hidden: true,
                               onTogglePin: {}, onToggleHidden: onUnhide)
        }
    }
}

struct BucketRow: View {
    let name: String
    let desc: String
    let sessions: Int
    let value: String
    let action: (() -> Void)?

    var body: some View {
        let row = VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(name).font(.system(size: 12))
                Spacer(minLength: 6)
                Text("\(sessions) session\(sessions == 1 ? "" : "s")")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                Text(value).font(.system(size: 12, weight: .medium, design: .rounded)).monospacedDigit()
                    .frame(minWidth: 52, alignment: .trailing)
            }
            Text(desc).font(.system(size: 10)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, Metrics.listInset).padding(.vertical, 7)
        .contentShape(Rectangle())

        if let action {
            Button(action: action) { row }.buttonStyle(RowButtonStyle(cornerRadius: Metrics.rowRadius)).help("Show these sessions")
        } else {
            row
        }
    }
}

struct ParseFailedRow: View {
    let bucket: ParseFailedBucket
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeOut(duration: 0.15)) { expanded.toggle() }
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        HStack(spacing: 4) {
                            Text("Parse failed").font(.system(size: 12))
                            if !bucket.files.isEmpty {
                                Image(systemName: expanded ? "chevron.down" : "chevron.right")
                                    .font(.system(size: 8, weight: .semibold))
                                    .foregroundStyle(.tertiary)
                            }
                        }
                        Spacer(minLength: 6)
                        Text("\(bucket.sessions) session\(bucket.sessions == 1 ? "" : "s")")
                            .font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                        Text("—").font(.system(size: 12, weight: .medium))
                            .foregroundStyle(.secondary)
                            .frame(minWidth: 52, alignment: .trailing)
                            .help("Cost of unparseable logs cannot be computed.")
                    }
                    Text("Log files kanjo could not read; cost unknown")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                .padding(.horizontal, Metrics.listInset).padding(.vertical, 7)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowButtonStyle(cornerRadius: Metrics.rowRadius))
            .disabled(bucket.files.isEmpty)

            if expanded {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(bucket.files, id: \.self) { f in
                        Text(f).font(.system(size: 9.5, design: .monospaced)).foregroundStyle(.secondary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.horizontal, Metrics.listInset).padding(.bottom, 8)
            }
        }
    }
}

/// 对账：正常时一行绿色小字（明细在 tooltip）；对不上时变成醒目的红色块，逐项列出差异。
struct ReconciliationView: View {
    let report: UsageReport

    var body: some View {
        let rec = Reconciliation(report: report)
        let cur = report.currency
        let lines = [
            (rec.cost.ok, "Total \(Fmt.money(rec.cost.reported, currency: cur)) vs projects \(Fmt.money(rec.projectsCost, currency: cur)) + unattributed \(Fmt.money(rec.unattributedCost, currency: cur)) + excluded \(Fmt.money(rec.excludedCost, currency: cur)) = \(Fmt.money(rec.cost.summed, currency: cur))" + (rec.cost.ok ? "" : " · diff \(signedMoney(rec.cost.diff, cur))")),
            (rec.tokens.ok, "Tokens \(Fmt.tokens(Int(rec.tokens.reported))) vs sum \(Fmt.tokens(Int(rec.tokens.summed)))" + (rec.tokens.ok ? "" : " · diff \(Int(rec.tokens.diff))")),
            (rec.sessions.ok, "Sessions \(Int(rec.sessions.reported)) vs sum \(Int(rec.sessions.summed))" + (rec.sessions.ok ? "" : " · diff \(Int(rec.sessions.diff))")),
        ]
        let contract = "Invariant from the data contract: totals = sum(projects) + unattributed + excluded (cost tolerance $0.01)."

        if rec.ok {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Image(systemName: "checkmark.circle.fill")
                Text("Reconciled: \(Fmt.money(rec.cost.reported, currency: cur)) = projects + unattributed + excluded")
                    .fixedSize(horizontal: false, vertical: true)
            }
            .font(.system(size: 10.5))
            .foregroundStyle(AgentPalette.good)
            .monospacedDigit()
            .help(lines.map(\.1).joined(separator: "\n") + "\n\n" + contract)
        } else {
            StatusBlock(kind: .bad, icon: "exclamationmark.triangle.fill") {
                Text("Totals do not reconcile").font(.system(size: 12, weight: .semibold))
                ForEach(Array(lines.enumerated()), id: \.offset) { _, l in
                    Text(l.1)
                        .font(.system(size: 10.5, weight: l.0 ? .regular : .semibold))
                        .foregroundStyle(l.0 ? Color.secondary : AgentPalette.bad)
                        .monospacedDigit()
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .help(contract)
        }
    }

    private func signedMoney(_ v: Double, _ cur: String) -> String {
        (v > 0 ? "+" : "") + Fmt.money(v, currency: cur)
    }
}
