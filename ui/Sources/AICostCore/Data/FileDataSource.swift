import Foundation

public struct FileDataSource: UsageDataSource {
    public let url: URL

    public init(url: URL) { self.url = url }

    public func load() async throws -> UsageReport {
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
        return try ReportDecoder.decode(data)
    }
}
