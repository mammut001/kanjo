import Foundation

/// 应用设置存储（UserDefaults / @AppStorage 统一访问入口）。
///
/// 避免开发调试 / 截图窗口（`--window`、`--snapshot`、`--share-image`）直接读写用户的真实偏好设置（UserDefaults.standard），
/// 支持通过命令行参数 `--defaults-suite <name>`、环境变量 `KANJO_DEFAULTS_SUITE` 或这些启动参数切换到独立的 settings suite。
public enum AppDefaults {
    public static let previewSuiteName = "kanjo-preview"
    /// `swift test` writes here instead of `UserDefaults.standard`.
    public static let xctestSuiteName = "kanjo-xctest"
    public static let suiteArgument = "--defaults-suite"
    public static let suiteEnvironmentKey = "KANJO_DEFAULTS_SUITE"
    public static let windowArgument = "--window"
    public static let snapshotArgument = "--snapshot"
    public static let shareImageArgument = "--share-image"

    /// 单例存储。启动参数选出 suite；否则在 XCTest 进程里用 `kanjo-xctest`，避免测试写到用户的标准域。
    public static let store: UserDefaults = resolveProcessStore(
        runningTests: isXCTestHost(
            environment: ProcessInfo.processInfo.environment,
            xcTestLinked: NSClassFromString("XCTestCase") != nil
        )
    )

    /// 解析当前应使用的 UserDefaults suite 名称：
    /// 1. `--defaults-suite <name>`（或 `--defaults-suite=<name>`）命令行参数
    /// 2. `KANJO_DEFAULTS_SUITE` 环境变量
    /// 3. `--window`、`--snapshot` 或 `--share-image` -> `"kanjo-preview"`
    /// 4. 否则返回 `nil`（表示使用 `UserDefaults.standard`）
    ///
    /// `--data` 不切换 suite：它只换用量文件，设置仍是用户自己的。
    public static func suiteName(
        arguments: [String] = CommandLine.arguments,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> String? {
        if let idx = arguments.firstIndex(where: { $0 == suiteArgument || $0.hasPrefix("\(suiteArgument)=") }) {
            let arg = arguments[idx]
            if arg == suiteArgument {
                if idx + 1 < arguments.count {
                    let val = arguments[idx + 1].trimmingCharacters(in: .whitespaces)
                    if !val.isEmpty {
                        return val
                    }
                }
            } else {
                let val = String(arg.dropFirst("\(suiteArgument)=".count)).trimmingCharacters(in: .whitespaces)
                if !val.isEmpty {
                    return val
                }
            }
        }
        if let env = environment[suiteEnvironmentKey]?.trimmingCharacters(in: .whitespaces), !env.isEmpty {
            return env
        }
        if arguments.contains(windowArgument)
            || arguments.contains(snapshotArgument)
            || arguments.contains(where: { $0.hasPrefix("\(snapshotArgument)=") })
            || arguments.contains(shareImageArgument)
            || arguments.contains(where: { $0.hasPrefix("\(shareImageArgument)=") }) {
            return previewSuiteName
        }
        return nil
    }

    /// 进程级存储。`runningTests` 为真且参数没有选出别的 suite 时，用 `kanjo-xctest`。
    /// `resolveStore(arguments:environment:)` 本身不看 XCTest，空参数仍然得到 `.standard`。
    public static func resolveProcessStore(
        arguments: [String] = CommandLine.arguments,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        runningTests: Bool = false
    ) -> UserDefaults {
        let resolved = resolveStore(arguments: arguments, environment: environment)
        if resolved == .standard && runningTests {
            return UserDefaults(suiteName: xctestSuiteName) ?? .standard
        }
        return resolved
    }

    static func isXCTestHost(environment: [String: String], xcTestLinked: Bool) -> Bool {
        if environment["XCTestConfigurationFilePath"] != nil
            || environment["XCTestBundlePath"] != nil
            || environment["XCTestSessionIdentifier"] != nil {
            return true
        }
        return xcTestLinked
    }

    /// 根据给定的参数与环境变量解析 UserDefaults 实例（纯函数方便测试）。
    public static func resolveStore(
        arguments: [String] = CommandLine.arguments,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> UserDefaults {
        if let name = suiteName(arguments: arguments, environment: environment) {
            return UserDefaults(suiteName: name) ?? .standard
        }
        return .standard
    }

    public static func isSnapshotMode(arguments: [String] = CommandLine.arguments) -> Bool {
        arguments.contains { $0 == snapshotArgument || $0.hasPrefix("\(snapshotArgument)=") }
    }

    /// 便捷重载（测试时可直接调用 AppDefaults.store(arguments:environment:)）。
    public static func store(
        arguments: [String],
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> UserDefaults {
        resolveStore(arguments: arguments, environment: environment)
    }
}
