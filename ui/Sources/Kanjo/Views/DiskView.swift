import SwiftUI
import KanjoCore

/// 清理时传给 `disk clean --older-than` 的档位。Any 不带这个参数。
enum DiskAge: String, CaseIterable, Identifiable {
    case any
    case d7 = "7d"
    case d30 = "30d"
    case d90 = "90d"

    var id: String { rawValue }
    var label: String { self == .any ? "Any" : rawValue }
    var argument: String? { self == .any ? nil : rawValue }
    var caption: String { self == .any ? "Any age" : "Older than \(rawValue)" }
}

struct DiskView: View {
    /// `--route disk:expanded` 用：截图时展开每个 agent。
    static let expandedAnchor = "expanded"

    var expandAll = false
    let onBack: () -> Void
    var onSettings: () -> Void = {}

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
            if disk.report == nil && disk.error == nil && !disk.isLoading { disk.refresh() }
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
                    Text("Loading disk…").font(.system(size: 11)).foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(.horizontal, Metrics.pagePadding)
                .padding(.top, 12)
            }
        }
    }

    private var back: some View {
        BackButton(title: "Overview", action: onBack)
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
                            Text("This disk report uses schema_version \(report.schemaVersion); this app understands version \(supportedSchemaVersion).")
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    if let err = disk.error {
                        StatusBlock(kind: .bad, icon: "xmark.octagon.fill") {
                            Text("Last refresh failed — showing previous data.").fontWeight(.semibold)
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
                    PanelSection("By agent", inset: true) {
                        if agents.isEmpty {
                            Text("No disk usage.").font(.system(size: 11)).foregroundStyle(.secondary)
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
                    Text("Generated \(Fmt.timestamp(report.generatedAt)) · schema v\(report.schemaVersion)")
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
                    Text("Total").font(.system(size: 11)).foregroundStyle(.secondary)
                    HeroAmount(value: Fmt.bytes(report.totalBytes), size: 28)
                }
                .accessibilityElement(children: .combine)
                Spacer(minLength: 8)
                VStack(alignment: .trailing, spacing: 1) {
                    Text("Reclaimable").font(.system(size: 11)).foregroundStyle(.secondary)
                    HeroAmount(value: Fmt.bytes(report.reclaimableBytes), size: 28, color: .accentColor)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Reclaimable \(Fmt.bytes(report.reclaimableBytes))")
            }
            CostNote(text: "Numbers stay in the ledger after cleanup")
        }
    }

    private var agePicker: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Older than").font(.system(size: 11)).foregroundStyle(.secondary)
            Picker("Older than", selection: $age) {
                ForEach(DiskAge.allCases) { Text($0.label).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .controlSize(.small)
            .disabled(checking || applying || pending != nil)
            .help("Passed to kanjo disk clean as --older-than. Any does not filter by age.")
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
            .help(open ? "Hide \(agent.label) entries" : "Show \(agent.label) entries")
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
        let files = entry.files == 1 ? "1 file" : "\(entry.files) files"
        // 每行都留出复选框的位置，这样 Kept / Blocked 的徽章和路径跟可清理行对齐。
        let slot: CGFloat = 16
        return VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .center, spacing: 6) {
                ZStack {
                    if entry.isReclaimable {
                        Toggle(isOn: binding(entry.id)) {
                            Text("Clean \(entry.path)")
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
            Badge(text: "Kept", help: "Kept on disk. Entries marked never, such as memory, are not part of cleanup.")
        } else if entry.blocked.isEmpty {
            Badge(text: "Reclaimable", style: .good,
                  help: "The CLI can move this to the Trash. Numbers stay in the ledger after the files are gone.")
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
        let title = checking
            ? "Checking…"
            : "Clean \(n) \(n == 1 ? "item" : "items") · \(Fmt.bytes(bytes))…"
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
            .help("Runs kanjo disk clean --dry-run, then asks before moving files to the Trash.")
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
    }

    @ViewBuilder private var card: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let result = finished {
                Text("Moved to Trash").font(.system(size: 14, weight: .semibold))
                Text("Freed \(Fmt.bytes(result.freedBytes))")
                    .font(.system(size: 20, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(Color.accentColor)
                skippedList(result)
                Button("Done") { finished = nil; actionError = nil }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
            } else if let result = pending {
                Text("Move to Trash?").font(.system(size: 14, weight: .semibold))
                Text(age.caption).font(.system(size: 10.5)).foregroundStyle(.secondary)
                ScrollView {
                    planBody(result)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: 320)
                Text("Files go to the Trash via kanjo disk clean. Nothing is deleted permanently.")
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
                    Button("Cancel") { pending = nil; actionError = nil }
                        .buttonStyle(.bordered)
                        .keyboardShortcut(.cancelAction)
                        .disabled(applying)
                    Spacer()
                    Button(action: move) {
                        if applying {
                            ProgressView().controlSize(.small).frame(width: 88)
                        } else {
                            Text("Move to Trash")
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
            Text("Nothing will be moved.").font(.system(size: 12)).foregroundStyle(.secondary)
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
            Text("Total \(CleanPlan.countAndSize(count: result.moved.count, bytes: result.freedBytes))")
                .font(.system(size: 11, weight: .medium)).monospacedDigit()
        }
        skippedList(result)
    }

    @ViewBuilder private func skippedList(_ result: CleanResult) -> some View {
        if !result.skipped.isEmpty {
            VStack(alignment: .leading, spacing: 3) {
                Text("Skipped").font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
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
                Label("Could not load disk data", systemImage: "xmark.octagon.fill")
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
                Text("Source — \(disk.sourceDescription)")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Button("Retry") { disk.refresh() }.buttonStyle(.borderedProminent)
                    Button("Open Settings", action: onSettings).buttonStyle(.bordered)
                }
                Text("Expected JSON from `kanjo disk --json` (see CONTRACT.md). The app does not delete files itself.")
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
                disk.refresh()
            } catch {
                actionError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            applying = false
        }
    }
}
