import CloudKit
import Foundation
import KanjoCore

/// 手机端只读快照的来源：CloudKit 私有库，或内置示例。
protocol SnapshotSource {
    /// nil 表示还没有任何快照（显示空状态）。
    func load() async throws -> UsageReport?
    var lastDeviceName: String? { get }
}

extension SnapshotSource {
    var lastDeviceName: String? { nil }
}

/// 读 App bundle 里的 sample-snapshot.json（由 ui/fixtures/sample.json 复制而来）。
struct BundledSampleSnapshotSource: SnapshotSource {
    var bundle: Bundle = .main
    var resourceName = "sample-snapshot"

    func load() async throws -> UsageReport? {
        guard let url = bundle.url(forResource: resourceName, withExtension: "json") else {
            return nil
        }
        let data = try Data(contentsOf: url)
        return try ReportDecoder.decode(data)
    }
}

enum SnapshotSourceError: LocalizedError {
    case missingPayload
    case cloudKit(Error)

    var errorDescription: String? {
        switch self {
        case .missingPayload:
            return L10n.tr("ios.error.missing_payload")
        case .cloudKit(let error):
            return (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}

final class CloudKitSnapshotSource: SnapshotSource {
    private let container: CKContainer
    private let database: CKDatabase
    private(set) var lastDeviceName: String?

    init(containerIdentifier: String = SnapshotRecord.containerIdentifier) {
        let container = CKContainer(identifier: containerIdentifier)
        self.container = container
        self.database = container.privateCloudDatabase
    }

    func load() async throws -> UsageReport? {
        lastDeviceName = nil
        let account: CKAccountStatus
        do {
            account = try await accountStatus()
        } catch {
            throw SnapshotSourceError.cloudKit(error)
        }
        guard account == .available else { return nil }

        let records: [CKRecord]
        do {
            records = try await fetchMetadata()
        } catch {
            throw SnapshotSourceError.cloudKit(error)
        }

        let snapshots = records.compactMap { SnapshotRecord.metadata(from: $0) }
        guard let newest = SnapshotRecord.newest(in: snapshots) else { return nil }
        lastDeviceName = newest.deviceName

        let payload: Data?
        do {
            payload = try await downloadPayload(recordID: CKRecord.ID(recordName: newest.deviceID))
        } catch {
            throw SnapshotSourceError.cloudKit(error)
        }
        guard let payload else { throw SnapshotSourceError.missingPayload }

        let json = try Gzip.decompress(payload)
        return try ReportDecoder.decode(json)
    }

    private func accountStatus() async throws -> CKAccountStatus {
        try await withCheckedThrowingContinuation { continuation in
            container.accountStatus { status, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: status)
                }
            }
        }
    }

    private func fetchMetadata() async throws -> [CKRecord] {
        let query = CKQuery(recordType: SnapshotRecord.recordType,
                            predicate: NSPredicate(value: true))
        var records: [CKRecord] = []
        var cursor: CKQueryOperation.Cursor?
        do {
            repeat {
                let page: ([CKRecord], CKQueryOperation.Cursor?)
                if let cursor {
                    page = try await fetchPage(cursor: cursor)
                } else {
                    page = try await fetchPage(query: query)
                }
                records.append(contentsOf: page.0)
                cursor = page.1
            } while cursor != nil
            return records
        } catch let error as CKError where error.code == .unknownItem {
            return []
        }
    }

    private func fetchPage(query: CKQuery) async throws -> ([CKRecord], CKQueryOperation.Cursor?) {
        try await runQueryOperation(CKQueryOperation(query: query))
    }

    private func fetchPage(cursor: CKQueryOperation.Cursor) async throws -> ([CKRecord], CKQueryOperation.Cursor?) {
        try await runQueryOperation(CKQueryOperation(cursor: cursor))
    }

    private func runQueryOperation(_ operation: CKQueryOperation) async throws -> ([CKRecord], CKQueryOperation.Cursor?) {
        operation.desiredKeys = [
            SnapshotRecord.fieldDeviceName,
            SnapshotRecord.fieldGeneratedAt,
            SnapshotRecord.fieldSchemaVersion,
        ]
        return try await withCheckedThrowingContinuation { continuation in
            let lock = NSLock()
            var records: [CKRecord] = []
            operation.recordMatchedBlock = { _, result in
                if case .success(let record) = result {
                    lock.lock()
                    records.append(record)
                    lock.unlock()
                }
            }
            operation.queryResultBlock = { result in
                lock.lock()
                let collected = records
                lock.unlock()
                switch result {
                case .success(let cursor):
                    continuation.resume(returning: (collected, cursor))
                case .failure(let error):
                    continuation.resume(throwing: error)
                }
            }
            database.add(operation)
        }
    }

    private func downloadPayload(recordID: CKRecord.ID) async throws -> Data? {
        let operation = CKFetchRecordsOperation(recordIDs: [recordID])
        operation.desiredKeys = [SnapshotRecord.fieldPayload]
        return try await withCheckedThrowingContinuation { continuation in
            let lock = NSLock()
            var payload: Data?
            operation.perRecordResultBlock = { _, result in
                guard case .success(let record) = result,
                      let asset = record[SnapshotRecord.fieldPayload] as? CKAsset,
                      let url = asset.fileURL else {
                    return
                }
                let data = try? Data(contentsOf: url)
                lock.lock()
                payload = data
                lock.unlock()
            }
            operation.fetchRecordsResultBlock = { result in
                lock.lock()
                let downloaded = payload
                lock.unlock()
                switch result {
                case .success:
                    continuation.resume(returning: downloaded)
                case .failure(let error):
                    continuation.resume(throwing: error)
                }
            }
            database.add(operation)
        }
    }
}
