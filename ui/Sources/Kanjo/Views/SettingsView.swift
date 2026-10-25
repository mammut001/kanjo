import AppKit
import SwiftUI
import KanjoCore

struct SettingsView: View {
    static let bottomAnchor = "settings-bottom"

    @EnvironmentObject var store: ReportStore
    var scrollTo: String? = nil     // 开发开关 --route settings-bottom 用
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
        .task(id: scrollTo) {
            guard let a = scrollTo else { return }
            try? await Task.sleep(nanoseconds: 300_000_000)
            proxy.scrollTo(a, anchor: .bottom)
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
                    ForEach(ctx.agentOrder, id: \.self) { agent in
                        subscriptionRow(agent, sub: subs[agent], report: r)
                    }
                }
            } else {
                note("No data loaded yet.")
            }
            note("Overrides live in ~/.config/kanjo/attribution.toml under [subscriptions.<agent>]. Agents without a subscription are left out of the Billing cycle range.")
        }
    }

    private func subscriptionRow(_ agent: String, sub: Subscription?, report: UsageReport) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                AgentDot(agent: agent, size: 6)
                    .alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
                Text(report.agentLabels[agent] ?? agent)
                    .font(.system(size: 11.5))
                    .lineLimit(1)
                Spacer(minLength: 8)
                Text(sub?.source ?? "none")
                    .font(.system(size: 10.5, design: .monospaced))
                    .foregroundStyle(sub == nil ? .tertiary : .secondary)
            }
            Text(subscriptionDetail(sub, currency: report.currency))
                .font(.system(size: 10))
                .foregroundStyle(sub == nil ? .tertiary : .secondary)
                .monospacedDigit()
                .fixedSize(horizontal: false, vertical: true)
                .padding(.leading, 11)
        }
    }

    private func subscriptionDetail(_ sub: Subscription?, currency: String) -> String {
        guard let sub else { return "No subscription info" }
        return "\(sub.planLabel) · \(Fmt.perMonth(sub.monthlyPriceUsd, currency: currency)) · anchor \(sub.anchorDay) · \(sub.cycleSource)"
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
