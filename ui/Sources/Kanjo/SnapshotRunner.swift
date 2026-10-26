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

@MainActor
enum SnapshotRunner {
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

        // 滚动路由：ImageRenderer 不会渲染 ScrollView 偏移量，
        // 因此截图模式将面板内容渲染为不滚动但完整高度（TALL）。
        let isScrolled = resolved.anchor != nil

        if let app = config.appearance {
            NSApp.appearance = NSAppearance(named: app == .dark ? .darkAqua : .aqua)
        }

        let panel = MenuPanelView(
            route: resolved.route,
            anchor: resolved.anchor,
            editingAgent: resolved.editingAgent,
            pendingDevRoute: nil,
            isTall: isScrolled
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

        let renderer = ImageRenderer(content: view)
        renderer.scale = config.scale

        guard let cgImage = renderer.cgImage else {
            fputs("Error: ImageRenderer failed to produce an image\n", stderr)
            exit(1)
        }

        let rep = NSBitmapImageRep(cgImage: cgImage)
        rep.size = NSSize(width: Double(cgImage.width) / config.scale, height: Double(cgImage.height) / config.scale)

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
