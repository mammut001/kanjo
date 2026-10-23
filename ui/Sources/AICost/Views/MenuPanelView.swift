import AppKit
import SwiftUI
import AICostCore

enum Route: Equatable {
    case overview
    case project(String)
    case bucket(BucketKind)
    case settings
}

enum BucketKind: String {
    case unattributed, excluded
}

/// 开发开关 `--route <value>`：启动后直接打开某一页，便于截图。
/// 取值：`overview`、`overview-bottom`（总览滚到底部）、`project:<index>`（按 cost 降序的第 index 个，从 0 开始）、
/// `bucket:unattributed` / `bucket:excluded`、`settings`。
enum DevRoute {
    static let requested: String? = {
        let args = CommandLine.arguments
        guard let i = args.firstIndex(of: "--route"), i + 1 < args.count else { return nil }
        return args[i + 1]
    }()

    /// 需要数据才能解析的取值在 report 为 nil 时返回 nil（等数据到了再解析）。
    static func resolve(_ raw: String, report: UsageReport?) -> (route: Route, anchor: String?)? {
        switch raw {
        case "settings": return (.settings, nil)
        case "overview": return (.overview, nil)
        case "overview-bottom": return report == nil ? nil : (.overview, OverviewView.bottomAnchor)
        default: break
        }
        guard let r = report else { return nil }
        if raw.hasPrefix("project:"), let i = Int(raw.dropFirst("project:".count)) {
            let sorted = r.projects.sorted { $0.cost > $1.cost }
            guard sorted.indices.contains(i) else { return (.overview, nil) }
            return (.project(sorted[i].id), nil)
        }
        if raw.hasPrefix("bucket:"), let k = BucketKind(rawValue: String(raw.dropFirst("bucket:".count))) {
            return (.bucket(k), nil)
        }
        return (.overview, nil)
    }
}

struct MenuPanelView: View {
    @EnvironmentObject var store: ReportStore
    @State private var route: Route = .overview
    @State private var pendingDevRoute = DevRoute.requested
    @State private var overviewAnchor: String?

    var body: some View {
        VStack(spacing: 0) {
            banners
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            footer
        }
        .frame(width: 380, height: 620)
        .onReceive(store.$report) { r in
            guard let raw = pendingDevRoute, let resolved = DevRoute.resolve(raw, report: r) else { return }
            pendingDevRoute = nil
            route = resolved.route
            overviewAnchor = resolved.anchor
        }
    }

    // 只在出问题时出现：schema 版本过新（警告）、刷新失败但还有旧数据（错误）。
    @ViewBuilder private var banners: some View {
        let schemaWarning = store.report?.isNewerSchema == true
        let refreshFailed = store.report != nil && store.error != nil
        if schemaWarning || refreshFailed {
            VStack(spacing: 6) {
                if let r = store.report, r.isNewerSchema {
                    StatusBlock(kind: .warn, icon: "exclamationmark.triangle.fill") {
                        Text("This data uses schema_version \(r.schemaVersion); this app understands version \(supportedSchemaVersion). Rendering anyway — some fields may be missing or misread.")
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                if store.report != nil, let err = store.error {
                    StatusBlock(kind: .bad, icon: "xmark.octagon.fill") {
                        Text("Last refresh failed — showing previous data.").fontWeight(.semibold)
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
            SettingsView(onBack: {
                route = .overview
                store.applySettings()
            })
        default:
            if let r = store.report {
                switch route {
                case .project(let id):
                    if let p = r.projects.first(where: { $0.id == id }) {
                        ProjectDetailView(project: p, report: r, onBack: { route = .overview })
                    } else {
                        missing("Project no longer in the data.")
                    }
                case .bucket(let kind):
                    BucketDetailView(kind: kind, report: r, onBack: { route = .overview })
                default:
                    OverviewView(report: r, scrollAnchor: overviewAnchor, onSelect: { route = $0 })
                }
            } else if let err = store.error {
                ErrorStateView(message: err, source: store.sourceDescription,
                               onRetry: { store.refresh() }, onSettings: { route = .settings })
            } else {
                VStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Loading…").font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func missing(_ text: String) -> some View {
        VStack(spacing: 8) {
            Text(text).font(.system(size: 12)).foregroundStyle(.secondary)
            BackButton(title: "Back to overview") { route = .overview }
        }
    }

    // 底栏：一条玻璃条，里面是无底的图标按钮。
    private var footer: some View {
        HStack(spacing: 2) {
            Button {
                store.refresh()
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(IconButtonStyle())
            .help("Refresh now")
            .disabled(store.isLoading)

            Group {
                if store.isLoading {
                    Text("Refreshing…")
                } else if let t = store.lastRefresh {
                    Text("Updated \(ShortDate.clock(t))")
                } else {
                    Text("Not refreshed yet")
                }
            }
            .font(.system(size: 11).monospacedDigit())
            .foregroundStyle(.secondary)
            .help(store.sourceDescription)

            Spacer()

            Button {
                route = route == .settings ? .overview : .settings
                if route == .overview { store.applySettings() }
            } label: {
                Image(systemName: "gearshape")
            }
            .buttonStyle(IconButtonStyle())
            .help("Settings")

            Button {
                NSApp.terminate(nil)
            } label: {
                Image(systemName: "power")
            }
            .buttonStyle(IconButtonStyle())
            .help("Quit AICost")
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
                Label("Could not load usage data", systemImage: "xmark.octagon.fill")
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
                Text("Source — \(source)")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Button("Retry", action: onRetry).buttonStyle(.borderedProminent)
                    Button("Open Settings", action: onSettings).buttonStyle(.bordered)
                }
                .controlSize(.regular)
                Text("Expected a JSON file produced by `aicost export` (see CONTRACT.md).")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
            }
            .padding(Metrics.pagePadding)
        }
    }
}
