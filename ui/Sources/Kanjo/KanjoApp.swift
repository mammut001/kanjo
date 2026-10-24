import AppKit
import SwiftUI
import KanjoCore

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var debugWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        if CommandLine.arguments.contains("--window") {
            // 开发用：把面板放进普通窗口（便于截图 / 调试），同时保留菜单栏图标。
            NSApp.setActivationPolicy(.regular)
            // 窗口本身透明，底下垫一层 popover 材质（behind-window），和菜单栏弹出面板一样能透出桌面，
            // 截图里能看到面板的玻璃效果。只影响这个调试窗口。
            let size = MenuPanelView.size
            let w = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                             styleMask: [.titled, .closable, .miniaturizable, .fullSizeContentView],
                             backing: .buffered, defer: false)
            w.title = "Kanjo"
            w.isOpaque = false
            w.backgroundColor = .clear
            w.titlebarAppearsTransparent = true
            let effect = NSVisualEffectView()
            effect.material = .popover
            effect.blendingMode = .behindWindow
            effect.state = .active
            let host = NSHostingView(rootView: MenuPanelView().environmentObject(ReportStore.shared))
            host.translatesAutoresizingMaskIntoConstraints = false
            effect.addSubview(host)
            w.contentView = effect
            // 面板放在标题栏下面（标题栏透明，材质铺满整个窗口）。
            let titlebar = w.frame.height - w.contentLayoutRect.height
            NSLayoutConstraint.activate([
                host.leadingAnchor.constraint(equalTo: effect.leadingAnchor),
                host.trailingAnchor.constraint(equalTo: effect.trailingAnchor),
                host.bottomAnchor.constraint(equalTo: effect.bottomAnchor),
                host.topAnchor.constraint(equalTo: effect.topAnchor, constant: titlebar),
            ])
            w.setContentSize(NSSize(width: size.width, height: size.height + titlebar))
            w.center()
            w.makeKeyAndOrderFront(nil)
            debugWindow = w
            NSApp.activate(ignoringOtherApps: true)
        } else {
            // 纯菜单栏应用：不占 Dock。
            NSApp.setActivationPolicy(.accessory)
        }
    }
}

@main
struct KanjoApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var store = ReportStore.shared
    @AppStorage(SettingsKeys.showAmountInMenuBar) private var showAmount = true

    var body: some Scene {
        MenuBarExtra {
            MenuPanelView()
                .environmentObject(store)
        } label: {
            MenuBarLabel(store: store, showAmount: showAmount)
        }
        .menuBarExtraStyle(.window)
    }
}

struct MenuBarLabel: View {
    @ObservedObject var store: ReportStore
    let showAmount: Bool
    @AppStorage(SettingsKeys.timeRange) private var rangeRaw = TimeRange.all.rawValue

    var body: some View {
        if store.report == nil && store.error != nil {
            Image(systemName: "exclamationmark.triangle")
            if showAmount { Text("$—") }
        } else {
            Image(systemName: "dollarsign.circle")
            if showAmount, let r = store.report {
                Text(amount(r))
            }
        }
    }

    /// 当前范围过滤后的总额（和总览 hero 同一个数）；All 下就是报告总额，不加前缀。
    /// 报告没有 quota_windows 时 Since reset 按 All 处理（RangeContext）。
    private func amount(_ r: UsageReport) -> String {
        let ctx = RangeContext(report: r, raw: rangeRaw)
        guard let prefix = ctx.range.menuBarPrefix else {
            return Fmt.money(r.totals.cost, currency: r.currency)
        }
        return "\(prefix) \(Fmt.money(ctx.filtered().cost, currency: r.currency))"
    }
}
