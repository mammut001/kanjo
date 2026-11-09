#if os(macOS)

import Foundation

/// 执行外部命令（默认 `python3 -m kanjo export`），把 stdout 当契约 JSON 解码。
/// 命令经 `/bin/zsh -l -c` 执行，以便拿到用户 shell 的 PATH（从 Finder 启动的应用 PATH 很短）。
public struct CLIDataSource: UsageDataSource {
    public static let defaultCommand = "python3 -m kanjo export"

    public let command: String
    public let workingDirectory: URL?
    public let timeout: TimeInterval

    public init(command: String = CLIDataSource.defaultCommand, workingDirectory: URL? = nil, timeout: TimeInterval = 300) {
        self.command = command
        self.workingDirectory = workingDirectory
        self.timeout = timeout
    }

    public func load() async throws -> UsageReport {
        try await load(qualityOfService: .background)
    }

    public func load(qualityOfService: QualityOfService) async throws -> UsageReport {
        let command = self.command
        let cwd = self.workingDirectory
        let timeout = self.timeout
        let (status, out, err, timedOut) = try await Task.detached(priority: .utility) {
            try Self.run(command: command, cwd: cwd, timeout: timeout, qualityOfService: qualityOfService)
        }.value
        if timedOut { throw DataSourceError.commandTimedOut(command: command, seconds: Int(timeout)) }
        guard status == 0 else {
            throw DataSourceError.commandFailed(command: command, status: status,
                                                stderr: String(decoding: err, as: UTF8.self))
        }
        if out.isEmpty { throw DataSourceError.emptyInput("Command output") }
        return try ReportDecoder.decode(out)
    }

    public static func pathsCommand(_ command: String) -> String {
        let base = command.trimmingCharacters(in: .whitespacesAndNewlines)
        return DiskCommand.replacingExport(in: base, with: "paths --json")
    }

    public func loadPaths(qualityOfService: QualityOfService = .background) async throws -> [String: [String]] {
        let cmd = Self.pathsCommand(self.command)
        let cwd = self.workingDirectory
        let timeout = self.timeout
        let (status, out, err, timedOut) = try await Task.detached(priority: .utility) {
            try Self.run(command: cmd, cwd: cwd, timeout: timeout, qualityOfService: qualityOfService)
        }.value
        if timedOut { throw DataSourceError.commandTimedOut(command: cmd, seconds: Int(timeout)) }
        guard status == 0 else {
            throw DataSourceError.commandFailed(command: cmd, status: status,
                                                stderr: String(decoding: err, as: UTF8.self))
        }
        if out.isEmpty { return [:] }
        return try JSONDecoder().decode([String: [String]].self, from: out)
    }

    public static func mobileExportCommand(_ command: String, hideProjectNames: Bool) -> String {
        let base = command.trimmingCharacters(in: .whitespacesAndNewlines)
        let flags = hideProjectNames
            ? " --mobile --gzip --hide-project-names"
            : " --mobile --gzip"
        return base + flags
    }

    public func loadMobileSnapshot(hideProjectNames: Bool, qualityOfService: QualityOfService = .background) async throws -> Data {
        let command = Self.mobileExportCommand(self.command, hideProjectNames: hideProjectNames)
        let cwd = self.workingDirectory
        let timeout = self.timeout
        let (status, out, err, timedOut) = try await Task.detached(priority: .utility) {
            try Self.run(command: command, cwd: cwd, timeout: timeout, qualityOfService: qualityOfService)
        }.value
        if timedOut { throw DataSourceError.commandTimedOut(command: command, seconds: Int(timeout)) }
        guard status == 0 else {
            throw DataSourceError.commandFailed(command: command, status: status,
                                                stderr: String(decoding: err, as: UTF8.self))
        }
        if out.isEmpty { throw DataSourceError.emptyInput("Mobile export output") }
        return out
    }

    public static func run(command: String, cwd: URL?, timeout: TimeInterval, qualityOfService: QualityOfService = .background) throws -> (Int32, Data, Data, Bool) {
        let p = Process()
        p.qualityOfService = qualityOfService
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        p.arguments = ["-l", "-c", command]
        // 内置 Python 包属于签名资源，运行时不能写入 __pycache__。
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        p.environment = environment
        if let cwd {
            var isDir: ObjCBool = false
            guard FileManager.default.fileExists(atPath: cwd.path, isDirectory: &isDir), isDir.boolValue else {
                throw DataSourceError.launchFailed("working directory does not exist: \(cwd.path)")
            }
            p.currentDirectoryURL = cwd
        }
        let outPipe = Pipe(), errPipe = Pipe()
        p.standardOutput = outPipe
        p.standardError = errPipe
        p.standardInput = FileHandle.nullDevice

        // 两路管道并发读，避免输出过大时子进程写满管道而死锁。
        let group = DispatchGroup()
        var outData = Data(), errData = Data()
        group.enter()
        DispatchQueue.global().async { outData = outPipe.fileHandleForReading.readDataToEndOfFile(); group.leave() }
        group.enter()
        DispatchQueue.global().async { errData = errPipe.fileHandleForReading.readDataToEndOfFile(); group.leave() }

        do {
            try p.run()
        } catch {
            try? outPipe.fileHandleForWriting.close()
            try? errPipe.fileHandleForWriting.close()
            throw DataSourceError.launchFailed(error.localizedDescription)
        }

        var timedOut = false
        if group.wait(timeout: .now() + timeout) == .timedOut {
            timedOut = true
            p.terminate()
            _ = group.wait(timeout: .now() + 5)
        }
        p.waitUntilExit()
        return (p.terminationStatus, outData, errData, timedOut)
    }
}

#endif
