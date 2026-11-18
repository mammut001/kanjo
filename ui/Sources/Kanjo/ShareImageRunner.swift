import AppKit
import SwiftUI
import KanjoCore

struct ShareConfig {
    let outputPath: URL
    let agentId: String?
}

@MainActor
enum ShareImageRunner {
    static func runCLI() {
        _ = NSApplication.shared
        
        // Parse args
        let args = CommandLine.arguments
        guard let idx = args.firstIndex(of: "--share-image"), idx + 1 < args.count else { return }
        let outputPath = URL(fileURLWithPath: args[idx + 1])
        
        var agentId: String? = nil
        if let aidx = args.firstIndex(of: "--share-agent"), aidx + 1 < args.count {
            agentId = aidx + 1 < args.count ? args[aidx + 1] : nil
        }
        
        guard let didx = args.firstIndex(of: "--data"), didx + 1 < args.count else {
            fputs("Error: --data <file> required\n", stderr)
            exit(1)
        }
        let dataPath = args[didx + 1]
        
        // Load data
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: dataPath)),
              let report = try? JSONDecoder().decode(UsageReport.self, from: data) else {
            fputs("Error: Failed to load data\n", stderr)
            exit(1)
        }
        
        // Use preview defaults
        let store = AppDefaults.resolveStore(arguments: args + ["--snapshot"])
        let rangeRaw = args.firstIndex(of: "--share-range").flatMap { i in i + 1 < args.count ? args[i+1] : nil } ?? store.string(forKey: SettingsKeys.timeRange) ?? "all"
        
        let summary = ShareSummary.build(report: report, rangeRaw: rangeRaw)
        
        if let agentId = agentId {
            if !summary.agentRows.contains(where: { $0.agent == agentId }) {
                let ids = summary.agentRows.map(\.agent).joined(separator: ", ")
                fputs("Error: no agent '\(agentId)'; available: \(ids)\n", stderr)
                exit(1)
            }
        }
        
        let view = ShareImage(summary: summary, agentId: agentId)
            .preferredColorScheme(.dark)
            .environment(\.colorScheme, .dark)
            .environment(\.locale, Locale(identifier: store.string(forKey: SettingsKeys.appLanguage) ?? "en"))
        
        let renderer = ImageRenderer(content: view)
        renderer.scale = 2.0
        
        if let nsImage = renderer.nsImage {
            if let tiff = nsImage.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff) {
                if let png = bitmap.representation(using: .png, properties: [:]) {
                    try? png.write(to: outputPath)
                    print("Rendered to \(outputPath.path)")
                    exit(0)
                }
            }
        }
        
        fputs("Error: Failed to render image\n", stderr)
        exit(1)
    }
}
