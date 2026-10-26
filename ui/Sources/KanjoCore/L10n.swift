import Foundation

/// 本地化辅助模块（CONTRACT / UI 本地化支持）
public enum L10n {
    public static let supportedLanguages = ["en", "zh-Hans", "fr"]
    public static let defaultLanguage = "en"

    private static let lock = NSLock()
    private static var bundleCache: [String: Bundle] = [:]

    /// 获取特定语言的子 bundle（从 Bundle.module 的 *.lproj 查找）
    public static func bundle(for language: String) -> Bundle? {
        lock.lock()
        defer { lock.unlock() }
        if let cached = bundleCache[language] {
            return cached
        }
        guard let url = Bundle.module.url(forResource: language, withExtension: "lproj"),
              let b = Bundle(url: url) else {
            return nil
        }
        bundleCache[language] = b
        return b
    }

    /// 当前有效语言代码（"en" / "zh-Hans" / "fr"）
    public static var currentLanguage: String {
        effectiveLanguage(for: UserDefaults.standard.string(forKey: SettingsKeys.appLanguage))
    }

    /// 根据用户设置项（或系统语言回退）计算出的有效语言代码
    public static func effectiveLanguage(for preference: String?) -> String {
        if let preference, !preference.isEmpty && preference != AppLanguage.system.rawValue {
            if supportedLanguages.contains(preference) {
                return preference
            }
        }
        return systemLanguage
    }

    /// 匹配系统语言到我们支持的语言，未命中时回退到默认语言 "en"
    public static var systemLanguage: String {
        let matched = Bundle.preferredLocalizations(from: supportedLanguages,
                                                    forPreferences: Locale.preferredLanguages)
        return matched.first ?? defaultLanguage
    }

    /// 翻译指定 key，可显式指定语言；未提供时按当前选中语言，失败时回退到 en，若仍未命中则返回 key 本身。
    public static func tr(_ key: String, language: String? = nil) -> String {
        let lang = language ?? currentLanguage
        if let b = bundle(for: lang) {
            let val = b.localizedString(forKey: key, value: "\u{0}missing", table: nil)
            if val != "\u{0}missing" {
                return val
            }
        }
        if lang != defaultLanguage, let enBundle = bundle(for: defaultLanguage) {
            let val = enBundle.localizedString(forKey: key, value: "\u{0}missing", table: nil)
            if val != "\u{0}missing" {
                return val
            }
        }
        return key
    }

    /// 带格式化参数的翻译
    public static func tr(_ key: String, language: String? = nil, _ args: CVarArg...) -> String {
        let format = tr(key, language: language)
        if args.isEmpty { return format }
        return String(format: format, arguments: args)
    }

    /// 读取某一语言 .strings 文件中的所有键值（供测试验证完整性）
    public static func allStrings(for language: String) -> [String: String]? {
        guard let b = bundle(for: language),
              let url = b.url(forResource: "Localizable", withExtension: "strings"),
              let data = try? Data(contentsOf: url) else {
            return nil
        }
        var format = PropertyListSerialization.PropertyListFormat.openStep
        return (try? PropertyListSerialization.propertyList(from: data, options: [], format: &format)) as? [String: String]
    }
}

/// 便捷全局翻译函数
public func L(_ key: String, _ args: CVarArg...) -> String {
    let format = L10n.tr(key)
    if args.isEmpty { return format }
    return String(format: format, arguments: args)
}
