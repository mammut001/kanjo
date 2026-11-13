import Foundation

/// 应用内更新（Sparkle）的判断与文案：纯逻辑，不依赖 Sparkle，iOS 也能编译。
public enum UpdateGate {
    /// `ui/Resources/sparkle-public-ed-key.txt` 里的占位符；打包脚本见到它就不写 SU 键。
    public static let placeholderPublicKey = "REPLACE_WITH_KANJO_SPARKLE_PUBLIC_KEY"

    /// 发布源：GitHub Releases 上跟 zip 一起上传的 appcast.xml（"latest" 指向最新一次发布）。
    public static let feedURL = "https://github.com/mammut001/kanjo/releases/latest/download/appcast.xml"

    /// 应用信息里跟更新有关的键。
    public static let feedKey = "SUFeedURL"
    public static let publicKeyKey = "SUPublicEDKey"

    /// 开发模式下的启动参数：这些情况下不启动更新（swift run / 截图 / 预览窗口 / 指定数据文件）。
    static let disablingArguments = ["--snapshot", "--window", "--data"]

    /// 是否从打包好的 .app 里运行。
    public static func isPackagedApp(bundleURL: URL?) -> Bool {
        guard let bundleURL else { return false }
        return bundleURL.pathExtension.lowercased() == "app"
    }

    /// 启动参数里是否带开发模式开关（`--snapshot [path]`、`--data=…` 等）。
    public static func hasDisablingArgument(
        _ arguments: [String],
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        if arguments.contains(where: { arg in
            disablingArguments.contains { arg == $0 || arg.hasPrefix("\($0)=") }
        }) {
            return true
        }
        // KANJO_DATA 等价于 --data：开发时指向任意 JSON，不走真实数据。
        return !(environment["KANJO_DATA"] ?? "").trimmingCharacters(in: .whitespaces).isEmpty
    }

    /// Info.plist 里的发布源是否可用：https 且带主机名。
    public static func isUsableFeedURL(_ raw: String?) -> Bool {
        guard let trimmed = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty,
              let url = URL(string: trimmed),
              url.scheme?.lowercased() == "https",
              let host = url.host, !host.isEmpty else { return false }
        return true
    }

    /// Info.plist 里的公钥是否可用：非空，且不是仓库里的占位符。
    public static func isUsablePublicKey(_ raw: String?) -> Bool {
        guard let key = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !key.isEmpty else { return false }
        return key != placeholderPublicKey
    }

    /// 是否应该启动 Sparkle。
    ///
    /// 只有同时满足才启动：从 .app 里运行、不是开发模式、Info.plist 里既有可用的
    /// SUFeedURL 又有真正的 SUPublicEDKey。否则界面上所有更新相关的东西都不出现。
    public static func shouldStartUpdater(
        bundleURL: URL?,
        infoDictionary: [String: Any]?,
        arguments: [String],
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        guard isPackagedApp(bundleURL: bundleURL) else { return false }
        guard !hasDisablingArgument(arguments, environment: environment) else { return false }
        guard isUsableFeedURL(infoDictionary?[feedKey] as? String) else { return false }
        return isUsablePublicKey(infoDictionary?[publicKeyKey] as? String)
    }

    /// 用当前进程的环境判断（app 里调用）。
    public static func shouldStartUpdater(
        bundle: Bundle = .main,
        arguments: [String] = CommandLine.arguments,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        shouldStartUpdater(
            bundleURL: bundle.bundleURL,
            infoDictionary: bundle.infoDictionary,
            arguments: arguments,
            environment: environment
        )
    }
}

/// 更新相关文案的纯格式化。日期 / 间隔的措辞走 L10n，方便三种语言。
public enum UpdateFormatting {
    /// "0.5.2 (502)"；build 为空或与版本相同时只显示版本号；版本为空时显示 "—"。
    public static func versionString(marketing: String?, build: String?) -> String {
        let cleanMarketing = marketing?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let cleanBuild = build?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !cleanMarketing.isEmpty else { return "—" }
        if cleanBuild.isEmpty || cleanBuild == cleanMarketing {
            return cleanMarketing
        }
        return "\(cleanMarketing) (\(cleanBuild))"
    }

    /// "Never checked" / "Just now" / "5m ago" / "3h ago" / 具体日期。
    public static func lastCheckDescription(date: Date?, now: Date = Date()) -> String {
        guard let date else { return L10n.tr("updates.never_checked") }
        let interval = now.timeIntervalSince(date)
        if interval < 60 {
            return L10n.tr("updates.just_now")
        } else if interval < 3600 {
            return L10n.tr("updates.minutes_ago", max(1, Int(interval / 60)))
        } else if interval < 86400 {
            return L10n.tr("updates.hours_ago", max(1, Int(interval / 3600)))
        } else {
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: L10n.currentLanguage)
            formatter.dateStyle = .medium
            formatter.timeStyle = .short
            return formatter.string(from: date)
        }
    }

    /// 菜单栏提醒行的标题："Kanjo 0.6.0 is available"。
    public static func pendingUpdateTitle(version: String, appName: String = "Kanjo") -> String {
        L10n.tr("menu.update.available", appName, version)
    }
}
