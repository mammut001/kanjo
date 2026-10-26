import XCTest
@testable import KanjoCore

/// 测试基类：默认强制应用语言为英文，保证断言英文文案的测试（如 "renews today" 等）
/// 在非英文 macOS 系统环境（如 zh-Hans / fr）下执行时结果确定。
class KanjoTestCase: XCTestCase {
    private var priorLanguage: String?

    override func setUp() {
        super.setUp()
        priorLanguage = AppDefaults.store.string(forKey: SettingsKeys.appLanguage)
        AppDefaults.store.set(AppLanguage.en.rawValue, forKey: SettingsKeys.appLanguage)
    }

    override func tearDown() {
        if let prior = priorLanguage {
            AppDefaults.store.set(prior, forKey: SettingsKeys.appLanguage)
        } else {
            AppDefaults.store.removeObject(forKey: SettingsKeys.appLanguage)
        }
        super.tearDown()
    }
}
