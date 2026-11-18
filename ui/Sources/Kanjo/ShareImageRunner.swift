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
        // Parse args
        let args = CommandLine.arguments
        guard let idx = args.firstIndex(of: "--share-image"), idx + 1 < args.count else { return }
        let outputPath = URL(fileURLWithPath: args[idx + 1])
        
        var agentId: String? = nil
        if let aidx = args.firstIndex(of: "--share-agent"), aidx + 1 < args.count {
            agentId = args[aidx + 1]
        }
        
        let config = ShareConfig(outputPath: outputPath, agentId: agentId)
        
        // Load data
        let report = ReportStore.shared.report! // Should be loaded by now if --data was passed
        let rangeSpec = RangeEngine.defaultSpec(report: report) // Simplified, maybe need to parse range if passed
        let summary = ShareSummary.build(report: report, rangeSpec: rangeSpec)
        
        let view = ShareImage(summary: summary, agentId: config.agentId)
            .preferredColorScheme(.dark)
        
        let renderer = ImageRenderer(content: view)
        renderer.scale = 2.0
        
        if let nsImage = renderer.nsImage {
            if let tiff = nsImage.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff) {
                if let png = bitmap.representation(using: .png, properties: [:]) {
                    try? png.write(to: config.outputPath)
                    print("Rendered to \(config.outputPath.path)")
                    exit(0)
                }
            }
        }
        
        fputs("Error: Failed to render image\n", stderr)
        exit(1)
    }
}
