import XCTest
@testable import KanjoCore

final class AppDefaultsTests: XCTestCase {
    func testPicksSuiteFromCommandLineArgument() {
        let args = ["--defaults-suite", "my-test-suite"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: args, environment: [:]), "my-test-suite")

        let argsEqual = ["--defaults-suite=another-suite"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: argsEqual, environment: [:]), "another-suite")
    }

    func testPicksSuiteFromEnvironment() {
        let env = ["KANJO_DEFAULTS_SUITE": "env-test-suite"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: [], environment: env), "env-test-suite")
    }

    func testCommandLineArgumentOverridesEnvironment() {
        let args = ["--defaults-suite", "cli-suite"]
        let env = ["KANJO_DEFAULTS_SUITE": "env-suite"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: args, environment: env), "cli-suite")
    }

    func testWindowDefaultsToKanjoPreview() {
        let args = ["--window"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: args, environment: [:]), "kanjo-preview")

        let argsWithOtherFlags = ["--window", "--route", "overview"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: argsWithOtherFlags, environment: [:]), "kanjo-preview")
    }

    func testSnapshotDefaultsToKanjoPreview() {
        let args = ["--snapshot", "out.png"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: args, environment: [:]), "kanjo-preview")

        let argsEqual = ["--snapshot=out.png"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: argsEqual, environment: [:]), "kanjo-preview")

        let argsWithOtherFlags = ["--snapshot", "out.png", "--route", "overview", "--snapshot-scale", "2"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: argsWithOtherFlags, environment: [:]), "kanjo-preview")
    }

    func testDefaultsSuiteOverridesWindow() {
        let args = ["--window", "--defaults-suite", "explicit-preview"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: args, environment: [:]), "explicit-preview")

        let argsReversed = ["--defaults-suite", "explicit-preview", "--window"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: argsReversed, environment: [:]), "explicit-preview")

        let argsWindowWithEnv = ["--window"]
        let env = ["KANJO_DEFAULTS_SUITE": "env-suite"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: argsWindowWithEnv, environment: env), "env-suite")
    }

    func testDefaultsSuiteOverridesSnapshot() {
        let args = ["--snapshot", "out.png", "--defaults-suite", "explicit-preview"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: args, environment: [:]), "explicit-preview")

        let argsReversed = ["--defaults-suite", "explicit-preview", "--snapshot", "out.png"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: argsReversed, environment: [:]), "explicit-preview")

        let argsSnapshotWithEnv = ["--snapshot", "out.png"]
        let env = ["KANJO_DEFAULTS_SUITE": "env-suite"]
        XCTAssertEqual(AppDefaults.suiteName(arguments: argsSnapshotWithEnv, environment: env), "env-suite")
    }

    func testShareImageDefaultsToKanjoPreview() {
        XCTAssertEqual(AppDefaults.suiteName(arguments: ["--share-image", "out.png"], environment: [:]), "kanjo-preview")
        XCTAssertEqual(AppDefaults.suiteName(arguments: ["--share-image=out.png"], environment: [:]), "kanjo-preview")
        XCTAssertEqual(AppDefaults.suiteName(
            arguments: ["--share-image", "out.png", "--defaults-suite", "explicit-preview"],
            environment: [:]
        ), "explicit-preview")
    }

    func testProcessStoreStaysOnStandardOutsideTests() {
        let store = AppDefaults.resolveProcessStore(arguments: [], environment: [:], runningTests: false)
        XCTAssertEqual(store, UserDefaults.standard)
        XCTAssertFalse(AppDefaults.isXCTestHost(environment: [:], xcTestLinked: false))
    }

    func testProcessStoreIsolatesWhenRunningTests() {
        XCTAssertTrue(AppDefaults.isXCTestHost(
            environment: ["XCTestConfigurationFilePath": "/tmp/x.xctestconfiguration"],
            xcTestLinked: false
        ))
        let store = AppDefaults.resolveProcessStore(arguments: [], environment: [:], runningTests: true)
        XCTAssertNotEqual(store, UserDefaults.standard)
        // suiteName itself stays nil: only the process store moves off .standard.
        XCTAssertNil(AppDefaults.suiteName(arguments: [], environment: [:]))
    }

    func testReturnsNilWhenAbsent() {
        XCTAssertNil(AppDefaults.suiteName(arguments: [], environment: [:]))
        XCTAssertNil(AppDefaults.suiteName(arguments: ["--data", "/tmp/sample.json"], environment: [:]))
        XCTAssertNil(AppDefaults.suiteName(arguments: ["--defaults-suite"], environment: [:]))
        XCTAssertNil(AppDefaults.suiteName(arguments: ["--defaults-suite", ""], environment: [:]))
        XCTAssertNil(AppDefaults.suiteName(arguments: [], environment: ["KANJO_DEFAULTS_SUITE": ""]))
    }

    func testResolvesStandardStoreWhenAbsent() {
        let store = AppDefaults.resolveStore(arguments: [], environment: [:])
        XCTAssertEqual(store, UserDefaults.standard)
    }

    func testResolvesIsolatedStore() {
        let suite = "kanjo-test-\(UUID().uuidString)"
        let store = AppDefaults.resolveStore(arguments: ["--defaults-suite", suite], environment: [:])
        defer {
            store.removePersistentDomain(forName: suite)
            UserDefaults.standard.removePersistentDomain(forName: suite)
            let path = ("~/Library/Preferences/\(suite).plist" as NSString).expandingTildeInPath
            try? FileManager.default.removeItem(atPath: path)
        }

        XCTAssertNotEqual(store, UserDefaults.standard)
        store.set("isolatedValue", forKey: "kanjo_isolated_key")
        XCTAssertEqual(store.string(forKey: "kanjo_isolated_key"), "isolatedValue")
        XCTAssertNil(UserDefaults.standard.string(forKey: "kanjo_isolated_key"))
    }

    func testSuiteStoreIsIsolatedFromStandard() {
        let suite = "kanjo-test-suite-\(UUID().uuidString)"
        let store = AppDefaults.store(arguments: ["--defaults-suite", suite], environment: [:])
        defer {
            store.removePersistentDomain(forName: suite)
            UserDefaults.standard.removePersistentDomain(forName: suite)
            let path = ("~/Library/Preferences/\(suite).plist" as NSString).expandingTildeInPath
            try? FileManager.default.removeItem(atPath: path)
        }

        store.set("suiteValue", forKey: "testKey")
        XCTAssertEqual(store.string(forKey: "testKey"), "suiteValue")
        XCTAssertNil(UserDefaults.standard.string(forKey: "testKey"))

        UserDefaults.standard.set("standardValue", forKey: "standardOnlyKey")
        defer { UserDefaults.standard.removeObject(forKey: "standardOnlyKey") }
        XCTAssertNil(store.string(forKey: "standardOnlyKey"))
    }

    func testAppAppearanceDefaultAndMapping() {
        XCTAssertEqual(SettingsKeys.appAppearance, "appAppearance")
        XCTAssertEqual(AppAppearance.defaultValue, .dark)
        XCTAssertEqual(AppAppearance.defaultValue.rawValue, "dark")
        XCTAssertEqual(AppAppearance.allCases, [.dark, .light, .system])

        XCTAssertEqual(AppAppearance.resolve(nil), .dark)
        XCTAssertEqual(AppAppearance.resolve(""), .dark)
        XCTAssertEqual(AppAppearance.resolve("unknown"), .dark)
        XCTAssertEqual(AppAppearance.resolve("dark"), .dark)
        XCTAssertEqual(AppAppearance.resolve("light"), .light)
        XCTAssertEqual(AppAppearance.resolve("system"), .system)

        XCTAssertEqual(AppAppearance.dark.explicitIsDark, true)
        XCTAssertEqual(AppAppearance.light.explicitIsDark, false)
        XCTAssertNil(AppAppearance.system.explicitIsDark)
    }
}
