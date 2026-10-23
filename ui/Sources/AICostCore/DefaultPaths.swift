import Foundation

public enum DefaultPaths {
    /// 本包的 ui/ 目录（编译期由 #filePath 推出：ui/Sources/AICostCore/DefaultPaths.swift）。
    /// 只在从源码 `swift run` 时有意义；打包成 .app 后该路径可能不存在。
    public static var packageRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // AICostCore
            .deletingLastPathComponent()  // Sources
            .deletingLastPathComponent()  // ui
    }

    public static var sampleFixture: URL {
        packageRoot.appendingPathComponent("fixtures/sample.json")
    }

    /// 仓库里和 ui/ 并排的 cli/ 目录，默认在这里执行 `python3 -m aicost export`。
    public static var cliDirectory: URL {
        packageRoot.deletingLastPathComponent().appendingPathComponent("cli")
    }

    /// cli/ 目录在不在：在就默认走 CLI 取数，不在（比如打包后的 .app）就退回示例 JSON。
    public static var cliDirectoryExists: Bool {
        var isDir: ObjCBool = false
        return FileManager.default.fileExists(atPath: cliDirectory.appendingPathComponent("aicost").path,
                                              isDirectory: &isDir) && isDir.boolValue
    }

    /// 命令行覆盖：`--data <path>` 优先，其次环境变量 `AICOST_DATA`。
    public static func dataOverride(arguments: [String] = CommandLine.arguments,
                                    environment: [String: String] = ProcessInfo.processInfo.environment) -> URL? {
        if let i = arguments.firstIndex(of: "--data"), i + 1 < arguments.count {
            return URL(fileURLWithPath: (arguments[i + 1] as NSString).expandingTildeInPath)
        }
        if let env = environment["AICOST_DATA"], !env.isEmpty {
            return URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
        }
        return nil
    }
}
