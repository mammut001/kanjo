import AppKit
import SwiftUI
import KanjoCore

@main
enum KanjoAppLauncher {
    private static var windowPreviewDelegate: WindowPreviewAppDelegate?

    static func main() {
        if SnapshotConfig.isSnapshotMode {
            SnapshotRunner.runCLI()
        } else if CommandLine.arguments.contains("--window") {
            let app = NSApplication.shared
            let delegate = WindowPreviewAppDelegate()
            windowPreviewDelegate = delegate
            app.delegate = delegate
            app.run()
        } else {
            KanjoMenuBarApp.main()
        }
    }
}

final class WindowPreviewAppDelegate: NSObject, NSApplicationDelegate {
    private var debugWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // 开发用：把面板放进普通窗口（便于截图 / 调试）。
        // 预览模式下不创建 NSStatusItem / MenuBarExtra，避免污染用户的状态栏与偏好设置。
        NSApp.setActivationPolicy(.regular)

        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu()
        appMenuItem.submenu = appMenu
        appMenu.addItem(withTitle: "Quit Kanjo", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        NSApp.mainMenu = mainMenu

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
        let host = NSHostingView(rootView: MenuPanelView()
            .environmentObject(ReportStore.shared)
            .environmentObject(DiskStore.shared))
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
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

final class MenuBarAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // 纯菜单栏应用：不占 Dock。
        NSApp.setActivationPolicy(.accessory)
    }
}

struct KanjoMenuBarApp: App {
    @NSApplicationDelegateAdaptor(MenuBarAppDelegate.self) private var appDelegate
    @StateObject private var store = ReportStore.shared
    @StateObject private var disk = DiskStore.shared
    @AppStorage(SettingsKeys.showAmountInMenuBar, store: AppDefaults.store) private var showAmount = true

    var body: some Scene {
        MenuBarExtra {
            MenuPanelView()
                .environmentObject(store)
                .environmentObject(disk)
        } label: {
            MenuBarLabel(store: store, showAmount: showAmount)
        }
        .menuBarExtraStyle(.window)
    }
}

struct MenuBarLabel: View {
    @ObservedObject var store: ReportStore
    let showAmount: Bool
    @AppStorage(SettingsKeys.timeRange, store: AppDefaults.store) private var rangeRaw = TimeRange.all.rawValue
    @AppStorage(SettingsKeys.menuBarMode, store: AppDefaults.store) private var menuBarMode = MenuBarMode.cost.rawValue

    private var mode: MenuBarMode {
        MenuBarMode(rawValue: menuBarMode) ?? .cost
    }

    var body: some View {
        if store.report == nil && store.error != nil {
            Image(systemName: "exclamationmark.triangle")
            if showAmount { Text(mode == .tokens ? "—" : "$—").monospacedDigit() }
        } else if showAmount, let r = store.report {
            if mode == .tokens {
                Image(systemName: "circle.hexagongrid")
                Text(tokensText(r)).monospacedDigit()
            } else {
                Text(amount(r)).monospacedDigit()
            }
        } else {
            Image(systemName: mode == .tokens ? "circle.hexagongrid" : "dollarsign.circle")
        }
    }

    /// 当前范围过滤后的总额（和总览 hero 同一个数）；All 下就是报告总额，不加后缀。
    /// Since reset / Billing cycle 在报告没有对应数据时按 All 处理（RangeContext）。
    private func amount(_ r: UsageReport) -> String {
        let ctx = RangeContext(report: r, raw: rangeRaw)
        let cost = ctx.isAll ? r.totals.cost : ctx.filtered().cost
        return MenuBarText.make(cost: cost, currency: r.currency, range: ctx.range)
    }

    /// 当前范围过滤后的总 token 数（和总览 hero 同一个数）；All 下就是报告总 token 数。
    private func tokensText(_ r: UsageReport) -> String {
        let ctx = RangeContext(report: r, raw: rangeRaw)
        let tokens = ctx.isAll ? r.totals.tokens.total : ctx.filtered().tokens
        return MenuBarText.make(tokens: tokens, range: ctx.range)
    }
}
