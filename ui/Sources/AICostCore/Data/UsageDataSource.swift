import Foundation

public protocol UsageDataSource {
    func load() async throws -> UsageReport
}

public enum DataSourceError: LocalizedError, Equatable {
    case fileNotFound(String)
    case unreadable(String, String)
    case emptyInput(String)
    case invalidJSON(String)
    case contractMismatch(String, schemaVersion: Int?)
    case commandFailed(command: String, status: Int32, stderr: String)
    case commandTimedOut(command: String, seconds: Int)
    case launchFailed(String)

    public var errorDescription: String? {
        switch self {
        case .fileNotFound(let p):
            return "Data file not found: \(p)"
        case .unreadable(let p, let why):
            return "Cannot read \(p): \(why)"
        case .emptyInput(let what):
            return "\(what) is empty — expected aicost export JSON."
        case .invalidJSON(let why):
            return "Not valid JSON: \(why)"
        case .contractMismatch(let why, let v):
            var s = "JSON does not match the aicost data contract: \(why)"
            if let v, v > supportedSchemaVersion {
                s += "\n(schema_version \(v) is newer than this app supports (\(supportedSchemaVersion)); update the app.)"
            }
            return s
        case .commandFailed(let c, let status, let err):
            let tail = err.trimmingCharacters(in: .whitespacesAndNewlines)
            return "Command exited with status \(status): \(c)" + (tail.isEmpty ? "" : "\n\(tail.suffix(600))")
        case .commandTimedOut(let c, let s):
            return "Command timed out after \(s)s: \(c)"
        case .launchFailed(let why):
            return "Could not start command: \(why)"
        }
    }
}

public enum ReportDecoder {
    /// 解码契约 JSON。错误信息尽量指出出错的字段路径。
    public static func decode(_ data: Data) throws -> UsageReport {
        if data.allSatisfy({ $0 == 0x20 || $0 == 0x0A || $0 == 0x0D || $0 == 0x09 }) {
            throw DataSourceError.emptyInput("Input")
        }
        let any: Any
        do {
            any = try JSONSerialization.jsonObject(with: data)
        } catch {
            let ns = error as NSError
            let detail = (ns.userInfo[NSDebugDescriptionErrorKey] as? String) ?? ns.localizedDescription
            throw DataSourceError.invalidJSON(detail)
        }
        guard let obj = any as? [String: Any] else {
            throw DataSourceError.contractMismatch("top level must be a JSON object", schemaVersion: nil)
        }
        let version = obj["schema_version"] as? Int
        do {
            return try JSONDecoder().decode(UsageReport.self, from: data)
        } catch let e as DecodingError {
            throw DataSourceError.contractMismatch(describe(e), schemaVersion: version)
        }
    }

    static func describe(_ e: DecodingError) -> String {
        func path(_ ctx: DecodingError.Context, _ extra: CodingKey? = nil) -> String {
            var keys = ctx.codingPath
            if let extra { keys.append(extra) }
            if keys.isEmpty { return "(root)" }
            return keys.map { k in k.intValue.map { "[\($0)]" } ?? ".\(k.stringValue)" }
                .joined().trimmingCharacters(in: CharacterSet(charactersIn: "."))
        }
        switch e {
        case .keyNotFound(let key, let ctx):
            return "missing field \(path(ctx, key))"
        case .typeMismatch(let type, let ctx):
            return "wrong type at \(path(ctx)) (expected \(type))"
        case .valueNotFound(let type, let ctx):
            return "null at \(path(ctx)) (expected \(type))"
        case .dataCorrupted(let ctx):
            return "\(ctx.debugDescription) at \(path(ctx))"
        @unknown default:
            return String(describing: e)
        }
    }
}
