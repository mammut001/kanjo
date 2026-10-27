import Foundation

public enum SyncFingerprint {
    public static func make(for report: UsageReport) -> String {
        var parts: [String] = [
            "cost:\(Int((report.totals.cost * 100).rounded()))",
            "tokens:\(report.totals.tokens.total)",
            "sessions:\(report.totals.sessions)",
        ]

        let windows = report.quotaWindows ?? [:]
        for agent in windows.keys.sorted() {
            guard let window = windows[agent] else { continue }
            parts.append("\(agent).weekly:\(percent(window.weeklyUsedPercent))")
            parts.append("\(agent).five:\(percent(window.fiveHourUsedPercent))")
            let extras = (window.extraWindows ?? []).sorted { $0.id < $1.id }
            for extra in extras {
                parts.append("\(agent).\(extra.id):\(percent(extra.usedPercent))")
            }
        }

        return parts.joined(separator: "|")
    }

    private static func percent(_ value: Double?) -> String {
        guard let value else { return "-" }
        return String(Int(value.rounded()))
    }
}
