import Foundation

/// attribution 取值的解释（CONTRACT.md 第 5 节 + ATTRIBUTION.md 第 4 节），用作 tooltip。
public enum AttributionInfo {
    public static let allKnown = ["dominant", "split", "cwd", "scratchpad", "override", "none", "excluded"]

    public static func explanation(_ value: String, threshold: Double) -> String {
        let pct = "\(Int((threshold * 100).rounded()))%"
        switch value {
        case "dominant":
            return L10n.tr("attribution.dominant", pct)
        case "split":
            return L10n.tr("attribution.split", pct)
        case "cwd":
            return L10n.tr("attribution.cwd")
        case "scratchpad":
            return L10n.tr("attribution.scratchpad")
        case "override":
            return L10n.tr("attribution.override")
        case "none":
            return L10n.tr("attribution.none")
        case "excluded":
            return L10n.tr("attribution.excluded")
        default:
            return L10n.tr("attribution.unknown", value)
        }
    }
}
