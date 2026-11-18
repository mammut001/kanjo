import Foundation

public enum SettingsKeys {
    public static let appLanguage = "appLanguage"
    public static let appAppearance = "appAppearance"        // "dark" | "light" | "system"；默认 dark
    public static let sourceKind = "sourceKind"              // "file" | "cli"；默认 cli（仓库里有 cli/ 时）
    public static let filePath = "filePath"                  // 空 = 用 ui/fixtures/sample.json
    public static let cliCommand = "cliCommand"
    public static let cliWorkingDirectory = "cliWorkingDirectory"   // 空 = 仓库里的 cli/，其次 ~/.local/share/kanjo/cli、/usr/local/share/kanjo/cli
    public static let refreshMinutes = "refreshMinutes"      // 0 = 关闭自动刷新
    public static let showAmountInMenuBar = "showAmountInMenuBar"
    public static let menuBarMode = "menuBarMode"            // "cost" | "tokens"；默认 cost
    public static let hiddenProjects = "hiddenProjects"      // 换行分隔的 project id（ProjectPrefs）
    public static let pinnedProjects = "pinnedProjects"      // 同上
    public static let panelViewMode = "panelViewMode"        // "projects" | "agents"；默认 projects
    public static let timeRange = "timeRange"                // TimeRange.rawValue；默认 all
    public static let renewalNudgeDismissed = "renewalNudgeDismissed"
    public static let subscriptionOrder = "subscriptionOrder" // 逗号分隔的 agent id（SubscriptionOrder）
    public static let cloudSyncEnabled = "cloudSyncEnabled"
    public static let cloudSyncHideProjectNames = "cloudSyncHideProjectNames"
    public static let cloudSyncDeviceID = "cloudSyncDeviceID"
    public static let cloudSyncLastUploadHash = "cloudSyncLastUploadHash"
    public static let cloudSyncLastFingerprint = "cloudSyncLastFingerprint"
    public static let cloudSyncLastUploadedAt = "cloudSyncLastUploadedAt"
    public static let publishEnabled = "publishEnabled"
    public static let publishFrequency = "publishFrequency"
    public static let publishRepoPath = "publishRepoPath"
    public static let publishFilePath = "publishFilePath"
    public static let publishBranch = "publishBranch"
    public static let publishLastAttemptAt = "publishLastAttemptAt"
    public static let publishLastSuccessAt = "publishLastSuccessAt"
    public static let publishLastResult = "publishLastResult"
    public static let familyReportEnabled = "familyReportEnabled"
    public static let familyReportMode = "familyReportMode" // "join" | "manager"
    public static let familyReportURL = "familyReportURL"
    public static let familyReportMemberLabel = "familyReportMemberLabel"
    public static let familyReportLastAttemptAt = "familyReportLastAttemptAt"
    public static let familyReportLastSuccessAt = "familyReportLastSuccessAt"
    public static let familyReportLastResult = "familyReportLastResult"
    public static let familyReportMigrationDone = "familyReportMigrationDone"
}

public enum PublishFrequency: String, CaseIterable, Identifiable {
    case daily = "daily"
    case weekly = "weekly"
    case monthly = "monthly"

    public var id: String { rawValue }
    public var label: String {
        switch self {
        case .daily: return L10n.tr("settings.publish.frequency.daily")
        case .weekly: return L10n.tr("settings.publish.frequency.weekly")
        case .monthly: return L10n.tr("settings.publish.frequency.monthly")
        }
    }
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

/// 面板主视图模式：项目列表或 Agent 列表。
public enum PanelViewMode: String, CaseIterable, Identifiable {
    case projects, agents
    public var id: String { rawValue }
    public var label: String {
        switch self {
        case .projects: return L10n.tr("view_mode.projects")
        case .agents: return L10n.tr("view_mode.agents")
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

/// 面板与附属窗口外观：Dark（默认）/ Light / System。
public enum AppAppearance: String, CaseIterable, Identifiable {
    case dark = "dark"
    case light = "light"
    case system = "system"

    public static let defaultValue: AppAppearance = .dark

    public var id: String { rawValue }

    public var label: String {
        switch self {
        case .dark: return L10n.tr("settings.appearance.dark")
        case .light: return L10n.tr("settings.appearance.light")
        case .system: return L10n.tr("settings.appearance.system")
        }
    }

    public static func resolve(_ raw: String?) -> AppAppearance {
        guard let raw, let parsed = AppAppearance(rawValue: raw) else {
            return defaultValue
        }
        return parsed
    }

    /// 显式深浅偏好；`nil` 表示跟随系统外观。
    public var explicitIsDark: Bool? {
        switch self {
        case .dark: return true
        case .light: return false
        case .system: return nil
        }
    }
}
