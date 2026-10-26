import SwiftUI
import KanjoCore

/// 清理时传给 `disk clean --older-than` 的档位。Any 不带这个参数。
enum DiskAge: String, CaseIterable, Identifiable {
    case any
    case d7 = "7d"
    case d30 = "30d"
    case d90 = "90d"

    var id: String { rawValue }
    var label: String {
        switch self {
        case .any: return L10n.tr("disk.age.any")
        case .d7: return L10n.tr("disk.age.7d")
        case .d30: return L10n.tr("disk.age.30d")
        case .d90: return L10n.tr("disk.age.90d")
        }
    }
    var argument: String? { self == .any ? nil : rawValue }
    var caption: String { self == .any ? L10n.tr("disk.age.caption.any") : L10n.tr("disk.age.caption.older", label) }
}

struct DiskView: View {
    /// `--route disk:expanded` 用：截图时展开每个 agent。
    static let expandedAnchor = "expanded"

    var expandAll = false
    let onBack: () -> Void
    var onSettings: () -> Void = {}

    @AppStorage(SettingsKeys.appLanguage, store: AppDefaults.store) private var appLanguage = AppLanguage.system.rawValue
    @EnvironmentObject private var disk: DiskStore
    @State private var expanded: Set<String> = []
    @State private var selected: Set<String> = []
    @State private var age: DiskAge = .any
    @State private var checking = false
    @State private var applying = false
    @State private var pending: CleanResult?
    @State private var finished: CleanResult?
    @State private var actionError: String?

    var body: some View {
        ZStack {
            page
            if pending != nil || finished != nil {
                Color.black.opacity(0.28)
                card
                    .padding(12)
            }
        }
        .onAppear {
            if !disk.hasReport && disk.error == nil && !disk.isLoading { disk.refresh() }
            applyExpanded()
        }
        .onChange(of: disk.report?.generatedAt) { _ in
            let ok = Set(disk.report?.allEntries.filter(\.isReclaimable).map(\.id) ?? [])
            selected.formIntersection(ok)
            applyExpanded()
        }
    }

    private func applyExpanded() {
        guard expandAll, let r = disk.report else { return }
        expanded = Set(r.agents.map(\.agent))
    }

    @ViewBuilder private var page: some View {
        VStack(spacing: 0) {
            if let r = disk.report {
                loaded(r)
            } else if let err = disk.error {
                failure(err)
            } else {
                VStack(spacing: 8) {
                    back
                    Spacer()
                    ProgressView().controlSize(.small)
                    Text(L10n.tr("disk.loading")).font(.system(size: 11)).foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(.horizontal, Metrics.pagePadding)
                .padding(.top, 12)
            }
        }
    }

    private var back: some View {
        BackButton(title: L10n.tr("disk.navigation.overview"), action: onBack)
            .padding(.leading, Metrics.rowInset - 4)
    }

    private func loaded(_ report: DiskReport) -> some View {
        let agents = report.agents.sorted { $0.bytes > $1.bytes }
        let maxBytes = agents.map(\.bytes).max() ?? 0
        return VStack(spacing: 0) {
            if report.isNewerSchema || (disk.error != nil) {
                VStack(spacing: 6) {
                    if report.isNewerSchema {
                        StatusBlock(kind: .warn, icon: "exclamationmark.triangle.fill") {
                            Text(L10n.tr("disk.schema_warning", report.schemaVersion, supportedSchemaVersion))
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    if let err = disk.error {
                        StatusBlock(kind: .bad, icon: "xmark.octagon.fill") {
                            Text(L10n.tr("menu.refresh_failed_banner")).fontWeight(.semibold)
                            Text(err).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                        }
                    }
                }
                .padding(.horizontal, Metrics.pagePadding).padding(.top, 10)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: Metrics.sectionSpacing) {
                    back
                    hero(report).padding(.horizontal, Metrics.rowInset)
                    agePicker.padding(.horizontal, Metrics.rowInset)
                    PanelSection(L10n.tr("disk.by_agent"), inset: true) {
                        if agents.isEmpty {
                            Text(L10n.tr("disk.no_disk_usage")).font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                        VStack(alignment: .leading, spacing: 12) {
                            ForEach(agents) { agent in
                                agentBlock(agent, maxBytes: maxBytes)
                            }
                        }
                    }
                    if let banner = actionError, pending == nil {
                        StatusBlock(kind: .bad, icon: "xmark.octagon.fill") {
                            Text(banner).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                        }
                        .padding(.horizontal, Metrics.rowInset)
                    }
                    Text(L10n.tr("overview.generated_footer", Fmt.timestamp(report.generatedAt), report.schemaVersion))
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                        .padding(.horizontal, Metrics.rowInset)
                        .help(disk.sourceDescription)
                }
                .padding(.horizontal, Metrics.pagePadding)
                .padding(.top, 12).padding(.bottom, 10)
            }
            if !selected.isEmpty {
                cleanBar(report)
            }
        }
    }

    private func hero(_ report: DiskReport) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(L10n.tr("disk.total")).font(.system(size: 11)).foregroundStyle(.secondary)
                    HeroAmount(value: Fmt.bytes(report.totalBytes), size: 28)
                }
                .accessibilityElement(children: .combine)
                Spacer(minLength: 8)
                VStack(alignment: .trailing, spacing: 1) {
                    Text(L10n.tr("disk.reclaimable")).font(.system(size: 11)).foregroundStyle(.secondary)
                    HeroAmount(value: Fmt.bytes(report.reclaimableBytes), size: 28, color: .accentColor)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel(L10n.tr("disk.reclaimable") + " " + Fmt.bytes(report.reclaimableBytes))
            }
            TimelineView(.periodic(from: .now, by: 60)) { context in
                HStack(spacing: 4) {
                    Text(DiskScanCaption.text(for: report, now: context.date))
                    if disk.isRescanning {
                        Text(L10n.tr("disk.rescanning"))
                        ProgressView().controlSize(.mini)
                    }
                }
                .font(.system(size: 10.5))
                .foregroundStyle(.secondary)
            }
            CostNote(text: L10n.tr("disk.ledger_note"))
        }
    }

    private var agePicker: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(L10n.tr("disk.older_than")).font(.system(size: 11)).foregroundStyle(.secondary)
            Picker(L10n.tr("disk.older_than"), selection: $age) {
                ForEach(DiskAge.allCases) { Text($0.label).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .controlSize(.small)
            .disabled(checking || applying || pending != nil)
            .help(L10n.tr("disk.age_help"))
        }
    }

    private func agentBlock(_ agent: DiskAgent, maxBytes: Int) -> some View {
        let open = expanded.contains(agent.agent)
        let fraction = maxBytes > 0 ? Double(agent.bytes) / Double(maxBytes) : 0
        return VStack(alignment: .leading, spacing: 6) {
            Button {
                if open { expanded.remove(agent.agent) } else { expanded.insert(agent.agent) }
            } label: {
                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Circle().fill(AgentPalette.color(for: agent.agent))
                            .frame(width: 6, height: 6)
                            .alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
                        Text(agent.label).font(.system(size: 12))
                        Text("·").font(.system(size: 12)).foregroundStyle(.tertiary)
                        Text(Fmt.bytes(agent.bytes))
                            .font(.system(size: 12, weight: .medium, design: .rounded))
                            .monospacedDigit()
                        Spacer(minLength: 6)
                        Image(systemName: open ? "chevron.down" : "chevron.right")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(.tertiary)
                    }
                    GeometryReader { geo in
                        Capsule().fill(AgentPalette.color(for: agent.agent))
                            .frame(width: max(geo.size.width * CGFloat(min(max(fraction, 0), 1)), 3))
                    }
                    .frame(height: 3)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(open ? L10n.tr("disk.hide_agent_entries", agent.label) : L10n.tr("disk.show_agent_entries", agent.label))
            if open {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(agent.entries.enumerated()), id: \.element.id) { i, entry in
                        entryRow(entry)
                        if i < agent.entries.count - 1 { RowDivider(inset: 0) }
                    }
                }
                .padding(.top, 2)
            }
        }
    }

    private func entryRow(_ entry: DiskEntry) -> some View {
        let fileKey = entry.files == 1 ? "disk.file.singular" : "disk.file.plural"
        let files = L10n.tr(fileKey, entry.files)
        // 每行都留出复选框的位置，这样 Kept / Blocked 的徽章和路径跟可清理行对齐。
        let slot: CGFloat = 16
        return VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .center, spacing: 6) {
                ZStack {
                    if entry.isReclaimable {
                        Toggle(isOn: binding(entry.id)) {
                            Text(L10n.tr("disk.clean_path", entry.path))
                        }
                        .toggleStyle(.checkbox)
                        .labelsHidden()
                        .controlSize(.small)
                        .disabled(checking || applying || pending != nil)
                    }
                }
                .frame(width: slot, height: slot)
                Badge(text: entry.kind.rawValue)
                Spacer(minLength: 4)
                statePill(entry)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.path)
                    .font(.system(size: 10.5, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
                    .help(entry.path)
                Text("\(Fmt.bytes(entry.bytes)) · \(files) · \(ShortDate.day(entry.newest))")
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .help(entry.note ?? "")
            }
            .padding(.leading, slot + 6)
        }
        .padding(.vertical, 6)
    }

    private func binding(_ id: String) -> Binding<Bool> {
        Binding(get: { selected.contains(id) }, set: { on in
            if on { selected.insert(id) } else { selected.remove(id) }
        })
    }

    @ViewBuilder private func statePill(_ entry: DiskEntry) -> some View {
        if entry.deletable == .never {
            Badge(text: L10n.tr("disk.badge.kept"), help: L10n.tr("disk.badge.kept_help"))
        } else if entry.blocked.isEmpty {
            Badge(text: L10n.tr("disk.badge.reclaimable"), style: .good,
                  help: L10n.tr("disk.badge.reclaimable_help"))
        } else {
            VStack(alignment: .trailing, spacing: 2) {
                ForEach(Array(entry.blocked.enumerated()), id: \.offset) { _, reason in
                    Badge(text: DiskBlock.title(reason), style: .warn, help: DiskBlock.explanation(reason))
                }
            }
        }
    }

    private func cleanBar(_ report: DiskReport) -> some View {
        let entries = report.allEntries.filter { selected.contains($0.id) }
        let bytes = entries.reduce(0) { $0 + $1.bytes }
        let n = entries.count
        let titleKey = n == 1 ? "disk.clean_button.singular" : "disk.clean_button.plural"
        let title = checking
            ? L10n.tr("disk.checking")
            : L10n.tr(titleKey, n, Fmt.bytes(bytes))
        return VStack(spacing: 0) {
            Divider().opacity(0.6)
            Button(action: dryRun) {
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(checking || applying)
            .help(L10n.tr("disk.clean_help"))
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
    }

    @ViewBuilder private var card: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let result = finished {
                Text(L10n.tr("disk.card.moved_title")).font(.system(size: 14, weight: .semibold))
                Text(L10n.tr("disk.card.freed", Fmt.bytes(result.freedBytes)))
                    .font(.system(size: 20, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(Color.accentColor)
                skippedList(result)
                Button(L10n.tr("common.done")) { finished = nil; actionError = nil }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
            } else if let result = pending {
                Text(L10n.tr("disk.card.confirm_title")).font(.system(size: 14, weight: .semibold))
                Text(age.caption).font(.system(size: 10.5)).foregroundStyle(.secondary)
                ScrollView {
                    planBody(result)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: 320)
                Text(L10n.tr("disk.card.warning"))
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let actionError {
                    Text(actionError)
                        .font(.system(size: 10.5, design: .monospaced))
                        .foregroundStyle(AgentPalette.bad)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack {
                    Button(L10n.tr("common.cancel")) { pending = nil; actionError = nil }
                        .buttonStyle(.bordered)
                        .keyboardShortcut(.cancelAction)
                        .disabled(applying)
                    Spacer()
                    Button(action: move) {
                        if applying {
                            ProgressView().controlSize(.small).frame(width: 88)
                        } else {
                            Text(L10n.tr("disk.card.move_button"))
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(AgentPalette.bad)
                    .disabled(applying || result.moved.isEmpty)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(.regularMaterial))
    }

    @ViewBuilder private func planBody(_ result: CleanResult) -> some View {
        let groups = CleanPlan.groups(report: disk.report ?? .empty, moved: result.moved)
        if result.moved.isEmpty {
            Text(L10n.tr("disk.card.nothing_moved")).font(.system(size: 12)).foregroundStyle(.secondary)
        }
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(groups.enumerated()), id: \.offset) { _, g in
                VStack(alignment: .leading, spacing: 2) {
                    Text(g.title).font(.system(size: 12, weight: .medium))
                    ForEach(g.paths, id: \.self) { path in
                        Text(path)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                            .textSelection(.enabled)
                            .help(path)
                    }
                    Text(CleanPlan.countAndSize(count: g.paths.count, bytes: g.bytes))
                        .font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                }
            }
            Text(L10n.tr("disk.card.total", CleanPlan.countAndSize(count: result.moved.count, bytes: result.freedBytes)))
                .font(.system(size: 11, weight: .medium)).monospacedDigit()
        }
        skippedList(result)
    }

    @ViewBuilder private func skippedList(_ result: CleanResult) -> some View {
        if !result.skipped.isEmpty {
            VStack(alignment: .leading, spacing: 3) {
                Text(L10n.tr("disk.card.skipped")).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
                ForEach(Array(result.skipped.enumerated()), id: \.offset) { _, skip in
                    VStack(alignment: .leading, spacing: 1) {
                        Text("\(skip.id) — \(DiskBlock.short(skip.reason))")
                            .font(.system(size: 11)).foregroundStyle(AgentPalette.warnInk)
                        Text(DiskBlock.explanation(skip.reason))
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    private func failure(_ message: String) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                back
                Label(L10n.tr("disk.error_title"), systemImage: "xmark.octagon.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(AgentPalette.bad)
                Text(message)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.primary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(AgentPalette.badFill))
                Text(L10n.tr("settings.current_source", disk.sourceDescription))
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Button(L10n.tr("common.retry")) { disk.refresh(rescan: true) }.buttonStyle(.borderedProminent)
                    Button(L10n.tr("menu.open_settings"), action: onSettings).buttonStyle(.bordered)
                }
                Text(L10n.tr("disk.expected_json"))
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(Metrics.pagePadding)
            .padding(.top, 12)
        }
    }

    private func dryRun() {
        guard !checking, !applying else { return }
        let ids = selected.sorted()
        guard !ids.isEmpty else { return }
        checking = true
        actionError = nil
        let older = age.argument
        Task {
            do {
                pending = try await disk.clean(ids: ids, olderThan: older, confirmed: false)
            } catch {
                actionError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            checking = false
        }
    }

    /// 用户已经看过 dry-run 计划，这一步才带 `--yes`。
    private func move() {
        guard !applying else { return }
        applying = true
        actionError = nil
        let ids = selected.sorted()
        let older = age.argument
        Task {
            do {
                let result = try await disk.clean(ids: ids, olderThan: older, confirmed: true)
                pending = nil
                finished = result
                selected.removeAll()
                disk.refresh(rescan: true)
            } catch {
                actionError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            applying = false
        }
    }
}
