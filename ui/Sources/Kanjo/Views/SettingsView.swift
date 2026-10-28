import AppKit
import SwiftUI
import KanjoCore

struct SettingsView: View {
    static let bottomAnchor = "settings-bottom"

    @EnvironmentObject var store: ReportStore
    var scrollTo: String? = nil     // 支持底部或具体订阅行
    var initiallyEditingAgent: String? = nil
    let onBack: () -> Void

    @AppStorage(SettingsKeys.appLanguage, store: AppDefaults.store) private var appLanguage = AppLanguage.system.rawValue
    @AppStorage(SettingsKeys.sourceKind, store: AppDefaults.store) private var sourceKind =
        (DefaultPaths.cliDirectoryExists ? SourceKind.cli : SourceKind.file).rawValue
    @AppStorage(SettingsKeys.filePath, store: AppDefaults.store) private var filePath = ""
    @AppStorage(SettingsKeys.cliCommand, store: AppDefaults.store) private var cliCommand = CLIDataSource.defaultCommand
    @AppStorage(SettingsKeys.cliWorkingDirectory, store: AppDefaults.store) private var cliWorkingDirectory = ""
    @AppStorage(SettingsKeys.refreshMinutes, store: AppDefaults.store) private var refreshMinutes = 5
    @AppStorage(SettingsKeys.showAmountInMenuBar, store: AppDefaults.store) private var showAmount = true
    @AppStorage(SettingsKeys.menuBarMode, store: AppDefaults.store) private var menuBarMode = MenuBarMode.cost.rawValue
    @AppStorage(SettingsKeys.hiddenProjects, store: AppDefaults.store) private var hiddenRaw = ""
    @AppStorage(SettingsKeys.cloudSyncEnabled, store: AppDefaults.store) private var cloudSyncEnabled = false
    @AppStorage(SettingsKeys.cloudSyncHideProjectNames, store: AppDefaults.store) private var cloudSyncHideNames = false
    @StateObject private var cloudSync = CloudSyncStore.shared

    private let intervals = [0, 1, 5, 15, 30, 60]

    var body: some View {
        ScrollViewReader { proxy in
        OptionalScrollView {
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
                            .hoverTip(L10n.tr("settings.disk_command_help"))
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

                PanelSection(L10n.tr("settings.section.icloud"), inset: true) {
                    Toggle(L10n.tr("settings.sync.enable"), isOn: $cloudSyncEnabled)
                        .font(.system(size: 12))
                    if cloudSyncEnabled {
                        Toggle(L10n.tr("settings.sync.hide_names"), isOn: $cloudSyncHideNames)
                            .font(.system(size: 12))
                    }
                    Text(syncStatusText)
                        .font(.system(size: 10.5))
                        .foregroundStyle(syncStatusColor)
                        .fixedSize(horizontal: false, vertical: true)
                    if cloudSyncEnabled, let code = cloudSync.accountCode {
                        Text(L10n.tr("sync.account_code", code))
                            .font(.system(size: 10.5).monospacedDigit())
                            .foregroundStyle(.secondary)
                            .help(L10n.tr("settings.sync.account_help"))
                    }
                    note(L10n.tr("settings.sync.note"))
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
                subscriptionsSection(proxy: proxy)

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
        .task(id: store.report?.generatedAt ?? (store.report == nil ? "" : "loaded")) {
            guard store.report != nil, let a = scrollTo else { return }
            scroll(to: a, with: proxy)
        }
        .onChange(of: store.report) { report in
            guard report != nil, let a = scrollTo else { return }
            scroll(to: a, with: proxy)
        }
        .onAppear {
            if let a = scrollTo {
                scroll(to: a, with: proxy)
            }
        }
        }
        .onChange(of: refreshMinutes) { _ in store.restartTimer() }
        .onChange(of: sourceKind) { _ in store.applySettings() }
        .task { await cloudSync.loadAccountCode() }
        .onChange(of: cloudSyncEnabled) { enabled in
            cloudSync.setEnabled(enabled)
            Task { await cloudSync.loadAccountCode() }
            if enabled {
                cloudSync.resetUploadState()
                store.refresh()
            }
        }
        .onChange(of: cloudSyncHideNames) { _ in
            cloudSync.resetUploadState()
            if cloudSyncEnabled { store.refresh() }
        }
    }

    private var syncStatusText: String {
        switch cloudSync.status {
        case .off:
            return L10n.tr("settings.sync.status.off")
        case .waitingForICloud:
            return L10n.tr("settings.sync.status.waiting")
        case .uploaded(let date):
            return L10n.tr("settings.sync.status.uploaded", Self.clock(date))
        case .failed(let message):
            return L10n.tr("settings.sync.status.failed", message)
        }
    }

    private var syncStatusColor: Color {
        switch cloudSync.status {
        case .off:
            return .secondary
        case .waitingForICloud, .uploaded:
            return .secondary
        case .failed:
            return .red
        }
    }

    private static func clock(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: L10n.currentLanguage)
        formatter.setLocalizedDateFormatFromTemplate("HHmm")
        return formatter.string(from: date)
    }

    /// 各 agent 的额度重置时间和来源（quota_windows），供总览的「Since reset」范围用。
    private var quotaSection: some View {
        PanelSection(L10n.tr("settings.section.quota_reset"), inset: true) {
            if let r = store.report {
                let agents = quotaAgentList(report: r)
                let quota = r.quotaWindows ?? [:]
                let cal = RangeEngine.calendar(timezone: RangeEngine.timezone(of: r))
                if agents.isEmpty {
                    Text(L10n.tr("settings.no_reset_info"))
                        .font(.system(size: 11)).foregroundStyle(.tertiary)
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(agents, id: \.self) { agent in
                            QuotaResetSettingsRow(agent: agent, quota: quota[agent],
                                                  label: r.agentLabels[agent] ?? AgentColors.defaultLabels[agent] ?? agent,
                                                  calendar: cal)
                        }
                    }
                }
            } else {
                note(L10n.tr("settings.no_data_loaded"))
            }
            note(L10n.tr("settings.quota_note"))
        }
    }

    private func quotaAgentList(report r: UsageReport) -> [String] {
        let subs = r.subscriptions ?? [:]
        let quota = r.quotaWindows ?? [:]
        return subscriptionAgentList(report: r).filter { subs[$0] != nil || quota[$0] != nil }
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
        if let editing = initiallyEditingAgent, !seen.contains(editing) {
            agentList.append(editing)
            seen.insert(editing)
        }
        return agentList
    }

    private func scroll(to anchor: String, with proxy: ScrollViewProxy) {
        let align: UnitPoint = anchor == Self.bottomAnchor ? .bottom : .top
        DispatchQueue.main.async {
            proxy.scrollTo(anchor, anchor: align)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            proxy.scrollTo(anchor, anchor: align)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            proxy.scrollTo(anchor, anchor: align)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            proxy.scrollTo(anchor, anchor: align)
        }
    }

    /// 各 agent 的订阅档位（subscriptions），供总览的 Subscription value 卡和 Billing cycle 范围用。
    private func subscriptionsSection(proxy: ScrollViewProxy) -> some View {
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
                                                currency: r.currency,
                                                initiallyEditing: agent == initiallyEditingAgent)
                            .id(item.anchor)
                            .onAppear {
                                if item.anchor == scrollTo {
                                    scroll(to: item.anchor, with: proxy)
                                }
                            }
                    }
                }
            } else {
                note(L10n.tr("settings.no_data_loaded"))
            }
            note(L10n.tr("settings.subscriptions_note"))
        }
    }

    static func stamp(_ d: Date, _ cal: Calendar) -> String {
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
    let initiallyEditing: Bool

    @State private var day: Int
    @State private var isEditingOverride: Bool? = nil
    private var isEditing: Bool {
        get { isEditingOverride ?? initiallyEditing }
        nonmutating set { isEditingOverride = newValue }
    }
    @State private var selectedPlanKey: String = ""
    @State private var customPlanText: String = ""
    @State private var inputPrice: String = ""
    @State private var saving = false
    @State private var actionError: String?

    private let otherPlanTag = "__custom_other__"

    init(agent: String, sub: Subscription?, label: String, currency: String, initiallyEditing: Bool = false) {
        self.agent = agent
        self.sub = sub
        self.label = label
        self.currency = currency
        self.initiallyEditing = initiallyEditing
        _isEditingOverride = State(initialValue: initiallyEditing ? true : nil)
        _day = State(initialValue: min(28, max(1, sub?.anchorDay ?? 1)))

        let plans = KnownPlan.fallbackPlans[agent] ?? []
        if let currentPlan = sub?.plan, !currentPlan.isEmpty {
            if let matching = plans.first(where: { $0.key == currentPlan }) ?? plans.first(where: { $0.label == sub?.planLabel }) {
                _selectedPlanKey = State(initialValue: matching.key)
                _customPlanText = State(initialValue: "")
            } else {
                _selectedPlanKey = State(initialValue: otherPlanTag)
                _customPlanText = State(initialValue: currentPlan)
            }
        } else if initiallyEditing, let first = plans.first {
            _selectedPlanKey = State(initialValue: first.key)
            _customPlanText = State(initialValue: "")
        } else {
            _selectedPlanKey = State(initialValue: sub?.plan ?? "")
            _customPlanText = State(initialValue: sub?.plan ?? sub?.planLabel ?? "")
        }

        if let price = sub?.monthlyPriceUsd {
            let s = price.truncatingRemainder(dividingBy: 1) == 0 ? String(format: "%.0f", price) : String(price)
            _inputPrice = State(initialValue: s)
        } else if initiallyEditing, let first = plans.first, let listPrice = first.monthlyPriceUsd {
            let s = listPrice.truncatingRemainder(dividingBy: 1) == 0 ? String(format: "%.0f", listPrice) : String(listPrice)
            _inputPrice = State(initialValue: s)
        } else {
            _inputPrice = State(initialValue: "")
        }
    }

    private var agentKnownPlans: [KnownPlan]? {
        store.knownPlans?[agent] ?? KnownPlan.fallbackPlans[agent]
    }

    private var hasKnownPlans: Bool {
        !(agentKnownPlans?.isEmpty ?? true)
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
        .onAppear {
            if initiallyEditing {
                isEditingOverride = true
            }
            syncInputs()
            Task { await store.loadKnownPlans() }
        }
        .onChange(of: initiallyEditing) { editing in
            if editing {
                isEditingOverride = true
                syncInputs()
            }
        }
        .onChange(of: sub?.anchorDay) { value in
            day = min(28, max(1, value ?? 1))
        }
        .onChange(of: sub) { _ in
            if !isEditing {
                syncInputs()
            }
        }
        .onChange(of: store.knownPlans) { _ in
            if !isEditing || initiallyEditing {
                syncInputs()
            }
        }
        .onChange(of: selectedPlanKey) { newKey in
            onPlanSelectionChanged(newKey: newKey)
        }
    }

    private func onPlanSelectionChanged(newKey: String) {
        guard isEditing else { return }
        if newKey == otherPlanTag {
            if let price = sub?.monthlyPriceUsd {
                inputPrice = formatPrice(price)
            } else {
                inputPrice = ""
            }
        } else if let matching = agentKnownPlans?.first(where: { $0.key == newKey }) {
            customPlanText = ""
            if let listPrice = matching.monthlyPriceUsd {
                inputPrice = formatPrice(listPrice)
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
        Stepper(L10n.tr("settings.renews_on_day", day), value: $day, in: 1...28)
            .font(.system(size: 11)).monospacedDigit()
            .lineLimit(1)
            .disabled(!store.canEditSubscriptions || saving || store.isLoading)
            .hoverTip(store.canEditSubscriptions ? L10n.tr("settings.renews_day_help") : L10n.tr("settings.renews_day_disabled_help"))
            .padding(.leading, 11)
        HStack(spacing: 6) {
            Spacer()
            Button(L10n.tr("common.apply")) { saveAnchor(day) }
            Button(L10n.tr("common.reset")) { resetAll() }
            Button(L10n.tr("settings.edit")) {
                syncInputs()
                isEditingOverride = true
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
                isEditingOverride = true
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
        VStack(alignment: .leading, spacing: 6) {
            // Row 1: Plan Picker (or free text)
            if let plans = agentKnownPlans, !plans.isEmpty {
                Picker("", selection: $selectedPlanKey) {
                    ForEach(plans) { plan in
                        Text(planMenuLabel(plan)).tag(plan.key)
                    }
                    Text(L10n.tr("settings.plan_other")).tag(otherPlanTag)
                }
                .labelsHidden()
                .pickerStyle(.menu)

                if selectedPlanKey == otherPlanTag {
                    TextField(L10n.tr("settings.plan"), text: $customPlanText)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(size: 11))
                }
            } else {
                TextField(L10n.tr("settings.plan"), text: $customPlanText)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 11))
            }

            // Row 2: Monthly price field & Stepper
            HStack(spacing: 8) {
                TextField(L10n.tr("settings.monthly_price_usd"), text: $inputPrice)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 11, design: .monospaced))
                    .frame(width: 85)
                Stepper(L10n.tr("settings.renews_on_day", day), value: $day, in: 1...28)
                    .font(.system(size: 11)).monospacedDigit()
                Spacer(minLength: 0)
            }

            // Row 3: Actions right-aligned
            HStack(spacing: 6) {
                Spacer()
                Button(L10n.tr("common.apply")) { applyManual() }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                Button(L10n.tr("common.cancel")) {
                    isEditingOverride = false
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
        }
        .disabled(saving || store.isLoading)
        .padding(.leading, 11)
    }

    private func planMenuLabel(_ plan: KnownPlan) -> String {
        if let price = plan.monthlyPriceUsd {
            return "\(plan.label) · \(Fmt.perMonth(price, currency: currency))"
        }
        return plan.label
    }

    private func syncInputs() {
        day = min(28, max(1, sub?.anchorDay ?? 1))
        let plans = agentKnownPlans ?? []
        if let currentPlan = sub?.plan, !currentPlan.isEmpty {
            if let matching = plans.first(where: { $0.key == currentPlan }) ?? plans.first(where: { $0.label == sub?.planLabel }) {
                selectedPlanKey = matching.key
                customPlanText = ""
            } else {
                selectedPlanKey = otherPlanTag
                customPlanText = currentPlan
            }
        } else if let first = plans.first {
            selectedPlanKey = first.key
            customPlanText = ""
        } else {
            selectedPlanKey = otherPlanTag
            customPlanText = sub?.planLabel ?? ""
        }

        if let price = sub?.monthlyPriceUsd {
            inputPrice = formatPrice(price)
        } else if let matching = plans.first(where: { $0.key == selectedPlanKey }), let listPrice = matching.monthlyPriceUsd {
            inputPrice = formatPrice(listPrice)
        } else {
            inputPrice = ""
        }
    }

    private func formatPrice(_ price: Double) -> String {
        price.truncatingRemainder(dividingBy: 1) == 0 ? String(format: "%.0f", price) : String(price)
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
        let isCustom = !hasKnownPlans || selectedPlanKey == otherPlanTag
        let plan = isCustom ? customPlanText.trimmingCharacters(in: .whitespacesAndNewlines) : selectedPlanKey
        guard !plan.isEmpty else {
            actionError = L10n.tr("settings.error.plan_required")
            return
        }

        let matchingPlan = hasKnownPlans ? agentKnownPlans?.first(where: { $0.key == selectedPlanKey }) : nil
        let listPrice = isCustom ? nil : matchingPlan?.monthlyPriceUsd
        let priceStr = inputPrice.trimmingCharacters(in: .whitespacesAndNewlines)

        var enteredPrice: Double? = nil
        if !priceStr.isEmpty {
            guard let p = Double(priceStr), p >= 0, p.isFinite else {
                actionError = L10n.tr("settings.error.invalid_price")
                return
            }
            enteredPrice = p
        } else if listPrice == nil {
            actionError = L10n.tr("settings.error.price_required")
            return
        } else {
            enteredPrice = listPrice
        }

        let fields = SubscriptionPlanHelper.fieldsToSave(
            plan: plan,
            isCustom: isCustom,
            enteredPrice: enteredPrice,
            listPrice: listPrice,
            anchorDay: day
        )

        saving = true
        actionError = nil
        Task {
            do {
                try await store.setSubscription(
                    agent: agent,
                    plan: fields.plan,
                    monthlyPriceUsd: fields.monthlyPriceUsd,
                    anchorDay: fields.anchorDay
                )
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

private struct QuotaResetSettingsRow: View {
    @EnvironmentObject var store: ReportStore
    let agent: String
    let quota: QuotaWindow?
    let label: String
    let calendar: Calendar

    @State private var weekday: String
    @State private var time: String
    @State private var saving = false
    @State private var actionError: String?

    private static let weekdays: [(key: String, label: String)] = [
        ("mon", L10n.tr("weekday.mon")),
        ("tue", L10n.tr("weekday.tue")),
        ("wed", L10n.tr("weekday.wed")),
        ("thu", L10n.tr("weekday.thu")),
        ("fri", L10n.tr("weekday.fri")),
        ("sat", L10n.tr("weekday.sat")),
        ("sun", L10n.tr("weekday.sun")),
    ]

    private static let standardTimes: [String] = {
        var res: [String] = []
        for h in 0..<24 {
            res.append(String(format: "%02d:00", h))
            res.append(String(format: "%02d:30", h))
        }
        return res
    }()

    private var availableTimes: [String] {
        var set = Set(Self.standardTimes)
        set.insert(time)
        return set.sorted()
    }

    init(agent: String, quota: QuotaWindow?, label: String, calendar: Calendar) {
        self.agent = agent
        self.quota = quota
        self.label = label
        self.calendar = calendar

        let (initWeekday, initTime) = Self.parseWeekdayAndTime(quota: quota, calendar: calendar)
        _weekday = State(initialValue: initWeekday)
        _time = State(initialValue: initTime)
    }

    private static func parseWeekdayAndTime(quota: QuotaWindow?, calendar: Calendar) -> (String, String) {
        if let quota, let date = ReportDates.parseTimestamp(quota.weeklyResetsAt) {
            let weekdayKeys = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
            let wIdx = calendar.component(.weekday, from: date)
            let wKey = (1...7).contains(wIdx) ? weekdayKeys[wIdx - 1] : "tue"
            let h = calendar.component(.hour, from: date)
            let m = calendar.component(.minute, from: date)
            return (wKey, String(format: "%02d:%02d", h, m))
        }
        return ("tue", "05:00")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 5) {
                AgentDot(agent: agent, size: 6)
                Text(label).font(.system(size: 11.5)).lineLimit(1)
                Spacer(minLength: 4)
                Text(quota?.source ?? "none")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(quota == nil ? .tertiary : .secondary)
            }

            if let quota, let reset = ReportDates.parseTimestamp(quota.weeklyResetsAt) {
                let start = RangeEngine.windowStart(quota, now: Date(), calendar: calendar)
                HStack(spacing: 4) {
                    Text(SettingsView.stamp(reset, calendar))
                        .font(.system(size: 10.5)).monospacedDigit()
                    if let start {
                        Text("· " + L10n.tr("settings.quota_window_since", SettingsView.stamp(start, calendar), quota.weeklyWindowHours))
                            .font(.system(size: 10)).foregroundStyle(.secondary).monospacedDigit()
                    }
                }
                .padding(.leading, 11)
            } else {
                Text(L10n.tr("settings.no_reset_info"))
                    .font(.system(size: 10.5)).foregroundStyle(.tertiary)
                    .padding(.leading, 11)
            }

            HStack(spacing: 6) {
                Picker("", selection: $weekday) {
                    ForEach(Self.weekdays, id: \.key) { w in
                        Text(w.label).tag(w.key)
                    }
                }
                .labelsHidden()
                .controlSize(.small)
                .frame(width: 68)

                Picker("", selection: $time) {
                    ForEach(availableTimes, id: \.self) { t in
                        Text(t).tag(t)
                    }
                }
                .labelsHidden()
                .controlSize(.small)
                .frame(width: 64)

                Button(L10n.tr("common.apply")) {
                    saveReset("\(weekday) \(time)")
                }
                .buttonStyle(.bordered)
                .controlSize(.small)

                Button(L10n.tr("common.reset")) {
                    clearReset()
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(quota?.source != "manual")
            }
            .disabled(!store.canEditSubscriptions || saving || store.isLoading)
            .hoverTip(store.canEditSubscriptions ? "" : L10n.tr("settings.renews_day_disabled_help"))
            .padding(.leading, 11)

            if saving {
                Text(L10n.tr("settings.saving"))
                    .font(.system(size: 10)).foregroundStyle(.secondary)
                    .padding(.leading, 11)
            }

            if let actionError {
                StatusBlock(kind: .bad, icon: "xmark.octagon.fill") {
                    Text(actionError).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                }
                .padding(.leading, 11)
            }
        }
        .onChange(of: quota) { newQuota in
            let (w, t) = Self.parseWeekdayAndTime(quota: newQuota, calendar: calendar)
            weekday = w
            time = t
        }
    }

    private func saveReset(_ val: String) {
        saving = true
        actionError = nil
        Task {
            do {
                try await store.setWeeklyReset(agent: agent, reset: val)
                saving = false
            } catch {
                saving = false
                actionError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
        }
    }

    private func clearReset() {
        saving = true
        actionError = nil
        Task {
            do {
                try await store.setWeeklyReset(agent: agent, reset: nil)
                saving = false
            } catch {
                saving = false
                actionError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
        }
    }
}
