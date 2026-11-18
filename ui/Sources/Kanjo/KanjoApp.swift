import AppKit
import os
import SwiftUI
import KanjoCore

@main
enum KanjoAppLauncher {
    private static var windowPreviewDelegate: WindowPreviewAppDelegate?

    static func main() {
        FamilyReportMigration.migrate()
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
        let effect = PreviewBackdropView()
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
        AppearanceController.applyStored()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

final class MenuBarAppDelegate: NSObject, NSApplicationDelegate {
    private static let logger = Logger(subsystem: "com.lanshuagent.kanjo", category: "cli-sync")

    func applicationDidFinishLaunching(_ notification: Notification) {
        // 纯菜单栏应用：不占 Dock。
        NSApp.setActivationPolicy(.accessory)
        // 应用内更新要在启动时就跑起来，否则第一次定时检查得等用户打开面板才发生。
        // 不是打包的 .app（或缺 SU 键）时 UpdateController 自己就是空转的。
        _ = UpdateController.shared
        AppearanceController.applyStored()
        syncTerminalCLIIfNeeded()
    }

    private func syncTerminalCLIIfNeeded() {
        guard !SnapshotConfig.isSnapshotMode,
              !CommandLine.arguments.contains(AppDefaults.windowArgument),
              AppDefaults.suiteName() == nil,
              let bundledCLI = DefaultPaths.bundledCLIDirectory else {
            return
        }

        let installDir = DefaultPaths.installedCLIDirectories()[0]
        let launcher = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".local/bin/kanjo")

        DispatchQueue.global(qos: .utility).async {
            let result = TerminalCLISync.sync(
                bundledCLI: bundledCLI,
                installDir: installDir,
                launcher: launcher
            )
            switch result {
            case .updated(let from, let to):
                Self.logger.info("terminal CLI updated: \(from, privacy: .public) -> \(to, privacy: .public)")
            case .upToDate:
                Self.logger.info("terminal CLI up to date")
            case .notInstalled:
                Self.logger.info("terminal CLI not installed")
            case .notOurs:
                Self.logger.info("terminal CLI skipped: launcher not managed by install.sh")
            case .failed(let message):
                Self.logger.error("terminal CLI sync failed: \(message, privacy: .public)")
            }
        }
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

private final class PreviewBackdropView: NSVisualEffectView {}

@MainActor
enum AppearanceController {
    static func nsAppearance(for appearance: AppAppearance) -> NSAppearance? {
        switch appearance.explicitIsDark {
        case true?: return NSAppearance(named: .darkAqua)
        case false?: return NSAppearance(named: .aqua)
        case nil: return nil
        }
    }

    static func colorScheme(for appearance: AppAppearance) -> ColorScheme? {
        switch appearance.explicitIsDark {
        case true?: return .dark
        case false?: return .light
        case nil: return nil
        }
    }

    static func apply(_ appearance: AppAppearance, to targetWindow: NSWindow? = nil) {
        let nsApp = nsAppearance(for: appearance)
        if let targetWindow, !isStatusBarWindow(targetWindow) {
            targetWindow.appearance = nsApp
            updatePreviewBackdrop(for: targetWindow, appearance: appearance)
        }
        for window in NSApp.windows where !isStatusBarWindow(window) {
            window.appearance = nsApp
            updatePreviewBackdrop(for: window, appearance: appearance)
        }
    }

    static func applyStored(defaults: UserDefaults = AppDefaults.store) {
        apply(AppAppearance.resolve(defaults.string(forKey: SettingsKeys.appAppearance)))
    }

    private static func updatePreviewBackdrop(for window: NSWindow, appearance: AppAppearance) {
        guard let effect = window.contentView as? PreviewBackdropView else { return }
        let resolved = nsAppearance(for: appearance) ?? NSApp.effectiveAppearance
        let isDark = resolved.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        if isDark {
            window.backgroundColor = NSColor(srgbRed: 0.135, green: 0.135, blue: 0.135, alpha: 0.97)
            effect.material = .windowBackground
            effect.blendingMode = .withinWindow
            effect.state = .inactive
        } else {
            window.backgroundColor = .clear
            effect.material = .popover
            effect.blendingMode = .behindWindow
            effect.state = .active
        }
    }

    private static func isStatusBarWindow(_ window: NSWindow) -> Bool {
        String(describing: type(of: window)).contains("StatusBar")
    }
}

/// 将 `AppAppearance` 实时同步到宿主 `NSPanel` / `NSWindow`（包括 MenuBarExtra 窗口及附属窗口），
/// 不影响状态栏图标所在的 `NSStatusBarWindow`。
struct WindowAppearanceBridge: NSViewRepresentable {
    let appearance: AppAppearance

    func makeNSView(context: Context) -> BridgeView {
        let view = BridgeView()
        view.appearanceSetting = appearance
        return view
    }

    func updateNSView(_ nsView: BridgeView, context: Context) {
        nsView.appearanceSetting = appearance
        AppearanceController.apply(appearance, to: nsView.window)
    }

    final class BridgeView: NSView {
        var appearanceSetting: AppAppearance = .defaultValue

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if let window {
                Task { @MainActor [appearanceSetting] in
                    AppearanceController.apply(appearanceSetting, to: window)
                }
            }
        }
    }
}
