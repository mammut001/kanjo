import AppKit
import SwiftUI
import KanjoCore

enum SnapshotAppearance: String {
    case light
    case dark
}

struct SnapshotConfig {
    let outputPath: URL
    let route: String?
    let scale: Double
    let appearance: SnapshotAppearance?

    static var isSnapshotMode: Bool {
        CommandLine.arguments.contains { $0 == "--snapshot" || $0.hasPrefix("--snapshot=") }
    }

    static func parse(arguments: [String] = CommandLine.arguments) -> SnapshotConfig? {
        guard isSnapshotMode else { return nil }

        // 1. Output path (--snapshot <path> or --snapshot=<path>)
        var rawPath: String?
        if let idx = arguments.firstIndex(where: { $0 == "--snapshot" || $0.hasPrefix("--snapshot=") }) {
            let arg = arguments[idx]
            if arg == "--snapshot" {
                if idx + 1 < arguments.count {
                    let next = arguments[idx + 1]
                    if !next.hasPrefix("-") && !next.isEmpty {
                        rawPath = next
                    }
                }
            } else {
                let val = String(arg.dropFirst("--snapshot=".count)).trimmingCharacters(in: .whitespaces)
                if !val.isEmpty {
                    rawPath = val
                }
            }
        }

        guard let pathString = rawPath, !pathString.isEmpty else {
            fputs("Error: --snapshot requires an output path\n", stderr)
            exit(1)
        }

        let expanded = (pathString as NSString).expandingTildeInPath
        let outURL = URL(fileURLWithPath: expanded, relativeTo: URL(fileURLWithPath: FileManager.default.currentDirectoryPath)).standardizedFileURL

        // 2. Route (--route <route> or --route=<route>)
        var route: String?
        if let idx = arguments.firstIndex(where: { $0 == "--route" || $0.hasPrefix("--route=") }) {
            let arg = arguments[idx]
            if arg == "--route" {
                if idx + 1 < arguments.count {
                    route = arguments[idx + 1]
                }
            } else {
                route = String(arg.dropFirst("--route=".count))
            }
        }

        // 3. Scale (--snapshot-scale <number> or --snapshot-scale=<number>)
        var scale: Double = 2.0
        if let idx = arguments.firstIndex(where: { $0 == "--snapshot-scale" || $0.hasPrefix("--snapshot-scale=") }) {
            let arg = arguments[idx]
            let strVal: String?
            if arg == "--snapshot-scale" {
                strVal = idx + 1 < arguments.count ? arguments[idx + 1] : nil
            } else {
                strVal = String(arg.dropFirst("--snapshot-scale=".count))
            }

            if let strVal, let parsed = Double(strVal), parsed > 0 {
                scale = parsed
            } else {
                fputs("Error: --snapshot-scale must be a positive number\n", stderr)
                exit(1)
            }
        }

        // 4. Appearance (--snapshot-appearance light|dark or --snapshot-appearance=light|dark)
        var appearance: SnapshotAppearance?
        if let idx = arguments.firstIndex(where: { $0 == "--snapshot-appearance" || $0.hasPrefix("--snapshot-appearance=") }) {
            let arg = arguments[idx]
            let strVal: String?
            if arg == "--snapshot-appearance" {
                strVal = idx + 1 < arguments.count ? arguments[idx + 1] : nil
            } else {
                strVal = String(arg.dropFirst("--snapshot-appearance=".count))
            }

            if let strVal {
                let lower = strVal.trimmingCharacters(in: .whitespaces).lowercased()
                if let parsed = SnapshotAppearance(rawValue: lower) {
                    appearance = parsed
                } else {
                    fputs("Error: --snapshot-appearance must be 'light' or 'dark'\n", stderr)
                    exit(1)
                }
            }
        }

        return SnapshotConfig(outputPath: outURL, route: route, scale: scale, appearance: appearance)
    }
}

private final class SnapshotWindow: NSWindow {
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect {
        frameRect
    }
}

@MainActor
enum SnapshotRunner {
    static func runCLI() {
        guard let config = SnapshotConfig.parse() else {
            exit(1)
        }
        let app = NSApplication.shared
        _ = app.setActivationPolicy(.prohibited)
        if app.activationPolicy() != .prohibited {
            app.setActivationPolicy(.accessory)
        }
        Task { @MainActor in
            await run(config: config)
        }
        app.run()
    }

    static func run(config: SnapshotConfig) async {
        let rawRoute = config.route ?? "overview"
        let needsDisk = rawRoute == "disk" || rawRoute.hasPrefix("disk:")

        if needsDisk {
            DiskStore.shared.refresh()
        }

        // 等待数据加载完成，超时约 20 秒
        let timeoutSeconds: TimeInterval = 20.0
        let deadline = Date().addingTimeInterval(timeoutSeconds)

        while true {
            let storeDone = !ReportStore.shared.isLoading && (ReportStore.shared.report != nil || ReportStore.shared.error != nil)
            let diskDone = !needsDisk || (!DiskStore.shared.isLoading && (DiskStore.shared.hasReport || DiskStore.shared.error != nil))

            if storeDone && diskDone {
                break
            }

            if Date() >= deadline {
                fputs("Error: Timed out waiting for data to load (~20s)\n", stderr)
                exit(1)
            }

            try? await Task.sleep(nanoseconds: 50_000_000)
        }

        // 检查加载错误
        if ReportStore.shared.report == nil {
            let err = ReportStore.shared.error ?? "Failed to load usage report"
            fputs("Error: \(err)\n", stderr)
            exit(1)
        }

        if needsDisk && DiskStore.shared.report == nil {
            let err = DiskStore.shared.error ?? "Failed to load disk report"
            fputs("Error: \(err)\n", stderr)
            exit(1)
        }

        // 订阅行编辑等场景：确保已知订阅档位加载完成
        if rawRoute.contains("subscriptions") {
            await ReportStore.shared.loadKnownPlans()
        }

        // 给主线程状态一点微小时间稳定
        try? await Task.sleep(nanoseconds: 50_000_000)

        // 解析路由
        guard let resolved = DevRoute.resolve(rawRoute, report: ReportStore.shared.report) else {
            fputs("Error: Could not resolve route '\(rawRoute)'\n", stderr)
            exit(1)
        }

        // 滚动路由：离屏渲染时从顶部开始渲染，完整内容高度（TALL）。
        let isTall = true

        if let app = config.appearance {
            let appearanceName: NSAppearance.Name = app == .dark ? .darkAqua : .aqua
            NSApp.appearance = NSAppearance(named: appearanceName)
        }

        let panel = MenuPanelView(
            route: resolved.route,
            anchor: resolved.anchor,
            editingAgent: resolved.editingAgent,
            pendingDevRoute: nil,
            isTall: isTall
        )

        var view: AnyView = AnyView(
            panel
                .environment(\.isSnapshotMode, true)
                .environmentObject(ReportStore.shared)
                .environmentObject(DiskStore.shared)
        )

        if let app = config.appearance {
            let scheme: ColorScheme = app == .dark ? .dark : .light
            view = AnyView(
                view
                    .environment(\.colorScheme, scheme)
                    .preferredColorScheme(scheme)
            )
        }

        let standardSize = MenuPanelView.size

        let hosting = NSHostingView(rootView: view)
        if let app = config.appearance {
            let appearanceName: NSAppearance.Name = app == .dark ? .darkAqua : .aqua
            hosting.appearance = NSAppearance(named: appearanceName)
        }

        let fit = hosting.fittingSize
        let renderHeight = max(standardSize.height, ceil(fit.height))
        let renderSize = NSSize(width: standardSize.width, height: renderHeight)
        let renderRect = NSRect(origin: .zero, size: renderSize)

        let window = SnapshotWindow(
            contentRect: renderRect,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.isOpaque = false
        window.backgroundColor = .clear
        window.alphaValue = 0
        if let app = config.appearance {
            let appearanceName: NSAppearance.Name = app == .dark ? .darkAqua : .aqua
            window.appearance = NSAppearance(named: appearanceName)
        }
        window.contentView = hosting
        hosting.frame = renderRect
        hosting.layoutSubtreeIfNeeded()

        let fitAfter = hosting.fittingSize
        let finalHeight = max(renderHeight, ceil(fitAfter.height))
        if finalHeight != renderHeight {
            let finalSize = NSSize(width: standardSize.width, height: finalHeight)
            let finalRect = NSRect(origin: .zero, size: finalSize)
            window.setFrame(finalRect, display: true)
            hosting.frame = finalRect
            hosting.layoutSubtreeIfNeeded()
        }

        try? await Task.sleep(nanoseconds: 50_000_000)
        hosting.layoutSubtreeIfNeeded()

        let bounds = hosting.bounds
        guard var rep = hosting.bitmapImageRepForCachingDisplay(in: bounds) else {
            fputs("Error: Failed to create bitmapImageRepForCachingDisplay\n", stderr)
            exit(1)
        }

        let targetPixelsWide = Int(round(bounds.width * config.scale))
        let targetPixelsHigh = Int(round(bounds.height * config.scale))

        if rep.pixelsWide != targetPixelsWide || rep.pixelsHigh != targetPixelsHigh {
            if let customRep = NSBitmapImageRep(
                bitmapDataPlanes: nil,
                pixelsWide: targetPixelsWide,
                pixelsHigh: targetPixelsHigh,
                bitsPerSample: 8,
                samplesPerPixel: 4,
                hasAlpha: true,
                isPlanar: false,
                colorSpaceName: .deviceRGB,
                bytesPerRow: 0,
                bitsPerPixel: 0
            ) {
                customRep.size = bounds.size
                rep = customRep
            }
        }

        hosting.cacheDisplay(in: bounds, to: rep)

        guard let pngData = rep.representation(using: .png, properties: [:]) else {
            fputs("Error: Failed to encode image to PNG\n", stderr)
            exit(1)
        }

        do {
            try FileManager.default.createDirectory(at: config.outputPath.deletingLastPathComponent(), withIntermediateDirectories: true)
            try pngData.write(to: config.outputPath, options: .atomic)
        } catch {
            fputs("Error: Failed to write snapshot to \(config.outputPath.path): \(error.localizedDescription)\n", stderr)
            exit(1)
        }

        print(config.outputPath.path)
        exit(0)
    }
}
