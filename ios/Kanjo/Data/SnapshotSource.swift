import CloudKit
import Foundation
import KanjoCore
import os

enum SyncLog {
    static let sync = Logger(subsystem: "com.lanshuagent.kanjo", category: "sync")
}

/// 手机端只读快照的来源：CloudKit 私有库，或内置示例。
protocol SnapshotSource {
    /// nil 表示还没有任何快照（显示空状态）。
    func load() async throws -> UsageReport?
    var lastDeviceName: String? { get }
    /// 这台 iPhone 的 iCloud 账户识别码，与 Mac 设置页对照。
    var lastAccountCode: String? { get }
}

extension SnapshotSource {
    var lastDeviceName: String? { nil }
    var lastAccountCode: String? { nil }
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
    private(set) var lastAccountCode: String?

    init(containerIdentifier: String = SnapshotRecord.containerIdentifier) {
        let container = CKContainer(identifier: containerIdentifier)
        self.container = container
        self.database = container.privateCloudDatabase
    }

    func load() async throws -> UsageReport? {
        lastDeviceName = nil
        lastAccountCode = nil

        let kvsSnapshot = UbiquitousSnapshotStore.load()
        if let kvsSnapshot {
            SyncLog.sync.info("kvs snapshot found: device \(kvsSnapshot.deviceName, privacy: .public), bytes \(kvsSnapshot.payload?.count ?? 0, privacy: .public)")
        }

        SyncLog.sync.info("fetch started: CloudKit private database")
        let account: CKAccountStatus
        do {
            account = try await accountStatus()
        } catch {
            Self.logFailure("account status failed", error)
            if let kvsSnapshot, let payload = kvsSnapshot.payload {
                SyncLog.sync.info("falling back to KVS snapshot due to account status error")
                return try decodeReport(payload: payload, deviceName: kvsSnapshot.deviceName)
            }
            throw SnapshotSourceError.cloudKit(error)
        }
        guard account == .available else {
            SyncLog.sync.info("fetch skipped: iCloud account status \(Self.accountCode(account), privacy: .public)")
            if let kvsSnapshot, let payload = kvsSnapshot.payload {
                SyncLog.sync.info("falling back to KVS snapshot due to unavailable iCloud account")
                return try decodeReport(payload: payload, deviceName: kvsSnapshot.deviceName)
            }
            return nil
        }
        lastAccountCode = await ICloudAccountCode.fetch()

        let records: [CKRecord]
        do {
            records = try await fetchMetadata()
        } catch {
            Self.logFailure("fetch failed", error)
            if let kvsSnapshot, let payload = kvsSnapshot.payload {
                SyncLog.sync.info("falling back to KVS snapshot due to fetchMetadata error")
                return try decodeReport(payload: payload, deviceName: kvsSnapshot.deviceName)
            }
            throw SnapshotSourceError.cloudKit(error)
        }
        SyncLog.sync.info("fetch finished: \(records.count, privacy: .public) records found")

        let snapshots = records.compactMap { SnapshotRecord.metadata(from: $0) }
        let cloudKitNewest = SnapshotRecord.newest(in: snapshots)

        if let kvsSnapshot, let kvsPayload = kvsSnapshot.payload {
            let useKvs: Bool
            if let ck = cloudKitNewest {
                useKvs = kvsSnapshot.generatedAt >= ck.generatedAt
            } else {
                useKvs = true
            }
            if useKvs {
                SyncLog.sync.info("chosen KVS snapshot: device \(kvsSnapshot.deviceName, privacy: .public), generatedAt \(kvsSnapshot.generatedAt, privacy: .public)")
                return try decodeReport(payload: kvsPayload, deviceName: kvsSnapshot.deviceName)
            }
        }

        guard let newest = cloudKitNewest else {
            SyncLog.sync.info("fetch finished: no usable snapshot records")
            return nil
        }
        SyncLog.sync.info("chosen record: device \(newest.deviceName, privacy: .public), generatedAt \(newest.generatedAt, privacy: .public)")

        let payload: Data?
        do {
            payload = try await downloadPayload(recordID: CKRecord.ID(recordName: newest.deviceID))
        } catch {
            Self.logFailure("download failed", error)
            if let kvsSnapshot, let kvsPayload = kvsSnapshot.payload {
                SyncLog.sync.info("falling back to KVS snapshot due to download error")
                return try decodeReport(payload: kvsPayload, deviceName: kvsSnapshot.deviceName)
            }
            throw SnapshotSourceError.cloudKit(error)
        }
        guard let payload else {
            if let kvsSnapshot, let kvsPayload = kvsSnapshot.payload {
                SyncLog.sync.info("falling back to KVS snapshot due to missing payload asset")
                return try decodeReport(payload: kvsPayload, deviceName: kvsSnapshot.deviceName)
            }
            SyncLog.sync.error("download failed: no payload asset")
            throw SnapshotSourceError.missingPayload
        }
        SyncLog.sync.info("download finished: bytes \(payload.count, privacy: .public)")

        return try decodeReport(payload: payload, deviceName: newest.deviceName)
    }

    private func decodeReport(payload: Data, deviceName: String) throws -> UsageReport {
        lastDeviceName = deviceName
        do {
            let json = try Gzip.decompress(payload)
            SyncLog.sync.info("decompress finished: bytes \(json.count, privacy: .public)")
            let report = try ReportDecoder.decode(json)
            SyncLog.sync.info("decode finished: \(report.projects.count, privacy: .public) projects")
            return report
        } catch {
            Self.logFailure("decompress/decode failed", error)
            throw error
        }
    }

    private static func accountCode(_ status: CKAccountStatus) -> String {
        switch status {
        case .available: return "available"
        case .noAccount: return "noAccount"
        case .restricted: return "restricted"
        case .couldNotDetermine: return "couldNotDetermine"
        case .temporarilyUnavailable: return "temporarilyUnavailable"
        @unknown default: return "unknown"
        }
    }

    private static func logFailure(_ context: String, _ error: Error) {
        if let ckError = error as? CKError {
            SyncLog.sync.error("\(context, privacy: .public): CKError code \(ckError.code.rawValue, privacy: .public), description \(ckError.localizedDescription, privacy: .private)")
        } else {
            SyncLog.sync.error("\(context, privacy: .public): \(String(describing: type(of: error)), privacy: .public), description \(error.localizedDescription, privacy: .private)")
        }
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
        let latestRecord: CKRecord?
        do {
            latestRecord = try await fetchLatestRecord()
            if let latestRecord {
                SyncLog.sync.info("fetch latest record finished: \(latestRecord.recordID.recordName, privacy: .public)")
            } else {
                SyncLog.sync.info("fetch latest record finished: no latest record")
            }
        } catch {
            SyncLog.sync.info("fetch latest record failed: \(error.localizedDescription, privacy: .private)")
            latestRecord = nil
        }

        let queryRecords: [CKRecord]
        do {
            queryRecords = try await fetchMetadataByQuery()
        } catch let error as CKError {
            if latestRecord != nil {
                SyncLog.sync.info("query supplementary fetch ignored error: CKError code \(error.code.rawValue, privacy: .public), description \(error.localizedDescription, privacy: .private)")
                queryRecords = []
            } else if error.code == .unknownItem || error.code == .invalidArguments {
                SyncLog.sync.info("query fetch ignored error: CKError code \(error.code.rawValue, privacy: .public), description \(error.localizedDescription, privacy: .private)")
                queryRecords = []
            } else {
                throw error
            }
        }

        var combined: [CKRecord] = []
        var seenIDs = Set<String>()
        if let latestRecord {
            combined.append(latestRecord)
            seenIDs.insert(latestRecord.recordID.recordName)
        }
        for record in queryRecords {
            if seenIDs.insert(record.recordID.recordName).inserted {
                combined.append(record)
            }
        }

        return combined
    }

    private func fetchLatestRecord() async throws -> CKRecord? {
        let recordID = CKRecord.ID(recordName: SnapshotRecord.latestRecordName)
        let operation = CKFetchRecordsOperation(recordIDs: [recordID])
        operation.desiredKeys = [
            SnapshotRecord.fieldDeviceName,
            SnapshotRecord.fieldGeneratedAt,
            SnapshotRecord.fieldSchemaVersion,
        ]
        return try await withCheckedThrowingContinuation { continuation in
            let lock = NSLock()
            var fetchedRecord: CKRecord?
            var recordError: Error?

            operation.perRecordResultBlock = { _, result in
                lock.lock()
                defer { lock.unlock() }
                switch result {
                case .success(let record):
                    fetchedRecord = record
                case .failure(let error):
                    recordError = error
                }
            }

            operation.fetchRecordsResultBlock = { result in
                lock.lock()
                let record = fetchedRecord
                let err = recordError
                lock.unlock()

                switch result {
                case .success:
                    if let record {
                        continuation.resume(returning: record)
                    } else if let error = err as? CKError, error.code == .unknownItem {
                        continuation.resume(returning: nil)
                    } else if let err {
                        continuation.resume(throwing: err)
                    } else {
                        continuation.resume(returning: nil)
                    }
                case .failure(let error):
                    if let ckError = error as? CKError {
                        if ckError.code == .unknownItem {
                            continuation.resume(returning: nil)
                            return
                        }
                        if ckError.code == .partialFailure,
                           let itemError = ckError.partialErrorsByItemID?[recordID] as? CKError,
                           itemError.code == .unknownItem {
                            continuation.resume(returning: nil)
                            return
                        }
                    }
                    continuation.resume(throwing: error)
                }
            }

            database.add(operation)
        }
    }

    private func fetchMetadataByQuery() async throws -> [CKRecord] {
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
            SyncLog.sync.info("fetch finished: Snapshot record type not created yet")
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
