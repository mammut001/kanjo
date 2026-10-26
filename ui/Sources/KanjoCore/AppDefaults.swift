import Foundation

/// 应用设置存储（UserDefaults / @AppStorage 统一访问入口）。
///
/// 避免开发调试 / 截图窗口（`--window`）直接读写用户的真实偏好设置（UserDefaults.standard），
/// 支持通过命令行参数 `--defaults-suite <name>`、环境变量 `KANJO_DEFAULTS_SUITE` 或 `--window` 切换到独立的 settings suite。
public enum AppDefaults {
    public static let previewSuiteName = "kanjo-preview"
    public static let suiteArgument = "--defaults-suite"
    public static let suiteEnvironmentKey = "KANJO_DEFAULTS_SUITE"
    public static let windowArgument = "--window"

    /// 单例存储，根据进程启动参数与环境变量自动选择使用隔离 suite 还是 UserDefaults.standard。
    public static let store: UserDefaults = resolveStore()

    /// 解析当前应使用的 UserDefaults suite 名称：
    /// 1. `--defaults-suite <name>`（或 `--defaults-suite=<name>`）命令行参数
    /// 2. `KANJO_DEFAULTS_SUITE` 环境变量
    /// 3. `--window` 启动参数 -> 自动默认使用 `"kanjo-preview"`
    /// 4. 否则返回 `nil`（表示使用 `UserDefaults.standard`）
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
        if arguments.contains(windowArgument) {
            return previewSuiteName
        }
        return nil
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

    /// 便捷重载（测试时可直接调用 AppDefaults.store(arguments:environment:)）。
    public static func store(
        arguments: [String],
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> UserDefaults {
        resolveStore(arguments: arguments, environment: environment)
    }
}
