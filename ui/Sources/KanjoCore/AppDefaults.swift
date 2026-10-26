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
            let suite = UserDefaults(suiteName: name) ?? .standard
            applyArgumentOverrides(to: suite, arguments: arguments)
            return suite
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

    /// 解析命令行 `-key value` 参数覆盖（NSArgumentDomain 行为）。
    public static func parseArgumentDomain(arguments: [String]) -> [String: Any] {
        var domain: [String: Any] = [:]
        var i = 0
        while i < arguments.count {
            let arg = arguments[i]
            if arg.hasPrefix("-") && !arg.hasPrefix("--") && arg.count > 1 {
                let key = String(arg.dropFirst())
                if i + 1 < arguments.count {
                    let next = arguments[i + 1]
                    if !next.hasPrefix("-") {
                        domain[key] = parseArgumentValue(next)
                        i += 2
                        continue
                    }
                }
            }
            i += 1
        }
        return domain
    }

    /// 字符串类型转换（Bool, Int, Double, String）。
    public static func parseArgumentValue(_ raw: String) -> Any {
        if raw.caseInsensitiveCompare("YES") == .orderedSame || raw.caseInsensitiveCompare("TRUE") == .orderedSame {
            return true
        }
        if raw.caseInsensitiveCompare("NO") == .orderedSame || raw.caseInsensitiveCompare("FALSE") == .orderedSame {
            return false
        }
        if let intVal = Int(raw) {
            return intVal
        }
        if let doubleVal = Double(raw) {
            return doubleVal
        }
        return raw
    }

    /// 将命令行启动参数的 -key value 应用到自定义 suite 的 argumentDomain 和 registrationDomain。
    public static func applyArgumentOverrides(
        to suite: UserDefaults,
        arguments: [String] = CommandLine.arguments
    ) {
        var domain = suite.volatileDomain(forName: UserDefaults.argumentDomain)
        let stdDomain = UserDefaults.standard.volatileDomain(forName: UserDefaults.argumentDomain)
        for (k, v) in stdDomain {
            domain[k] = v
        }
        let parsed = parseArgumentDomain(arguments: arguments)
        for (k, v) in parsed {
            domain[k] = v
        }
        if !domain.isEmpty {
            suite.setVolatileDomain(domain, forName: UserDefaults.argumentDomain)
            suite.register(defaults: domain)
        }
    }
}
