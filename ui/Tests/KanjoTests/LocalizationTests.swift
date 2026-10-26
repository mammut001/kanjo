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
}
