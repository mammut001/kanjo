import Foundation

/// 从设置里的导出命令推出磁盘命令。只替换最后一个独立的 `export`，
/// 这样前面的 `export PATH=...` 不会被改掉。
public enum DiskCommand {
    public static func report(from cliCommand: String, rescan: Bool = false) -> String {
        replacingExport(in: cliCommand, with: rescan ? "disk --json --rescan" : "disk --json")
            .trimmingCharacters(in: .whitespaces)
    }

    /// `disk clean <id>... [--older-than Nd] --dry-run|--yes`
    /// olderThan 为空时不带 `--older-than`。confirmed 为 false 时用 `--dry-run`。
    public static func clean(from cliCommand: String, ids: [String], olderThan: String?, confirmed: Bool) -> String {
        var parts = [replacingExport(in: cliCommand, with: "disk clean").trimmingCharacters(in: .whitespaces)]
        parts.append(contentsOf: ids.map(shellWord))
        if let olderThan, !olderThan.isEmpty {
            parts.append("--older-than")
            parts.append(shellWord(olderThan))
        }
        parts.append(confirmed ? "--yes" : "--dry-run")
        return parts.joined(separator: " ")
    }

    static func replacingExport(in command: String, with replacement: String) -> String {
        guard let range = lastExportToken(in: command) else { return command }
        var copy = command
        copy.replaceSubrange(range, with: replacement)
        return copy
    }

    /// 从后往前找作为独立单词的 `export`（前后不是字母、数字、`_` 或 `-`）。
    static func lastExportToken(in command: String) -> Range<String.Index>? {
        var searchEnd = command.endIndex
        while searchEnd > command.startIndex,
              let found = command.range(of: "export", options: .backwards, range: command.startIndex..<searchEnd) {
            let beforeOK = found.lowerBound == command.startIndex || !isTokenBody(command[command.index(before: found.lowerBound)])
            let afterOK = found.upperBound == command.endIndex || !isTokenBody(command[found.upperBound])
            if beforeOK && afterOK { return found }
            searchEnd = found.lowerBound
        }
        return nil
    }

    private static func isTokenBody(_ c: Character) -> Bool {
        c.isLetter || c.isNumber || c == "_" || c == "-"
    }

    /// 安全字符原样留下，其余用单引号包起来，供 `/bin/zsh -l -c` 使用。
    static func shellWord(_ raw: String) -> String {
        let ok = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_:./")
        if !raw.isEmpty && raw.unicodeScalars.allSatisfy({ ok.contains($0) }) { return raw }
        return "'" + raw.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}

public protocol DiskSource {
    func load() async throws -> DiskReport
    func clean(ids: [String], olderThan: String?, confirmed: Bool) async throws -> CleanResult
}

/// 跑 `kanjo disk --json` 和 `kanjo disk clean`。命令从设置里的导出命令推导，工作目录与用量导出相同。
public struct DiskDataSource: DiskSource {
    public let cliCommand: String
    public let workingDirectory: URL?
    public let timeout: TimeInterval
    public let rescan: Bool

    public init(cliCommand: String, workingDirectory: URL? = nil, timeout: TimeInterval = 300, rescan: Bool = false) {
        self.cliCommand = cliCommand
        self.workingDirectory = workingDirectory
        self.timeout = timeout
        self.rescan = rescan
    }

    public var reportCommand: String { DiskCommand.report(from: cliCommand, rescan: rescan) }

    public func load() async throws -> DiskReport {
        try DiskDecoder.decode(try await run(reportCommand))
    }

    public func clean(ids: [String], olderThan: String?, confirmed: Bool) async throws -> CleanResult {
        let command = DiskCommand.clean(from: cliCommand, ids: ids, olderThan: olderThan, confirmed: confirmed)
        return try DiskDecoder.decodeClean(try await run(command))
    }

    private func run(_ command: String) async throws -> Data {
        let cwd = workingDirectory
        let timeout = self.timeout
        let (status, out, err, timedOut) = try await Task.detached(priority: .utility) {
            try CLIDataSource.run(command: command, cwd: cwd, timeout: timeout)
        }.value
        if timedOut { throw DataSourceError.commandTimedOut(command: command, seconds: Int(timeout)) }
        guard status == 0 else {
            throw DataSourceError.commandFailed(command: command, status: status,
                                                stderr: String(decoding: err, as: UTF8.self))
        }
        if out.isEmpty { throw DataSourceError.emptyInput("Command output") }
        return out
    }
}

/// `--disk-data` 指定的 JSON 文件。清理不会在这里动磁盘：没有 CLI 可调用，直接拒绝。
public struct FileDiskSource: DiskSource {
    public let url: URL

    public init(url: URL) { self.url = url }

    public func load() async throws -> DiskReport {
        let path = url.path
        guard FileManager.default.fileExists(atPath: path) else {
            throw DataSourceError.fileNotFound(path)
        }
        let data: Data
        do {
            data = try Data(contentsOf: url)
        } catch {
            throw DataSourceError.unreadable(path, error.localizedDescription)
        }
        if data.isEmpty { throw DataSourceError.emptyInput(url.lastPathComponent) }
        return try DiskDecoder.decode(data)
    }

    public func clean(ids: [String], olderThan: String?, confirmed: Bool) async throws -> CleanResult {
        _ = (ids, olderThan, confirmed)
        throw DataSourceError.launchFailed(
            "Disk cleanup only runs through the kanjo CLI (disk clean). This report was loaded from a JSON file, so nothing was moved.")
    }
}

public enum DiskDecoder {
    public static func decode(_ data: Data) throws -> DiskReport {
        try decodeJSON(data, emptyWhat: "Disk report")
    }

    public static func decodeClean(_ data: Data) throws -> CleanResult {
        try decodeJSON(data, emptyWhat: "Clean result")
    }

    private static func decodeJSON<T: Decodable>(_ data: Data, emptyWhat: String) throws -> T {
        if data.isEmpty || data.allSatisfy({ $0 == 0x20 || $0 == 0x0A || $0 == 0x0D || $0 == 0x09 }) {
            throw DataSourceError.emptyInput(emptyWhat)
        }
        let any: Any
        do {
            any = try JSONSerialization.jsonObject(with: data)
        } catch {
            let ns = error as NSError
            let detail = (ns.userInfo[NSDebugDescriptionErrorKey] as? String) ?? ns.localizedDescription
            throw DataSourceError.invalidJSON(detail)
        }
        guard any is [String: Any] else {
            throw DataSourceError.contractMismatch("top level must be a JSON object", schemaVersion: nil)
        }
        let version = (any as? [String: Any])?["schema_version"] as? Int
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch let e as DecodingError {
            throw DataSourceError.contractMismatch(ReportDecoder.describe(e), schemaVersion: version)
        }
    }
}
