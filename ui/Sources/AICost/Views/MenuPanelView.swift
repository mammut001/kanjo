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

struct MenuPanelView: View {
    @EnvironmentObject var store: ReportStore
    @State private var route: Route = .overview

    var body: some View {
        VStack(spacing: 0) {
            header
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            footer
        }
        .frame(width: 380, height: 620)
        .background(PanelBackdrop())
    }

    // 顶部：cost_note 原文（不可隐藏）+ schema 警告 + 刷新错误。都是玻璃小条，放在同一个容器里。
    @ViewBuilder private var header: some View {
        if store.report != nil {
            GlassGroup(spacing: 6) {
                VStack(spacing: 6) {
                    if let r = store.report {
                        HStack(spacing: 6) {
                            Image(systemName: "info.circle").font(.system(size: 10.5, weight: .semibold))
                            Text(r.costNote)
                                .font(.system(size: 10.5, weight: .medium))
                                .multilineTextAlignment(.leading)
                                .fixedSize(horizontal: false, vertical: true)
                                .textSelection(.enabled)
                        }
                        .foregroundStyle(.primary.opacity(0.85))
                        .frame(maxWidth: .infinity)
                        .padding(.horizontal, 12).padding(.vertical, 6)
                        .glassSurface(cornerRadius: 12, fallbackFill: Color.primary.opacity(0.04))
                        if r.isNewerSchema {
                            banner(icon: "exclamationmark.triangle.fill",
                                   text: "This data uses schema_version \(r.schemaVersion); this app understands version \(supportedSchemaVersion). Rendering anyway — some fields may be missing or misread.",
                                   tint: AgentPalette.warnTint, fill: AgentPalette.warnFill, ink: AgentPalette.warnInk)
                        }
                    }
                    if let err = store.error {
                        banner(icon: "xmark.octagon.fill",
                               text: "Last refresh failed — showing previous data.\n\(err)",
                               tint: AgentPalette.badTint, fill: AgentPalette.badFill, ink: AgentPalette.bad)
                    }
                }
            }
            .padding(.horizontal, 10).padding(.top, 10).padding(.bottom, 2)
        } else {
            // 没有数据时（加载中 / 错误卡片）也留一条顶边：macOS 26+ 上 ScrollView 紧贴面板顶边时，
            // 里面玻璃面的内容（文字、按钮标题）实测整块不绘制，只剩空玻璃。隔开几个点即可。
            Color.clear.frame(height: 6)
        }
    }

    private func banner(icon: String, text: String, tint: Color, fill: Color, ink: Color) -> some View {
        HStack(alignment: .top, spacing: 6) {
            Image(systemName: icon)
            Text(text).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            Spacer(minLength: 0)
        }
        .font(.system(size: 10.5, weight: .medium))
        .foregroundStyle(ink)
        .padding(.horizontal, 12).padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassSurface(cornerRadius: 12, tint: tint, fallbackFill: fill)
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
                    OverviewView(report: r, onSelect: { route = $0 })
                }
            } else if let err = store.error {
                ErrorStateView(message: err, source: store.sourceDescription,
                               onRetry: { store.refresh() }, onSettings: { route = .settings })
            } else {
                VStack(spacing: 8) {
                    ProgressView()
                    Text("Loading…").font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func missing(_ text: String) -> some View {
        VStack(spacing: 8) {
            Text(text).foregroundStyle(.secondary)
            Button("Back to overview") { route = .overview }.glassButtonStyle()
        }
    }

    private var footer: some View {
        GlassGroup(spacing: 8) {
            HStack(spacing: 8) {
                Button {
                    store.refresh()
                } label: {
                    Image(systemName: "arrow.clockwise").frame(width: 16, height: 16)
                }
                .glassButtonStyle()
                .help("Refresh now")
                .disabled(store.isLoading)

                Group {
                    if store.isLoading {
                        ProgressView().controlSize(.small).scaleEffect(0.7)
                        Text("Refreshing…")
                    } else if let t = store.lastRefresh {
                        Text("Updated \(Fmt.clock(t))")
                    } else {
                        Text("Not refreshed yet")
                    }
                }
                .font(.system(size: 10.5).monospacedDigit())
                .foregroundStyle(.secondary)
                .help(store.sourceDescription)

                Spacer()
                // 设置 + 退出靠得很近（2pt < 容器 spacing 8）：在 macOS 26 上两枚玻璃按钮融合成一个胶囊组。
                HStack(spacing: 2) {
                Button {
                    route = route == .settings ? .overview : .settings
                    if route == .overview { store.applySettings() }
                } label: {
                    Image(systemName: "gearshape").frame(width: 16, height: 16)
                }
                .glassButtonStyle()
                .help("Settings")
                Button {
                    NSApp.terminate(nil)
                } label: {
                    Image(systemName: "power").frame(width: 16, height: 16)
                }
                .glassButtonStyle()
                .help("Quit AICost")
                }
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 8)
    }
}

/// 面板最底层：一层很淡的强调色渐变，给上面的玻璃一点可折射的内容，同时不影响文字对比度。
/// MenuBarExtra 窗口本身已有系统材质，这里不再铺不透明底色。
struct PanelBackdrop: View {
    @Environment(\.colorScheme) private var scheme
    var body: some View {
        LinearGradient(colors: [Color.accentColor.opacity(scheme == .dark ? 0.16 : 0.10),
                                Color.accentColor.opacity(0.0)],
                       startPoint: .top, endPoint: .bottom)
            .ignoresSafeArea()
            .allowsHitTesting(false)
    }
}

struct ErrorStateView: View {
    let message: String
    let source: String
    let onRetry: () -> Void
    let onSettings: () -> Void

    var body: some View {
        ScrollView {
            // 不给整张卡再套一层玻璃（里面已有染红的玻璃消息框和玻璃按钮，避免玻璃叠玻璃），
            // 它们放进同一个 GlassEffectContainer。
            GlassGroup(spacing: 6) {
                VStack(alignment: .leading, spacing: 10) {
                    Label("Could not load usage data", systemImage: "xmark.octagon.fill")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(AgentPalette.bad)
                    Text(message)
                        .font(.system(size: 11, design: .monospaced))
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .glassSurface(cornerRadius: 10, tint: AgentPalette.badTint, fallbackFill: AgentPalette.badFill)
                    Text("Source — \(source)")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack {
                        Button("Retry", action: onRetry).glassButtonStyle(prominent: true)
                        Button("Open Settings", action: onSettings).glassButtonStyle()
                    }
                    Text("Expected a JSON file produced by `aicost export` (see CONTRACT.md).")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                .padding(14)
            }
        }
    }
}

