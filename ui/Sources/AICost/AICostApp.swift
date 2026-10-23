import AppKit
import SwiftUI
import AICostCore

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var debugWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        if CommandLine.arguments.contains("--window") {
            // 开发用：把面板放进普通窗口（便于截图 / 调试），同时保留菜单栏图标。
            NSApp.setActivationPolicy(.regular)
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 380, height: 620),
                             styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
            w.title = "AICost"
            w.contentView = NSHostingView(rootView: MenuPanelView().environmentObject(ReportStore.shared))
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
struct AICostApp: App {
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

    var body: some View {
        if store.report == nil && store.error != nil {
            Image(systemName: "exclamationmark.triangle")
            if showAmount { Text("$—") }
        } else {
            Image(systemName: "dollarsign.circle")
            if showAmount, let r = store.report {
                Text(Fmt.money(r.totals.cost, currency: r.currency))
            }
        }
    }
}
