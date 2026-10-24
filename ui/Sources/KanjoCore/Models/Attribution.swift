import Foundation

/// attribution 取值的解释（CONTRACT.md 第 5 节 + ATTRIBUTION.md 第 4 节），用作 tooltip。
public enum AttributionInfo {
    public static let allKnown = ["dominant", "split", "cwd", "scratchpad", "override", "none", "excluded"]

    public static func explanation(_ value: String, threshold: Double) -> String {
        let pct = "\(Int((threshold * 100).rounded()))%"
        switch value {
        case "dominant":
            return "Dominant: ≥\(pct) of this session's file-operation signals pointed at this project, so the whole session is counted here."
        case "split":
            return "Split: no project reached \(pct) of file-operation signals, so the cost is divided between projects in proportion to their signals. Share shows this project's part."
        case "cwd":
            return "cwd: the session touched no project files; it is attributed by its working directory."
        case "scratchpad":
            return "Scratchpad: the session touched no project files; it is attributed by the project path encoded in its scratchpad directory."
        case "override":
            return "Override: a path-prefix rule in your attribution config forces this session onto this project."
        case "none":
            return "Unattributed: no file signals, and neither cwd nor scratchpad maps to a project."
        case "excluded":
            return "Excluded: the session matched an exclude path in your config and is not counted toward any project."
        default:
            return "Unknown attribution value \"\(value)\" (not in the data contract)."
        }
    }
}
