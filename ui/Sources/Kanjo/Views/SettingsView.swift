import AppKit
import SwiftUI
import KanjoCore

struct SettingsView: View {
    static let bottomAnchor = "settings-bottom"

    @EnvironmentObject var store: ReportStore
    var scrollTo: String? = nil     // 支持底部或具体订阅行
    let onBack: () -> Void

    @AppStorage(SettingsKeys.sourceKind) private var sourceKind =
        (DefaultPaths.cliDirectoryExists ? SourceKind.cli : SourceKind.file).rawValue
    @AppStorage(SettingsKeys.filePath) private var filePath = ""
    @AppStorage(SettingsKeys.cliCommand) private var cliCommand = CLIDataSource.defaultCommand
    @AppStorage(SettingsKeys.cliWorkingDirectory) private var cliWorkingDirectory = ""
    @AppStorage(SettingsKeys.refreshMinutes) private var refreshMinutes = 5
    @AppStorage(SettingsKeys.showAmountInMenuBar) private var showAmount = true
    @AppStorage(SettingsKeys.hiddenProjects) private var hiddenRaw = ""

    private let intervals = [0, 1, 5, 15, 30, 60]

    var body: some View {
        ScrollViewReader { proxy in
        ScrollView {
            VStack(alignment: .leading, spacing: Metrics.sectionSpacing) {
                VStack(alignment: .leading, spacing: 8) {
                    BackButton(title: "Done", action: onBack)
                        .padding(.leading, -4)
                    Text("Settings").font(.system(size: 15, weight: .semibold))
                }
                .padding(.horizontal, Metrics.rowInset)

                if let o = store.dataOverride {
                    StatusBlock(kind: .warn, icon: "exclamationmark.triangle.fill") {
                        Text("Launched with --data / KANJO_DATA: \(o.path). This overrides the data source below until the app is restarted without it.")
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                    }
                }

                PanelSection("Data source", inset: true) {
                    Picker("Source", selection: $sourceKind) {
                        ForEach(SourceKind.allCases) { Text($0.label).tag($0.rawValue) }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()

                    if sourceKind == SourceKind.cli.rawValue {
                        note(DefaultPaths.cliDescription(customDirectory: cliWorkingDirectory, customCommand: cliCommand))
                        field("Command", text: $cliCommand, placeholder: CLIDataSource.defaultCommand)
                        HStack(alignment: .bottom) {
                            field("Working directory (cli/ path)", text: $cliWorkingDirectory,
                                  placeholder: DefaultPaths.resolvedCLIDirectory()?.path ?? "Inherit")
                            Button("Choose…") { if let p = chooseFolder() { cliWorkingDirectory = p } }
                        }
                        note("Runs via /bin/zsh -l -c and reads kanjo export JSON from stdout.")
                        Text("Disk · \(derivedDiskCommand)")
                            .font(.system(size: 10.5, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                            .help("Derived from the command above by replacing export with disk --json. Cleanup runs disk clean and moves files to the Trash.")
                    } else {
                        HStack(alignment: .bottom) {
                            field("JSON file", text: $filePath, placeholder: DefaultPaths.sampleFixture.path)
                            Button("Choose…") { if let p = chooseFile() { filePath = p } }
                        }
                        note("Leave empty to use the bundled sample: fixtures/sample.json.")
                    }
                }

                PanelSection("Refresh", inset: true) {
                    Picker("Auto refresh", selection: $refreshMinutes) {
                        ForEach(intervals, id: \.self) { m in
                            Text(m == 0 ? "Off" : "Every \(m) min").tag(m)
                        }
                    }
                    .font(.system(size: 12))
                    Toggle("Show total cost in menu bar", isOn: $showAmount)
                        .font(.system(size: 12))
                }

                PanelSection("Projects", inset: true) {
                    let hidden = ProjectPrefs.parse(hiddenRaw).count
                    HStack {
                        Text("Hidden projects: \(hidden)").font(.system(size: 12)).monospacedDigit()
                        Spacer()
                        Button("Unhide all") { hiddenRaw = "" }
                            .disabled(hidden == 0)
                    }
                    note("Hide or pin a project from its row in the overview (hover or right-click).")
                }

                quotaSection
                subscriptionsSection

                VStack(alignment: .trailing, spacing: 8) {
                    Button("Apply & Refresh") { store.applySettings() }
                        .keyboardShortcut(.defaultAction)
                        .buttonStyle(.borderedProminent)
                    Text("Current source — \(store.sourceDescription)")
                        .font(.system(size: 10.5)).foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.horizontal, Metrics.rowInset)
                .id(Self.bottomAnchor)
            }
            .padding(.horizontal, Metrics.pagePadding)
            .padding(.top, 12).padding(.bottom, 10)
        }
        .task(id: store.report == nil ? nil : scrollTo) {
            guard let a = scrollTo else { return }
            try? await Task.sleep(nanoseconds: 300_000_000)
            proxy.scrollTo(a, anchor: a == Self.bottomAnchor ? .bottom : .top)
        }
        }
        .onChange(of: refreshMinutes) { _ in store.restartTimer() }
        .onChange(of: sourceKind) { _ in store.applySettings() }
    }

    /// 各 agent 的额度重置时间和来源（quota_windows），供总览的「Since reset」范围用。
    private var quotaSection: some View {
        PanelSection("Quota reset", inset: true) {
            if let r = store.report {
                let ctx = RangeContext(report: r, raw: TimeRange.sinceReset.rawValue)
                let quota = r.quotaWindows ?? [:]
                let cal = RangeEngine.calendar(timezone: RangeEngine.timezone(of: r))
                Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                    GridRow {
                        Text("Agent"); Text("Next weekly reset"); Text("Source").gridColumnAlignment(.trailing)
                    }
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
                    ForEach(ctx.agentOrder, id: \.self) { agent in
                        GridRow {
                            HStack(spacing: 5) {
                                AgentDot(agent: agent, size: 6)
                                Text(r.agentLabels[agent] ?? agent).lineLimit(1)
                            }
                            .font(.system(size: 11.5))
                            quotaCell(quota[agent], cal: cal)
                            Text(quota[agent]?.source ?? "none")
                                .font(.system(size: 10.5, design: .monospaced))
                                .foregroundStyle(quota[agent] == nil ? .tertiary : .secondary)
                        }
                    }
                }
            } else {
                note("No data loaded yet.")
            }
            note("Read from the tokei cache (~/.tokei) when available. To set or override a reset time by hand, add it to ~/.config/kanjo/attribution.toml. Agents without reset info are left out of the Since reset range.")
        }
    }

    /// 各 agent 的订阅档位（subscriptions），供总览的 Subscription value 卡和 Billing cycle 范围用。
    private var subscriptionsSection: some View {
        PanelSection("Subscriptions", inset: true) {
            if let r = store.report {
                let ctx = RangeContext(report: r, raw: TimeRange.all.rawValue)
                let subs = r.subscriptions ?? [:]
                VStack(alignment: .leading, spacing: 8) {
                    // ForEach 的标识也用滚动 anchor，确保 ScrollViewReader 能找到嵌套的行。
                    ForEach(ctx.agentOrder.map { (agent: $0, anchor: SubscriptionSettingsRoute.anchor(for: $0)) },
                            id: \.anchor) { item in
                        let agent = item.agent
                        SubscriptionSettingsRow(agent: agent, sub: subs[agent],
                                                label: r.agentLabels[agent] ?? agent, currency: r.currency)
                            .id(item.anchor)
                    }
                }
            } else {
                note("No data loaded yet.")
            }
            note("Apply saves the renewal day through the CLI; Reset restores detection. Agents without a subscription are left out of the Billing cycle range.")
        }
    }

    @ViewBuilder private func quotaCell(_ q: QuotaWindow?, cal: Calendar) -> some View {
        if let q, let reset = ReportDates.parseTimestamp(q.weeklyResetsAt) {
            let start = RangeEngine.windowStart(q, now: Date())
            VStack(alignment: .leading, spacing: 1) {
                Text(Self.stamp(reset, cal)).font(.system(size: 11.5)).monospacedDigit()
                if let start {
                    Text("window since \(Self.stamp(start, cal)) · \(q.weeklyWindowHours)h")
                        .font(.system(size: 10)).foregroundStyle(.secondary).monospacedDigit()
                }
            }
        } else if q != nil {
            Text("unreadable").font(.system(size: 11.5)).foregroundStyle(AgentPalette.warnInk)
        } else {
            Text("No reset info").font(.system(size: 11.5)).foregroundStyle(.tertiary)
        }
    }

    private static func stamp(_ d: Date, _ cal: Calendar) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = cal.timeZone
        f.dateFormat = "EEE MMM d HH:mm"
        return f.string(from: d)
    }

    /// 磁盘页用的命令：导出命令里最后一个 `export` 换成 `disk --json`。
    private var derivedDiskCommand: String {
        let trimmed = cliCommand.trimmingCharacters(in: .whitespaces)
        let base = trimmed.isEmpty ? CLIDataSource.defaultCommand : trimmed
        return DiskCommand.report(from: base)
    }

    private func field(_ label: String, text: Binding<String>, placeholder: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.system(size: 10.5)).foregroundStyle(.secondary)
            TextField(placeholder, text: text)
                .textFieldStyle(.roundedBorder)
                .font(.system(size: 11, design: .monospaced))
                .onSubmit { store.applySettings() }
        }
    }

    private func note(_ s: String) -> some View {
        Text(s).font(.system(size: 10.5)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }

    private func chooseFile() -> String? {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.json]
        p.canChooseDirectories = false
        p.allowsMultipleSelection = false
        NSApp.activate(ignoringOtherApps: true)
        return p.runModal() == .OK ? p.url?.path : nil
    }

    private func chooseFolder() -> String? {
        let p = NSOpenPanel()
        p.canChooseFiles = false
        p.canChooseDirectories = true
        p.allowsMultipleSelection = false
        NSApp.activate(ignoringOtherApps: true)
        return p.runModal() == .OK ? p.url?.path : nil
    }
}

private struct SubscriptionSettingsRow: View {
    @EnvironmentObject var store: ReportStore
    let agent: String
    let sub: Subscription?
    let label: String
    let currency: String
    @State private var day: Int
    @State private var saving = false
    @State private var actionError: String?

    init(agent: String, sub: Subscription?, label: String, currency: String) {
        self.agent = agent
        self.sub = sub
        self.label = label
        self.currency = currency
        _day = State(initialValue: min(28, max(1, sub?.anchorDay ?? 1)))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 5) {
                AgentDot(agent: agent, size: 6)
                Text(label).font(.system(size: 11.5)).lineLimit(1)
                Spacer(minLength: 8)
            }
            if let sub {
                Text("\(sub.planLabel) · \(Fmt.perMonth(sub.monthlyPriceUsd, currency: currency))")
                    .font(.system(size: 10)).foregroundStyle(.secondary)
                    .padding(.leading, 11)
                HStack(spacing: 8) {
                    Stepper("Renews on day \(day)", value: $day, in: 1...28)
                        .font(.system(size: 11)).monospacedDigit()
                        .disabled(!store.canEditSubscriptions || saving || store.isLoading)
                        .help(store.canEditSubscriptions ? "Day of the month (1–28)" : "Editing needs the CLI data source")
                    Button("Apply") { save(day) }
                    Button("Reset") { save(nil) }
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(!store.canEditSubscriptions || saving || store.isLoading)
                .padding(.leading, 11)
                Text(saving ? "Saving…" : SubscriptionValue.anchorSource(sub))
                    .font(.system(size: 10)).foregroundStyle(.secondary)
                    .padding(.leading, 11)
                if let url = SubscriptionValue.billingPage(for: agent) {
                    Button("Open billing page") { NSWorkspace.shared.open(url) }
                        .buttonStyle(.link)
                        .font(.system(size: 11))
                        .padding(.leading, 11)
                    Text("Look for \"renews on\" and enter that day above")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.leading, 11)
                }
            } else {
                Text("No subscription info").font(.system(size: 10)).foregroundStyle(.tertiary)
                    .padding(.leading, 11)
            }
            if let actionError {
                StatusBlock(kind: .bad, icon: "xmark.octagon.fill") {
                    Text(actionError).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                }
            }
        }
        .onChange(of: sub?.anchorDay) { value in
            day = min(28, max(1, value ?? 1))
        }
    }

    private func save(_ value: Int?) {
        saving = true
        actionError = nil
        Task {
            do {
                try await store.setAnchorDay(agent: agent, day: value)
                if value == nil { day = min(28, max(1, sub?.anchorDay ?? 1)) }
            } catch {
                actionError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            saving = false
        }
    }
}
