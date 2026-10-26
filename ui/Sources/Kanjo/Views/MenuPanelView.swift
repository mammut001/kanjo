import AppKit
import SwiftUI
import KanjoCore

enum Route: Equatable {
    case overview
    case project(String)
    case bucket(BucketKind)
    case disk
    case settings
}

enum BucketKind: String {
    case unattributed, excluded
}

/// 开发开关 `--route <value>`：启动后直接打开某一页，便于截图。
/// 取值：`overview`、`overview-bottom`（总览滚到底部）、`project:<index>`（按 cost 降序的第 index 个，从 0 开始）、
/// `project:<index>:bottom`（详情页滚到底部）、`project:<index>:locations`（滚到底部并展开 Locations）、
/// `bucket:unattributed` / `bucket:excluded`、`disk`、`disk:expanded`（磁盘页展开每个 agent，仅供截图）、
/// `settings`、`settings-bottom`（设置页滚到最底部，含 Subscriptions）、`settings:subscriptions:<agent>`、
/// `settings:subscriptions:<agent>:edit`（滚到该 agent 的订阅行并直接进入编辑态，加载 plan picker）。
enum DevRoute {
    static let requested: String? = {
        let args = CommandLine.arguments
        guard let i = args.firstIndex(of: "--route"), i + 1 < args.count else { return nil }
        return args[i + 1]
    }()

    /// 需要数据才能解析的取值在 report 为 nil 时返回 nil（等数据到了再解析）。
    static func resolve(_ raw: String, report: UsageReport?) -> (route: Route, anchor: String?, editingAgent: String?)? {
        switch raw {
        case "settings": return (.settings, nil, nil)
        case "settings-bottom": return (.settings, SettingsView.bottomAnchor, nil)
        case "overview": return (.overview, nil, nil)
        case "overview-bottom": return report == nil ? nil : (.overview, OverviewView.bottomAnchor, nil)
        case "disk": return (.disk, nil, nil)
        case "disk:expanded": return (.disk, DiskView.expandedAnchor, nil)
        default: break
        }
        if let agent = SubscriptionSettingsRoute.editAgent(from: raw) {
            guard report != nil else { return nil }
            return (.settings, SubscriptionSettingsRoute.anchor(for: agent), agent)
        }
        if let agent = SubscriptionSettingsRoute.agent(from: raw) {
            guard report != nil else { return nil }
            return (.settings, SubscriptionSettingsRoute.anchor(for: agent), nil)
        }
        guard let r = report else { return nil }
        if raw.hasPrefix("project:") {
            let parts = raw.dropFirst("project:".count).split(separator: ":", maxSplits: 1)
            guard let first = parts.first, let i = Int(first) else { return (.overview, nil, nil) }
            let sorted = r.projects.sorted { $0.cost > $1.cost }
            guard sorted.indices.contains(i) else { return (.overview, nil, nil) }
            let anchor: String?
            switch parts.count > 1 ? String(parts[1]) : "" {
            case "bottom": anchor = ProjectDetailView.bottomAnchor
            case "locations": anchor = ProjectDetailView.locationsOpenAnchor
            default: anchor = nil
            }
            return (.project(sorted[i].id), anchor, nil)
        }
        if raw.hasPrefix("bucket:"), let k = BucketKind(rawValue: String(raw.dropFirst("bucket:".count))) {
            return (.bucket(k), nil, nil)
        }
        return (.overview, nil, nil)
    }
}

struct MenuPanelView: View {
    static let size = CGSize(width: 360, height: 620)

    @EnvironmentObject var store: ReportStore
    @EnvironmentObject var disk: DiskStore
    @AppStorage(SettingsKeys.appLanguage, store: AppDefaults.store) private var appLanguage = AppLanguage.system.rawValue
    @State private var route: Route = .overview
    @State private var pendingDevRoute = DevRoute.requested
    @State private var overviewAnchor: String?
    @State private var editingSubscriptionAgent: String?

    var body: some View {
        VStack(spacing: 0) {
            banners
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            footer
        }
        .frame(width: Self.size.width, height: Self.size.height)
        .panelBackground()
        .onAppear { applyDevRoute(report: store.report) }
        .onReceive(store.$report) { applyDevRoute(report: $0) }
    }

    /// `disk` 不依赖用量报告，出现时就能打开；项目页要等报告到了再解析。
    private func applyDevRoute(report: UsageReport?) {
        guard let raw = pendingDevRoute, let resolved = DevRoute.resolve(raw, report: report) else { return }
        pendingDevRoute = nil
        route = resolved.route
        overviewAnchor = resolved.anchor
        editingSubscriptionAgent = resolved.editingAgent
    }

    // 只在出问题时出现：schema 版本过新（警告）、刷新失败但还有旧数据（错误）。
    @ViewBuilder private var banners: some View {
        let schemaWarning = store.report?.isNewerSchema == true
        let refreshFailed = store.report != nil && store.error != nil
        if schemaWarning || refreshFailed || store.needsCommandLineTools {
            VStack(spacing: 6) {
                if store.needsCommandLineTools {
                    StatusBlock(kind: .bad, icon: "xmark.octagon.fill") {
                        Text(L10n.tr("menu.python_needed"))
                            .fixedSize(horizontal: false, vertical: true)
                        HStack {
                            Button(L10n.tr("menu.install_clt")) { store.installCommandLineTools() }
                            Button(L10n.tr("common.retry")) {
                                Task { await store.checkPython(); store.refresh() }
                            }
                        }
                    }
                }
                if let r = store.report, r.isNewerSchema {
                    StatusBlock(kind: .warn, icon: "exclamationmark.triangle.fill") {
                        Text(L10n.tr("menu.schema_warning", r.schemaVersion, supportedSchemaVersion))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                if store.report != nil, let err = store.error {
                    StatusBlock(kind: .bad, icon: "xmark.octagon.fill") {
                        Text(L10n.tr("menu.refresh_failed_banner")).fontWeight(.semibold)
                        Text(err)
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                    }
                }
            }
            .padding(.horizontal, 10).padding(.top, 10).padding(.bottom, 2)
        }
    }

    @ViewBuilder private var content: some View {
        switch route {
        case .settings:
            SettingsView(scrollTo: overviewAnchor, initiallyEditingAgent: editingSubscriptionAgent, onBack: {
                route = .overview
                overviewAnchor = nil
                editingSubscriptionAgent = nil
                store.applySettings()
            })
        case .disk:
            DiskView(expandAll: overviewAnchor == DiskView.expandedAnchor, onBack: {
                route = .overview
                overviewAnchor = nil
            }, onSettings: { route = .settings })
        default:
            if let r = store.report {
                switch route {
                case .project(let id):
                    if let p = r.projects.first(where: { $0.id == id }) {
                        ProjectDetailView(project: p, report: r, devAnchor: overviewAnchor,
                                          onBack: { route = .overview; overviewAnchor = nil })
                    } else {
                        missing(L10n.tr("menu.project_missing"))
                    }
                case .bucket(let kind):
                    BucketDetailView(kind: kind, report: r, onBack: { route = .overview })
                default:
                    OverviewView(report: r, scrollAnchor: overviewAnchor, onSelect: { route = $0 },
                                 onSetRenewalDay: { agent in
                        overviewAnchor = SubscriptionSettingsRoute.anchor(for: agent)
                        route = .settings
                    })
                }
            } else if let err = store.error {
                ErrorStateView(message: err, source: store.sourceDescription,
                               onRetry: { store.refresh() }, onSettings: { route = .settings })
            } else {
                VStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(L10n.tr("common.loading")).font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func missing(_ text: String) -> some View {
        VStack(spacing: 8) {
            Text(text).font(.system(size: 12)).foregroundStyle(.secondary)
            BackButton(title: L10n.tr("menu.back_to_overview")) { route = .overview }
        }
    }

    // 底栏：一条玻璃条，里面是无底的图标按钮。
    private var footer: some View {
        HStack(spacing: 2) {
            Button {
                if route == .disk {
                    disk.refresh(rescan: true)
                } else {
                    store.refresh()
                }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(IconButtonStyle())
            .help(L10n.tr("menu.refresh_now"))
            .disabled(route == .disk ? disk.isLoading : store.isLoading)

            Group {
                if route == .disk {
                    if disk.isLoading {
                        Text(L10n.tr("menu.refreshing"))
                    } else if let t = disk.lastRefresh {
                        Text(L10n.tr("menu.updated_at", ShortDate.clock(t)))
                    } else {
                        Text(L10n.tr("menu.not_refreshed_yet"))
                    }
                } else if store.isLoading {
                    Text(L10n.tr("menu.refreshing"))
                } else if let t = store.lastRefresh {
                    Text(L10n.tr("menu.updated_at", ShortDate.clock(t)))
                } else {
                    Text(L10n.tr("menu.not_refreshed_yet"))
                }
            }
            .font(.system(size: 11).monospacedDigit())
            .foregroundStyle(.secondary)
            .help(route == .disk ? disk.sourceDescription : store.sourceDescription)

            Spacer()

            Button {
                let wasSettings = route == .settings
                route = route == .disk ? .overview : .disk
                overviewAnchor = nil
                if wasSettings { store.applySettings() }
            } label: {
                Image(systemName: "internaldrive")
            }
            .buttonStyle(IconButtonStyle(active: route == .disk))
            .help(L10n.tr("menu.disk"))

            Button {
                overviewAnchor = nil
                route = route == .settings ? .overview : .settings
                if route == .overview { store.applySettings() }
            } label: {
                Image(systemName: "gearshape")
            }
            .buttonStyle(IconButtonStyle())
            .help(L10n.tr("menu.settings"))

            Button {
                NSApp.terminate(nil)
            } label: {
                Image(systemName: "power")
            }
            .buttonStyle(IconButtonStyle())
            .help(L10n.tr("menu.quit"))
        }
        .padding(.horizontal, 5).padding(.vertical, 3)
        .glassSurface(cornerRadius: 12)
        .padding(.horizontal, 8).padding(.bottom, 8).padding(.top, 4)
    }
}

struct ErrorStateView: View {
    let message: String
    let source: String
    let onRetry: () -> Void
    let onSettings: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Label(L10n.tr("menu.error_title"), systemImage: "xmark.octagon.fill")
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
                Text(L10n.tr("settings.current_source", source))
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Button(L10n.tr("common.retry"), action: onRetry).buttonStyle(.borderedProminent)
                    Button(L10n.tr("menu.open_settings"), action: onSettings).buttonStyle(.bordered)
                }
                .controlSize(.regular)
                Text(L10n.tr("menu.expected_export_json"))
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
            }
            .padding(Metrics.pagePadding)
        }
    }
}
