import XCTest
@testable import KanjoCore

final class LocalizationTests: KanjoTestCase {
    /// 确保 en 中的每一个 key 在 zh-Hans 和 fr 中都存在
    func testAllKeysPresentInAllLanguages() {
        guard let enStrings = L10n.allStrings(for: "en") else {
            XCTFail("Failed to load English strings dictionary")
            return
        }
        XCTAssertFalse(enStrings.isEmpty, "English strings dictionary should not be empty")

        for lang in ["zh-Hans", "fr"] {
            guard let langStrings = L10n.allStrings(for: lang) else {
                XCTFail("Failed to load strings dictionary for \(lang)")
                continue
            }
            var missingKeys: [String] = []
            for key in enStrings.keys {
                if langStrings[key] == nil {
                    missingKeys.append(key)
                }
            }
            XCTAssertTrue(missingKeys.isEmpty, "\(lang) is missing keys: \(missingKeys.sorted().joined(separator: ", "))")
        }
    }

    /// 扫描 ui/Sources 源码中所有 L10n.tr 调用的字面量 key，确保它们均在 en.lproj 中存在
    func testAllSourceKeysPresentInEnglishStrings() throws {
        guard let packageRoot = DefaultPaths.packageRoot else {
            return
        }
        guard let enStrings = L10n.allStrings(for: "en") else {
            XCTFail("Failed to load English strings")
            return
        }
        let sourcesURL = packageRoot.appendingPathComponent("Sources")
        let fm = FileManager.default
        guard let enumerator = fm.enumerator(at: sourcesURL, includingPropertiesForKeys: [.isRegularFileKey]) else {
            XCTFail("Failed to enumerate Sources directory")
            return
        }

        let regex = try NSRegularExpression(pattern: #"L10n\.tr\(\s*"([^"]+)""#)
        var usedKeys = Set<String>()

        for case let fileURL as URL in enumerator {
            guard fileURL.pathExtension == "swift" else { continue }
            let content = try String(contentsOf: fileURL, encoding: .utf8)
            let nsRange = NSRange(content.startIndex..<content.endIndex, in: content)
            regex.enumerateMatches(in: content, range: nsRange) { match, _, _ in
                if let match, let range = Range(match.range(at: 1), in: content) {
                    usedKeys.insert(String(content[range]))
                }
            }
        }

        XCTAssertFalse(usedKeys.isEmpty, "Should find L10n.tr keys in sources")
        let missing = usedKeys.filter { enStrings[$0] == nil }
        XCTAssertTrue(missing.isEmpty, "Keys used in ui/Sources missing in en.lproj: \(missing.sorted().joined(separator: ", "))")
    }

    /// 验证对若干常用 key 解析 zh-Hans 和 fr 时返回的内容与英文不同（且不是原始 key）
    func testResolvingKeysDifferFromEnglish() {
        let sampleKeys = [
            "common.done",
            "settings.title",
            "overview.total_cost",
            "disk.clean_help",
            "menu.quit",
        ]
        for key in sampleKeys {
            let en = L10n.tr(key, language: "en")
            let zh = L10n.tr(key, language: "zh-Hans")
            let fr = L10n.tr(key, language: "fr")

            XCTAssertNotEqual(zh, en, "Simplified Chinese should differ from English for key '\(key)'")
            XCTAssertNotEqual(fr, en, "French should differ from English for key '\(key)'")
            XCTAssertNotEqual(zh, key, "Simplified Chinese translation should not be raw key for '\(key)'")
            XCTAssertNotEqual(fr, key, "French translation should not be raw key for '\(key)'")
        }
    }

    /// 验证有效语言推导逻辑
    func testEffectiveLanguage() {
        XCTAssertEqual(L10n.effectiveLanguage(for: "en"), "en")
        XCTAssertEqual(L10n.effectiveLanguage(for: "zh-Hans"), "zh-Hans")
        XCTAssertEqual(L10n.effectiveLanguage(for: "fr"), "fr")

        // "system", nil 或未识别语言应回退到支持的系统语言
        XCTAssertTrue(L10n.supportedLanguages.contains(L10n.effectiveLanguage(for: "system")))
        XCTAssertTrue(L10n.supportedLanguages.contains(L10n.effectiveLanguage(for: nil)))
        XCTAssertTrue(L10n.supportedLanguages.contains(L10n.effectiveLanguage(for: "unsupported-lang")))
    }

    /// 验证不存在 key 的回退行为
    func testMissingKeyFallback() {
        let nonExistentKey = "nonexistent.key.that.does.not.exist"
        XCTAssertEqual(L10n.tr(nonExistentKey, language: "en"), nonExistentKey)
        XCTAssertEqual(L10n.tr(nonExistentKey, language: "zh-Hans"), nonExistentKey)
        XCTAssertEqual(L10n.tr(nonExistentKey, language: "fr"), nonExistentKey)
    }

    /// 验证带参数格式化功能
    func testParameterizedTranslation() {
        let result = L10n.tr("common.show_all", language: "en", 5, "items")
        XCTAssertEqual(result, "Show all 5 items")
    }

    /// 验证 lproj 目录名称匹配器（纯函数：大小写不敏感，规范化 '-' 与 '_'）
    func testLprojMatcher() {
        // 1. 标准目录名
        let standardCandidates = ["en.lproj", "zh-Hans.lproj", "fr.lproj"]
        XCTAssertEqual(L10n.matchLproj(for: "zh-Hans", in: standardCandidates), "zh-Hans.lproj")
        XCTAssertEqual(L10n.matchLproj(for: "en", in: standardCandidates), "en.lproj")
        XCTAssertEqual(L10n.matchLproj(for: "fr", in: standardCandidates), "fr.lproj")

        // 2. 小写目录名 (zh-hans.lproj)
        let lowerCandidates = ["en.lproj", "zh-hans.lproj", "fr.lproj"]
        XCTAssertEqual(L10n.matchLproj(for: "zh-Hans", in: lowerCandidates), "zh-hans.lproj")
        XCTAssertEqual(L10n.matchLproj(for: "zh-hans", in: lowerCandidates), "zh-hans.lproj")
        XCTAssertEqual(L10n.matchLproj(for: "zh_Hans", in: lowerCandidates), "zh-hans.lproj")

        // 3. 下划线目录名 (zh_Hans.lproj / zh_hans.lproj)
        let underscoreCandidates = ["en.lproj", "zh_Hans.lproj", "fr.lproj"]
        XCTAssertEqual(L10n.matchLproj(for: "zh-Hans", in: underscoreCandidates), "zh_Hans.lproj")
        XCTAssertEqual(L10n.matchLproj(for: "zh-hans", in: underscoreCandidates), "zh_Hans.lproj")
        XCTAssertEqual(L10n.matchLproj(for: "zh_Hans", in: underscoreCandidates), "zh_Hans.lproj")

        let underscoreLowerCandidates = ["en.lproj", "zh_hans.lproj", "fr.lproj"]
        XCTAssertEqual(L10n.matchLproj(for: "zh-Hans", in: underscoreLowerCandidates), "zh_hans.lproj")

        // 4. 大写目录名 (ZH-HANS.LPROJ / ZH_HANS.LPROJ)
        let upperCandidates = ["EN.LPROJ", "ZH-HANS.LPROJ", "FR.LPROJ"]
        XCTAssertEqual(L10n.matchLproj(for: "zh-Hans", in: upperCandidates), "ZH-HANS.LPROJ")
        XCTAssertEqual(L10n.matchLproj(for: "zh_Hans", in: upperCandidates), "ZH-HANS.LPROJ")

        // 5. 不带 .lproj 后缀的语言代码列表（如 Bundle.localizations）
        let rawCandidates = ["en", "zh-hans", "fr"]
        XCTAssertEqual(L10n.matchLproj(for: "zh-Hans", in: rawCandidates), "zh-hans")
        XCTAssertEqual(L10n.matchLproj(for: "zh_Hans", in: rawCandidates), "zh-hans")

        // 6. 别名 matchLprojDirectory 同样可用
        XCTAssertEqual(L10n.matchLprojDirectory(for: "zh-Hans", in: lowerCandidates), "zh-hans.lproj")

        // 7. 不匹配与边界情况
        XCTAssertNil(L10n.matchLproj(for: "ja", in: standardCandidates))
        XCTAssertNil(L10n.matchLproj(for: "zh-Hant", in: standardCandidates))
        XCTAssertNil(L10n.matchLproj(for: "zh-Hans", in: []))
        XCTAssertNil(L10n.matchLproj(for: "", in: standardCandidates))
        XCTAssertNil(L10n.matchLproj(for: "   ", in: standardCandidates))
    }

    /// 验证不同变体拼写（zh-Hans / zh-hans / zh_Hans）均可正常加载 bundle 和 strings
    func testLanguageVariantsBundleAndStringsLoading() {
        for variant in ["zh-Hans", "zh-hans", "zh_Hans"] {
            guard let strings = L10n.allStrings(for: variant) else {
                XCTFail("Failed to load strings dictionary for variant: \(variant)")
                continue
            }
            XCTAssertFalse(strings.isEmpty, "Strings dictionary for \(variant) should not be empty")
            XCTAssertNotNil(L10n.bundle(for: variant), "Bundle for \(variant) should be found")
            XCTAssertEqual(L10n.tr("common.done", language: variant), "完成")
        }
    }

    /// 验证即使 lproj 目录位于 bundle 根目录或使用下划线/小写，lprojURL 仍能正确定位
    func testMockBundleRootAndLowercaseLookup() throws {
        let fm = FileManager.default
        let tempDir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("KanjoMock_\(UUID().uuidString).bundle")
        defer { try? fm.removeItem(at: tempDir) }

        // 场景 1：lproj 位于根目录，名为 zh_Hans.lproj
        let rootLproj = tempDir.appendingPathComponent("zh_Hans.lproj", isDirectory: true)
        try fm.createDirectory(at: rootLproj, withIntermediateDirectories: true)
        guard let bundle = Bundle(url: tempDir) else {
            XCTFail("Failed to instantiate mock bundle")
            return
        }

        let foundURL = L10n.lprojURL(for: "zh-Hans", in: bundle)
        XCTAssertNotNil(foundURL)
        XCTAssertEqual(foundURL?.lastPathComponent, "zh_Hans.lproj")

        // 场景 2：lproj 位于 Contents/Resources/zh-hans.lproj
        let nestedBundleDir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("KanjoNestedMock_\(UUID().uuidString).bundle")
        defer { try? fm.removeItem(at: nestedBundleDir) }

        let nestedLproj = nestedBundleDir.appendingPathComponent("Contents/Resources/zh-hans.lproj", isDirectory: true)
        try fm.createDirectory(at: nestedLproj, withIntermediateDirectories: true)
        guard let nestedBundle = Bundle(url: nestedBundleDir) else {
            XCTFail("Failed to instantiate nested mock bundle")
            return
        }

        let foundNestedURL = L10n.lprojURL(for: "zh-Hans", in: nestedBundle)
        XCTAssertNotNil(foundNestedURL)
        XCTAssertEqual(foundNestedURL?.lastPathComponent, "zh-hans.lproj")
    }
}
