import Foundation

public enum SettingsKeys {
    public static let appLanguage = "appLanguage"
    public static let sourceKind = "sourceKind"              // "file" | "cli"；默认 cli（仓库里有 cli/ 时）
    public static let filePath = "filePath"                  // 空 = 用 ui/fixtures/sample.json
    public static let cliCommand = "cliCommand"
    public static let cliWorkingDirectory = "cliWorkingDirectory"   // 空 = 仓库里的 cli/，其次 ~/.local/share/kanjo/cli、/usr/local/share/kanjo/cli
    public static let refreshMinutes = "refreshMinutes"      // 0 = 关闭自动刷新
    public static let showAmountInMenuBar = "showAmountInMenuBar"
    public static let menuBarMode = "menuBarMode"            // "cost" | "tokens"；默认 cost
    public static let hiddenProjects = "hiddenProjects"      // 换行分隔的 project id（ProjectPrefs）
    public static let pinnedProjects = "pinnedProjects"      // 同上
    public static let timeRange = "timeRange"                // TimeRange.rawValue；默认 all
    public static let renewalNudgeDismissed = "renewalNudgeDismissed"
    public static let subscriptionOrder = "subscriptionOrder" // 逗号分隔的 agent id（SubscriptionOrder）
}

public enum SourceKind: String, CaseIterable, Identifiable {
    case file, cli
    public var id: String { rawValue }
    public var label: String { self == .file ? L10n.tr("settings.source.file") : L10n.tr("settings.source.cli") }
}

public enum MenuBarMode: String, CaseIterable, Identifiable {
    case cost, tokens
    public var id: String { rawValue }
    public var label: String {
        switch self {
        case .cost: return L10n.tr("settings.menubar.cost")
        case .tokens: return L10n.tr("settings.menubar.tokens")
        }
    }
}

public enum AppLanguage: String, CaseIterable, Identifiable {
    case system = "system"
    case en = "en"
    case zhHans = "zh-Hans"
    case fr = "fr"

    public var id: String { rawValue }

    /// 在语言切换器中显示的名字（各语言使用其母语名称）。
    public var displayName: String {
        switch self {
        case .system:
            return L10n.tr("settings.language.system")
        case .en:
            return "English"
        case .zhHans:
            return "简体中文"
        case .fr:
            return "Français"
        }
    }
}
