import XCTest
@testable import KanjoCore

final class UpdateTests: KanjoTestCase {
    private let goodFeed = "https://github.com/mammut001/kanjo/releases/latest/download/appcast.xml"
    private let goodKey = "vmOe1t+p1v3JEswzjVmUkECAovISZ6QQ7t6WvhbdEDo="

    private func appURL() -> URL {
        URL(fileURLWithPath: "/Applications/Kanjo.app")
    }

    private func info(feed: String? = nil, key: String? = nil) -> [String: Any] {
        var dict: [String: Any] = [:]
        dict[UpdateGate.feedKey] = feed ?? goodFeed
        dict[UpdateGate.publicKeyKey] = key ?? goodKey
        return dict
    }

    // MARK: Version formatting

    func testVersionString() {
        XCTAssertEqual(UpdateFormatting.versionString(marketing: "0.5.2", build: "0.5.2"), "0.5.2")
        XCTAssertEqual(UpdateFormatting.versionString(marketing: "0.5.2", build: "502"), "0.5.2 (502)")
        XCTAssertEqual(UpdateFormatting.versionString(marketing: "0.5.2", build: ""), "0.5.2")
        XCTAssertEqual(UpdateFormatting.versionString(marketing: "0.5.2", build: nil), "0.5.2")
        XCTAssertEqual(UpdateFormatting.versionString(marketing: " 0.5.2 ", build: " 502 "), "0.5.2 (502)")
        XCTAssertEqual(UpdateFormatting.versionString(marketing: nil, build: "502"), "—")
        XCTAssertEqual(UpdateFormatting.versionString(marketing: "", build: ""), "—")
    }

    func testLastCheckDescription() {
        let now = Date()
        XCTAssertEqual(UpdateFormatting.lastCheckDescription(date: nil, now: now),
                       L10n.tr("updates.never_checked", language: "en"))
        XCTAssertEqual(UpdateFormatting.lastCheckDescription(date: now.addingTimeInterval(-10), now: now),
                       L10n.tr("updates.just_now", language: "en"))
        XCTAssertEqual(UpdateFormatting.lastCheckDescription(date: now.addingTimeInterval(-5 * 60), now: now),
                       "5m ago")
        XCTAssertEqual(UpdateFormatting.lastCheckDescription(date: now.addingTimeInterval(-3 * 3600), now: now),
                       "3h ago")
        // 超过一天用具体日期，至少不该是空的。
        XCTAssertFalse(UpdateFormatting.lastCheckDescription(date: now.addingTimeInterval(-3 * 86400), now: now).isEmpty)
    }

    // MARK: Updater gate

    func testUpdaterStartsForPackagedAppWithFeedAndKey() {
        XCTAssertTrue(UpdateGate.shouldStartUpdater(
            bundleURL: appURL(),
            infoDictionary: info(),
            arguments: [],
            environment: [:]
        ))
    }

    func testUpdaterNeedsPackagedApp() {
        // `swift run` / `swift test`：可执行文件不在 .app 里。
        XCTAssertFalse(UpdateGate.shouldStartUpdater(
            bundleURL: URL(fileURLWithPath: "/tmp/kanjo/.build/debug/Kanjo"),
            infoDictionary: info(),
            arguments: [],
            environment: [:]
        ))
        XCTAssertFalse(UpdateGate.shouldStartUpdater(
            bundleURL: nil,
            infoDictionary: info(),
            arguments: [],
            environment: [:]
        ))
    }

    func testUpdaterSkippedInDevelopmentModes() {
        for arguments in [["--snapshot", "/tmp/out.png"], ["--snapshot=/tmp/out.png"],
                          ["--window"], ["--data", "/tmp/data.json"], ["--data=/tmp/data.json"]] {
            XCTAssertFalse(UpdateGate.shouldStartUpdater(
                bundleURL: appURL(),
                infoDictionary: info(),
                arguments: arguments,
                environment: [:]
            ), "updater must stay off for \(arguments)")
        }
        // KANJO_DATA 等价于 --data。
        XCTAssertFalse(UpdateGate.shouldStartUpdater(
            bundleURL: appURL(),
            infoDictionary: info(),
            arguments: [],
            environment: ["KANJO_DATA": "/tmp/data.json"]
        ))
        // 空值不算开发模式。
        XCTAssertTrue(UpdateGate.shouldStartUpdater(
            bundleURL: appURL(),
            infoDictionary: info(),
            arguments: [],
            environment: ["KANJO_DATA": "  "]
        ))
        // 不相干的参数不影响。
        XCTAssertTrue(UpdateGate.shouldStartUpdater(
            bundleURL: appURL(),
            infoDictionary: info(),
            arguments: ["--defaults-suite", "kanjo-test"],
            environment: [:]
        ))
    }

    func testUpdaterDisabledWhenFeedMissing() {
        XCTAssertFalse(UpdateGate.shouldStartUpdater(
            bundleURL: appURL(),
            infoDictionary: [UpdateGate.publicKeyKey: goodKey],
            arguments: [],
            environment: [:]
        ))
        XCTAssertFalse(UpdateGate.shouldStartUpdater(
            bundleURL: appURL(),
            infoDictionary: info(feed: ""),
            arguments: [],
            environment: [:]
        ))
        XCTAssertFalse(UpdateGate.shouldStartUpdater(
            bundleURL: appURL(),
            infoDictionary: nil,
            arguments: [],
            environment: [:]
        ))
        // 只接受 https 的绝对地址。
        XCTAssertFalse(UpdateGate.isUsableFeedURL("http://example.com/appcast.xml"))
        XCTAssertFalse(UpdateGate.isUsableFeedURL("appcast.xml"))
        XCTAssertTrue(UpdateGate.isUsableFeedURL(goodFeed))
    }

    func testUpdaterDisabledWhenKeyMissingOrPlaceholder() {
        XCTAssertFalse(UpdateGate.shouldStartUpdater(
            bundleURL: appURL(),
            infoDictionary: [UpdateGate.feedKey: goodFeed],
            arguments: [],
            environment: [:]
        ))
        XCTAssertFalse(UpdateGate.shouldStartUpdater(
            bundleURL: appURL(),
            infoDictionary: info(key: ""),
            arguments: [],
            environment: [:]
        ))
        // 仓库里那份占位符不能当成真钥匙，否则每个本地构建都会去敲一个不存在的 feed。
        XCTAssertFalse(UpdateGate.isUsablePublicKey(UpdateGate.placeholderPublicKey))
        XCTAssertFalse(UpdateGate.shouldStartUpdater(
            bundleURL: appURL(),
            infoDictionary: info(key: UpdateGate.placeholderPublicKey),
            arguments: [],
            environment: [:]
        ))
        XCTAssertTrue(UpdateGate.isUsablePublicKey(goodKey))
    }

    /// 仓库里的公钥文件必须存在，且本地开发时仍是占位符（公证构建会被 package.sh 拒绝）。
    func testPublicKeyFileShape() throws {
        let root = try XCTUnwrap(DefaultPaths.packageRoot)
        let url = root.appendingPathComponent("Resources/sparkle-public-ed-key.txt")
        let raw = try String(contentsOf: url, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        XCTAssertFalse(raw.isEmpty, "sparkle-public-ed-key.txt must not be empty")
        if raw == UpdateGate.placeholderPublicKey {
            XCTAssertFalse(UpdateGate.isUsablePublicKey(raw))
        } else {
            // 真钥匙是 base64 的 32 字节 Ed25519 公钥。
            XCTAssertEqual(Data(base64Encoded: raw)?.count, 32, "public key should be base64 of 32 bytes")
        }
    }

    /// package.sh 写进 Info.plist 的 feed 必须和 app 里的常量一致。
    func testPackageScriptFeedMatchesConstant() throws {
        let root = try XCTUnwrap(DefaultPaths.packageRoot)
        let script = try String(contentsOf: root.appendingPathComponent("package.sh"), encoding: .utf8)
        XCTAssertTrue(script.contains("SPARKLE_FEED_URL=\"\(UpdateGate.feedURL)\""),
                      "package.sh SPARKLE_FEED_URL must match UpdateGate.feedURL")
        XCTAssertTrue(script.contains("<key>SUPublicEDKey</key>"))
        XCTAssertTrue(script.contains("<key>SUScheduledCheckInterval</key><integer>86400</integer>"))
        XCTAssertTrue(script.contains("<key>SUAllowsAutomaticUpdates</key><false/>"))
    }

    // MARK: Appcast script

    func testValidateAppcastScriptAcceptsFixture() throws {
        let root = try XCTUnwrap(DefaultPaths.packageRoot)   // ui/
        let repoRoot = root.deletingLastPathComponent()
        let script = repoRoot.appendingPathComponent("scripts/validate-appcast.sh")
        let fixture = root.appendingPathComponent("fixtures/appcast-sample.xml")
        try XCTSkipUnless(FileManager.default.isExecutableFile(atPath: script.path),
                          "scripts/validate-appcast.sh not found")

        let output = try runScript(script, arguments: [
            fixture.path,
            "0.6.0",
            "600",
            "https://github.com/mammut001/kanjo/releases/download/v0.6.0/Kanjo-0.6.0-macos.zip",
        ])
        XCTAssertTrue(output.contains("Appcast OK"), output)

        // 版本 / build / URL 对不上时必须失败。
        XCTAssertFalse(try runScriptAllowingFailure(script, arguments: [
            fixture.path, "0.6.1", "600",
            "https://github.com/mammut001/kanjo/releases/download/v0.6.1/Kanjo-0.6.1-macos.zip",
        ]).status == 0)
        XCTAssertFalse(try runScriptAllowingFailure(script, arguments: [
            fixture.path, "0.6.0", "601",
            "https://github.com/mammut001/kanjo/releases/download/v0.6.0/Kanjo-0.6.0-macos.zip",
        ]).status == 0)
        XCTAssertFalse(try runScriptAllowingFailure(script, arguments: [
            fixture.path, "0.6.0", "600",
            "https://github.com/mammut001/kanjo/releases/download/v0.9.9/Kanjo-0.9.9-macos.zip",
        ]).status == 0)
    }

    @discardableResult
    private func runScript(_ script: URL, arguments: [String]) throws -> String {
        let result = try runScriptAllowingFailure(script, arguments: arguments)
        XCTAssertEqual(result.status, 0, result.output)
        return result.output
    }

    private func runScriptAllowingFailure(_ script: URL, arguments: [String]) throws -> (status: Int32, output: String) {
        let process = Process()
        process.executableURL = script
        process.arguments = arguments
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        return (process.terminationStatus, String(data: data, encoding: .utf8) ?? "")
    }
}
