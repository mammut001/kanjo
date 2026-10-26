import XCTest
@testable import KanjoCore

/// 测试基类：默认强制应用语言为英文，保证断言英文文案的测试（如 "renews today" 等）
/// 在非英文 macOS 系统环境（如 zh-Hans / fr）下执行时结果确定。
class KanjoTestCase: XCTestCase {
    private var priorLanguage: String?

    override func setUp() {
        super.setUp()
        priorLanguage = UserDefaults.standard.string(forKey: SettingsKeys.appLanguage)
        UserDefaults.standard.set(AppLanguage.en.rawValue, forKey: SettingsKeys.appLanguage)
    }

    override func tearDown() {
        if let prior = priorLanguage {
            UserDefaults.standard.set(prior, forKey: SettingsKeys.appLanguage)
        } else {
            UserDefaults.standard.removeObject(forKey: SettingsKeys.appLanguage)
        }
        super.tearDown()
    }
}
