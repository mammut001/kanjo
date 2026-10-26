import AppKit
import SwiftUI
import KanjoCore

struct SettingsView: View {
    static let bottomAnchor = "settings-bottom"

    @EnvironmentObject var store: ReportStore
    var scrollTo: String? = nil     // 支持底部或具体订阅行
    let onBack: () -> Void

    @AppStorage(SettingsKeys.appLanguage) private var appLanguage = AppLanguage.system.rawValue
    @AppStorage(SettingsKeys.sourceKind) private var sourceKind =
        (DefaultPaths.cliDirectoryExists ? SourceKind.cli : SourceKind.file).rawValue
    @AppStorage(SettingsKeys.filePath) private var filePath = ""
    @AppStorage(SettingsKeys.cliCommand) private var cliCommand = CLIDataSource.defaultCommand
    @AppStorage(SettingsKeys.cliWorkingDirectory) private var cliWorkingDirectory = ""
    @AppStorage(SettingsKeys.refreshMinutes) private var refreshMinutes = 5
    @AppStorage(SettingsKeys.showAmountInMenuBar) private var showAmount = true
    @AppStorage(SettingsKeys.menuBarMode) private var menuBarMode = MenuBarMode.cost.rawValue
    @AppStorage(SettingsKeys.hiddenProjects) private var hiddenRaw = ""

    private let intervals = [0, 1, 5, 15, 30, 60]

    var body: some View {
        ScrollViewReader { proxy in
        ScrollView {
            VStack(alignment: .leading, spacing: Metrics.sectionSpacing) {
                VStack(alignment: .leading, spacing: 8) {
                    BackButton(title: L10n.tr("common.done"), action: onBack)
                        .padding(.leading, -4)
                    Text(L10n.tr("settings.title")).font(.system(size: 15, weight: .semibold))
                }
                .padding(.horizontal, Metrics.rowInset)

                if let o = store.dataOverride {
                    StatusBlock(kind: .warn, icon: "exclamationmark.triangle.fill") {
                        Text(L10n.tr("settings.data_override", o.path))
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                    }
                }

                PanelSection(L10n.tr("settings.section.language"), inset: true) {
                    Picker(L10n.tr("settings.language"), selection: $appLanguage) {
                        ForEach(AppLanguage.allCases) { lang in
                            Text(lang.displayName).tag(lang.rawValue)
                        }
                    }
                    .font(.system(size: 12))
                }

                PanelSection(L10n.tr("settings.section.data_source"), inset: true) {
                    Picker("Source", selection: $sourceKind) {
                        ForEach(SourceKind.allCases) { Text($0.label).tag($0.rawValue) }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()

                    if sourceKind == SourceKind.cli.rawValue {
                        note(DefaultPaths.cliDescription(customDirectory: cliWorkingDirectory, customCommand: cliCommand))
                        field(L10n.tr("settings.command"), text: $cliCommand, placeholder: CLIDataSource.defaultCommand)
                        HStack(alignment: .bottom) {
                            field(L10n.tr("settings.working_directory"), text: $cliWorkingDirectory,
                                  placeholder: DefaultPaths.resolvedCLIDirectory()?.path ?? L10n.tr("settings.inherit"))
                            Button(L10n.tr("settings.choose")) { if let p = chooseFolder() { cliWorkingDirectory = p } }
                        }
                        note(L10n.tr("settings.cli_note"))
                        Text(L10n.tr("settings.disk_command", derivedDiskCommand))
                            .font(.system(size: 10.5, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                            .help(L10n.tr("settings.disk_command_help"))
                    } else {
                        HStack(alignment: .bottom) {
                            field(L10n.tr("settings.json_file"), text: $filePath, placeholder: DefaultPaths.sampleFixture.path)
                            Button(L10n.tr("settings.choose")) { if let p = chooseFile() { filePath = p } }
                        }
                        note(L10n.tr("settings.file_note"))
                    }
                }

                PanelSection(L10n.tr("settings.section.refresh"), inset: true) {
                    Picker(L10n.tr("settings.auto_refresh"), selection: $refreshMinutes) {
                        ForEach(intervals, id: \.self) { m in
                            Text(m == 0 ? L10n.tr("settings.refresh_off") : L10n.tr("settings.refresh_minutes", m)).tag(m)
                        }
                    }
                    .font(.system(size: 12))
                    Picker(L10n.tr("settings.menu_bar_shows"), selection: $menuBarMode) {
                        ForEach(MenuBarMode.allCases) { mode in
                            Text(mode.label).tag(mode.rawValue)
                        }
                    }
                    .font(.system(size: 12))
                    Toggle(L10n.tr("settings.show_menu_bar_cost"), isOn: $showAmount)
                        .font(.system(size: 12))
                }

                PanelSection(L10n.tr("settings.section.projects"), inset: true) {
                    let hidden = ProjectPrefs.parse(hiddenRaw).count
                    HStack {
                        Text(L10n.tr("settings.hidden_projects_count", hidden)).font(.system(size: 12)).monospacedDigit()
                        Spacer()
                        Button(L10n.tr("settings.unhide_all")) { hiddenRaw = "" }
                            .disabled(hidden == 0)
                    }
                    note(L10n.tr("settings.projects_note"))
                }

                quotaSection
                subscriptionsSection

                VStack(alignment: .trailing, spacing: 8) {
                    Button(L10n.tr("settings.apply_refresh")) { store.applySettings() }
                        .keyboardShortcut(.defaultAction)
                        .buttonStyle(.borderedProminent)
                    Text(L10n.tr("settings.current_source", store.sourceDescription))
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
        PanelSection(L10n.tr("settings.section.quota_reset"), inset: true) {
            if let r = store.report {
                let ctx = RangeContext(report: r, raw: TimeRange.sinceReset.rawValue)
                let quota = r.quotaWindows ?? [:]
                let cal = RangeEngine.calendar(timezone: RangeEngine.timezone(of: r))
                Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                    GridRow {
                        Text(L10n.tr("settings.grid.agent")); Text(L10n.tr("settings.grid.next_reset")); Text(L10n.tr("settings.grid.source")).gridColumnAlignment(.trailing)
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
                note(L10n.tr("settings.no_data_loaded"))
            }
            note(L10n.tr("settings.quota_note"))
        }
    }

    private func subscriptionAgentList(report r: UsageReport) -> [String] {
        let ctx = RangeContext(report: r, raw: TimeRange.all.rawValue)
        let subs = r.subscriptions ?? [:]
        var agentList: [String] = []
        var seen = Set<String>()
        for a in ctx.agentOrder where subs[a] != nil {
            agentList.append(a)
            seen.insert(a)
        }
        for a in subs.keys.sorted() where !seen.contains(a) {
            agentList.append(a)
            seen.insert(a)
        }
        for a in ctx.agentOrder where !seen.contains(a) {
            agentList.append(a)
            seen.insert(a)
        }
        let knownOrder = ["claude", "codex", "antigravity", "grok", "copilot", "minimax", "qwen", "commandcode", "opencode"]
        for a in knownOrder where !seen.contains(a) {
            agentList.append(a)
            seen.insert(a)
        }
        return agentList
    }

    /// 各 agent 的订阅档位（subscriptions），供总览的 Subscription value 卡和 Billing cycle 范围用。
    private var subscriptionsSection: some View {
        PanelSection(L10n.tr("settings.section.subscriptions"), inset: true) {
            if let r = store.report {
                let subs = r.subscriptions ?? [:]
                let agents = subscriptionAgentList(report: r)
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(agents.map { (agent: $0, anchor: SubscriptionSettingsRoute.anchor(for: $0)) },
                            id: \.anchor) { item in
                        let agent = item.agent
                        SubscriptionSettingsRow(agent: agent, sub: subs[agent],
                                                label: r.agentLabels[agent] ?? AgentColors.defaultLabels[agent] ?? agent,
                                                currency: r.currency)
                            .id(item.anchor)
                    }
                }
            } else {
                note(L10n.tr("settings.no_data_loaded"))
            }
            note(L10n.tr("settings.subscriptions_note"))
        }
    }

    @ViewBuilder private func quotaCell(_ q: QuotaWindow?, cal: Calendar) -> some View {
        if let q, let reset = ReportDates.parseTimestamp(q.weeklyResetsAt) {
            let start = RangeEngine.windowStart(q, now: Date())
            VStack(alignment: .leading, spacing: 1) {
                Text(Self.stamp(reset, cal)).font(.system(size: 11.5)).monospacedDigit()
                if let start {
                    Text(L10n.tr("settings.quota_window_since", Self.stamp(start, cal), q.weeklyWindowHours))
                        .font(.system(size: 10)).foregroundStyle(.secondary).monospacedDigit()
                }
            }
        } else if q != nil {
            Text(L10n.tr("settings.unreadable")).font(.system(size: 11.5)).foregroundStyle(AgentPalette.warnInk)
        } else {
            Text(L10n.tr("settings.no_reset_info")).font(.system(size: 11.5)).foregroundStyle(.tertiary)
        }
    }

    private static func stamp(_ d: Date, _ cal: Calendar) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.currentLanguage)
        f.timeZone = cal.timeZone
        f.setLocalizedDateFormatFromTemplate("EEEMMMdHHmm")
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
    @State private var isEditing = false
    @State private var inputPlan: String = ""
    @State private var inputPrice: String = ""
    @State private var saving = false
    @State private var actionError: String?

    init(agent: String, sub: Subscription?, label: String, currency: String) {
        self.agent = agent
        self.sub = sub
        self.label = label
        self.currency = currency
        _day = State(initialValue: min(28, max(1, sub?.anchorDay ?? 1)))
        _inputPlan = State(initialValue: sub?.plan ?? sub?.planLabel ?? "")
        if let price = sub?.monthlyPriceUsd {
            let s = price.truncatingRemainder(dividingBy: 1) == 0 ? String(format: "%.0f", price) : String(price)
            _inputPrice = State(initialValue: s)
        } else {
            _inputPrice = State(initialValue: "")
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 5) {
                AgentDot(agent: agent, size: 6)
                Text(label).font(.system(size: 11.5)).lineLimit(1)
                Spacer(minLength: 8)
            }
            if isEditing {
                editingForm
            } else if let sub {
                displaySub(sub)
            } else {
                displayEmpty
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
        .onChange(of: sub) { newSub in
            inputPlan = newSub?.plan ?? newSub?.planLabel ?? ""
            if let price = newSub?.monthlyPriceUsd {
                inputPrice = price.truncatingRemainder(dividingBy: 1) == 0 ? String(format: "%.0f", price) : String(price)
            } else {
                inputPrice = ""
            }
        }
    }

    @ViewBuilder
    private func displaySub(_ sub: Subscription) -> some View {
        Text("\(sub.planLabel) · \(Fmt.perMonth(sub.monthlyPriceUsd, currency: currency))")
            .font(.system(size: 10)).foregroundStyle(.secondary)
            .padding(.leading, 11)
        HStack(spacing: 8) {
            Stepper(L10n.tr("settings.renews_on_day", day), value: $day, in: 1...28)
                .font(.system(size: 11)).monospacedDigit()
                .disabled(!store.canEditSubscriptions || saving || store.isLoading)
                .help(store.canEditSubscriptions ? L10n.tr("settings.renews_day_help") : L10n.tr("settings.renews_day_disabled_help"))
            Button(L10n.tr("common.apply")) { saveAnchor(day) }
            Button(L10n.tr("common.reset")) { resetAll() }
            Button(L10n.tr("settings.edit")) {
                syncInputs()
                isEditing = true
            }
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .disabled(!store.canEditSubscriptions || saving || store.isLoading)
        .padding(.leading, 11)
        Text(saving ? L10n.tr("settings.saving") : SubscriptionValue.anchorSource(sub))
            .font(.system(size: 10)).foregroundStyle(.secondary)
            .padding(.leading, 11)
        if let url = SubscriptionValue.billingPage(for: agent) {
            Button(L10n.tr("settings.open_billing_page")) { NSWorkspace.shared.open(url) }
                .buttonStyle(.link)
                .font(.system(size: 11))
                .padding(.leading, 11)
            Text(L10n.tr("settings.billing_page_hint"))
                .font(.system(size: 10)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.leading, 11)
        }
    }

    @ViewBuilder
    private var displayEmpty: some View {
        HStack(spacing: 8) {
            Text(L10n.tr("settings.no_subscription_info"))
                .font(.system(size: 10)).foregroundStyle(.tertiary)
            Button(L10n.tr("settings.add_subscription")) {
                syncInputs()
                isEditing = true
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(!store.canEditSubscriptions || saving || store.isLoading)
        }
        .padding(.leading, 11)
        if let url = SubscriptionValue.billingPage(for: agent) {
            Button(L10n.tr("settings.open_billing_page")) { NSWorkspace.shared.open(url) }
                .buttonStyle(.link)
                .font(.system(size: 11))
                .padding(.leading, 11)
        }
    }

    @ViewBuilder
    private var editingForm: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                TextField(L10n.tr("settings.plan"), text: $inputPlan)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 11))
                    .frame(width: 140)
                TextField(L10n.tr("settings.monthly_price_usd"), text: $inputPrice)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 11, design: .monospaced))
                    .frame(width: 80)
                Stepper(L10n.tr("settings.renews_on_day", day), value: $day, in: 1...28)
                    .font(.system(size: 11)).monospacedDigit()
                Button(L10n.tr("common.apply")) { applyManual() }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                Button(L10n.tr("common.cancel")) {
                    isEditing = false
                    syncInputs()
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                if sub != nil {
                    Button(L10n.tr("settings.remove_subscription")) { removeManual() }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                }
            }
            .disabled(saving || store.isLoading)
        }
        .padding(.leading, 11)
    }

    private func syncInputs() {
        day = min(28, max(1, sub?.anchorDay ?? 1))
        inputPlan = sub?.plan ?? sub?.planLabel ?? ""
        if let price = sub?.monthlyPriceUsd {
            inputPrice = price.truncatingRemainder(dividingBy: 1) == 0 ? String(format: "%.0f", price) : String(price)
        } else {
            inputPrice = ""
        }
    }

    private func saveAnchor(_ value: Int?) {
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

    private func applyManual() {
        let plan = inputPlan.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !plan.isEmpty else {
            actionError = L10n.tr("settings.error.plan_required")
            return
        }
        let priceStr = inputPrice.trimmingCharacters(in: .whitespacesAndNewlines)
        var price: Double? = nil
        if !priceStr.isEmpty {
            guard let p = Double(priceStr), p >= 0, p.isFinite else {
                actionError = L10n.tr("settings.error.invalid_price")
                return
            }
            price = p
        }
        saving = true
        actionError = nil
        Task {
            do {
                try await store.setSubscription(agent: agent, plan: plan, monthlyPriceUsd: price, anchorDay: day)
                isEditing = false
            } catch {
                actionError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            saving = false
        }
    }

    private func removeManual() {
        saving = true
        actionError = nil
        Task {
            do {
                try await store.removeSubscription(agent: agent)
                isEditing = false
            } catch {
                actionError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            saving = false
        }
    }

    private func resetAll() {
        if sub?.source == "manual" {
            removeManual()
        } else {
            saveAnchor(nil)
        }
    }
}
