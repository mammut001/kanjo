import Foundation

/// 本地化辅助模块（CONTRACT / UI 本地化支持）
public enum L10n {
    public static let supportedLanguages = ["en", "zh-Hans", "fr"]
    public static let defaultLanguage = "en"

    private static let lock = NSLock()
    private static var bundleCache: [String: Bundle] = [:]

    /// 规范化语言标识符：去除空白，小写化，并将下划线统一替换为连字符（zh-Hans == zh-hans == zh_Hans）
    public static func normalizeLanguage(_ code: String) -> String {
        let name = (code as NSString).lastPathComponent
        let baseName: String
        if name.lowercased().hasSuffix(".lproj") {
            baseName = String(name.dropLast(".lproj".count))
        } else {
            baseName = name
        }
        return baseName
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "_", with: "-")
    }

    /// 在候选目录名或语言标识符列表中查找匹配项（纯函数，忽略大小写，规范化 '-' 与 '_'）
    public static func matchLproj(for language: String, in candidates: [String]) -> String? {
        let trimmedLang = language.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedLang.isEmpty else { return nil }
        let target = normalizeLanguage(trimmedLang)
        guard !target.isEmpty else { return nil }

        // 1. 完全匹配（带或不带 .lproj 后缀）
        for candidate in candidates {
            if candidate == "\(trimmedLang).lproj" || candidate == trimmedLang {
                return candidate
            }
        }

        // 2. 忽略大小写匹配
        let lowercasedLang = trimmedLang.lowercased()
        for candidate in candidates {
            let lower = candidate.lowercased()
            if lower == "\(lowercasedLang).lproj" || lower == lowercasedLang {
                return candidate
            }
        }

        // 3. 规范化 '-' 与 '_' 后的匹配
        for candidate in candidates {
            if normalizeLanguage(candidate) == target {
                return candidate
            }
        }

        return nil
    }

    /// 别名：纯函数在目录名列表中匹配 lproj 目录
    public static func matchLprojDirectory(for language: String, in candidates: [String]) -> String? {
        matchLproj(for: language, in: candidates)
    }

    /// 查找指定语言对应的 .lproj URL（检查 Bundle 的 localizations 以及 Contents/Resources 和根目录）
    public static func lprojURL(for language: String, in bundle: Bundle? = nil) -> URL? {
        let trimmed = language.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let b = bundle ?? Bundle.module

        // 1. 尝试从 b.localizations 匹配
        let localizations = b.localizations
        if let matchedLoc = matchLproj(for: trimmed, in: localizations),
           let url = b.url(forResource: matchedLoc, withExtension: "lproj"),
           FileManager.default.fileExists(atPath: url.path) {
            return url
        }

        // 2. 遍历 bundle 内部可能的资源目录（包括 Contents/Resources 以及 bundle 根目录）
        var candidateDirs: [URL] = []
        if let resourceURL = b.resourceURL {
            candidateDirs.append(resourceURL)
        }
        let contentsRes = b.bundleURL.appendingPathComponent("Contents/Resources", isDirectory: true)
        candidateDirs.append(contentsRes)
        candidateDirs.append(b.bundleURL)

        var seenStandardizedPaths = Set<String>()
        for dir in candidateDirs {
            let standardized = dir.standardizedFileURL.path
            guard !seenStandardizedPaths.contains(standardized) else { continue }
            seenStandardizedPaths.insert(standardized)

            var isDir: ObjCBool = false
            guard FileManager.default.fileExists(atPath: dir.path, isDirectory: &isDir),
                  isDir.boolValue else {
                continue
            }
            guard let contents = try? FileManager.default.contentsOfDirectory(atPath: dir.path) else {
                continue
            }
            let lprojEntries = contents.filter { $0.lowercased().hasSuffix(".lproj") }
            if let matchedName = matchLproj(for: trimmed, in: lprojEntries) {
                let candidateURL = dir.appendingPathComponent(matchedName, isDirectory: true)
                if FileManager.default.fileExists(atPath: candidateURL.path) {
                    return candidateURL
                }
            }
        }

        // 3. 回退尝试系统默认 API
        if let direct = b.url(forResource: trimmed, withExtension: "lproj"),
           FileManager.default.fileExists(atPath: direct.path) {
            return direct
        }

        return nil
    }

    /// 获取特定语言的子 bundle（从 Bundle.module 的 *.lproj 查找）
    public static func bundle(for language: String) -> Bundle? {
        let trimmed = language.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let normalized = normalizeLanguage(trimmed)

        lock.lock()
        defer { lock.unlock() }
        if let cached = bundleCache[normalized] ?? bundleCache[trimmed] {
            return cached
        }
        guard let url = lprojURL(for: trimmed, in: Bundle.module),
              let b = Bundle(url: url) else {
            return nil
        }
        bundleCache[normalized] = b
        bundleCache[trimmed] = b
        return b
    }

    /// 当前有效语言代码（"en" / "zh-Hans" / "fr"）
    public static var currentLanguage: String {
        effectiveLanguage(for: AppDefaults.store.string(forKey: SettingsKeys.appLanguage))
    }

    /// 根据用户设置项（或系统语言回退）计算出的有效语言代码
    public static func effectiveLanguage(for preference: String?) -> String {
        if let preference, !preference.isEmpty && preference != AppLanguage.system.rawValue {
            if supportedLanguages.contains(preference) {
                return preference
            }
            if let matched = supportedLanguages.first(where: { normalizeLanguage($0) == normalizeLanguage(preference) }) {
                return matched
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
        guard let b = bundle(for: language) else {
            return nil
        }
        let stringsURL: URL?
        if let direct = b.url(forResource: "Localizable", withExtension: "strings"),
           FileManager.default.fileExists(atPath: direct.path) {
            stringsURL = direct
        } else {
            let directFile = b.bundleURL.appendingPathComponent("Localizable.strings")
            if FileManager.default.fileExists(atPath: directFile.path) {
                stringsURL = directFile
            } else if let files = try? FileManager.default.contentsOfDirectory(atPath: b.bundleURL.path),
                      let match = files.first(where: { $0.caseInsensitiveCompare("Localizable.strings") == .orderedSame }) {
                stringsURL = b.bundleURL.appendingPathComponent(match)
            } else {
                stringsURL = nil
            }
        }
        guard let url = stringsURL,
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
