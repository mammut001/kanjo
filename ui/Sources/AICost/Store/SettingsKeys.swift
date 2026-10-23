import Foundation

enum SettingsKeys {
    static let sourceKind = "sourceKind"              // "file" | "cli"；默认 cli（仓库里有 cli/ 时）
    static let filePath = "filePath"                  // 空 = 用 ui/fixtures/sample.json
    static let cliCommand = "cliCommand"
    static let cliWorkingDirectory = "cliWorkingDirectory"   // 空 = 仓库里的 cli/
    static let refreshMinutes = "refreshMinutes"      // 0 = 关闭自动刷新
    static let showAmountInMenuBar = "showAmountInMenuBar"
}

enum SourceKind: String, CaseIterable, Identifiable {
    case file, cli
    var id: String { rawValue }
    var label: String { self == .file ? "JSON file" : "CLI command" }
}
