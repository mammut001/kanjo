import Foundation

public enum DefaultPaths {
    /// 本包的 ui/ 目录（编译期由 #filePath 推出：ui/Sources/KanjoCore/DefaultPaths.swift）。
    /// 只在 DEBUG（从源码 `swift run` / `swift test`）下有值；release 构建是 nil，
    /// 免得把构建机的源码路径编进发布的二进制。
    public static var packageRoot: URL? {
        #if DEBUG
        return URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // KanjoCore
            .deletingLastPathComponent()  // Sources
            .deletingLastPathComponent()  // ui
        #else
        return nil
        #endif
    }

    /// 示例数据：DEBUG 下用源码里的 fixtures/sample.json；release（或源码不在）就用 .app 里附带的那份
    /// （package.sh 放进 Contents/Resources/sample.json）。
    public static var sampleFixture: URL {
        let source = packageRoot?.appendingPathComponent("fixtures/sample.json")
        if let source, FileManager.default.fileExists(atPath: source.path) { return source }
        return Bundle.main.url(forResource: "sample", withExtension: "json")
            ?? source
            ?? Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/sample.json")
    }

    /// 仓库里和 ui/ 并排的 cli/ 目录，从源码运行时默认在这里执行 `python3 -m kanjo export`。release 下为 nil。
    public static var cliDirectory: URL? {
        packageRoot?.deletingLastPathComponent().appendingPathComponent("cli")
    }

    /// install.sh 安装 CLI 的位置，按顺序查找。打包后的 .app 里没有 cli/，靠这里找到 CLI。
    public static func installedCLIDirectories(home: URL = FileManager.default.homeDirectoryForCurrentUser) -> [URL] {
        [home.appendingPathComponent(".local/share/kanjo/cli"),
         URL(fileURLWithPath: "/usr/local/share/kanjo/cli")]
    }

    /// 目录下有 `kanjo/` 包才算 CLI 目录。
    public static func isCLIDirectory(_ url: URL, fileManager: FileManager = .default) -> Bool {
        var isDir: ObjCBool = false
        return fileManager.fileExists(atPath: url.appendingPathComponent("kanjo").path, isDirectory: &isDir)
            && isDir.boolValue
    }

    /// 设置里工作目录留空时用的 CLI 目录：仓库里的 cli/（仅 DEBUG），其次 `~/.local/share/kanjo/cli`、
    /// `/usr/local/share/kanjo/cli`。都没有就是 nil。
    public static func resolvedCLIDirectory(candidates: [URL]? = nil,
                                            fileManager: FileManager = .default) -> URL? {
        (candidates ?? [cliDirectory].compactMap { $0 } + installedCLIDirectories())
            .first { isCLIDirectory($0, fileManager: fileManager) }
    }

    /// 找得到 CLI 就默认走 CLI 取数，找不到（打包后的 .app 且没跑过 install.sh）就退回示例 JSON。
    public static var cliDirectoryExists: Bool {
        resolvedCLIDirectory() != nil
    }

    /// 开发开关 `--disk-data <path>`：磁盘页读这个 JSON，不跑 `kanjo disk`。
    public static func diskDataOverride(arguments: [String] = CommandLine.arguments) -> URL? {
        guard let i = arguments.firstIndex(of: "--disk-data"), i + 1 < arguments.count else { return nil }
        return URL(fileURLWithPath: (arguments[i + 1] as NSString).expandingTildeInPath)
    }

    /// 命令行覆盖：`--data <path>` 优先，其次环境变量 `KANJO_DATA`。
    public static func dataOverride(arguments: [String] = CommandLine.arguments,
                                    environment: [String: String] = ProcessInfo.processInfo.environment) -> URL? {
        if let i = arguments.firstIndex(of: "--data"), i + 1 < arguments.count {
            return URL(fileURLWithPath: (arguments[i + 1] as NSString).expandingTildeInPath)
        }
        if let env = environment["KANJO_DATA"], !env.isEmpty {
            return URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
        }
        return nil
    }
}
