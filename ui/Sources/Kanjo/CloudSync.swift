import Foundation
import KanjoCore
import SwiftUI
import os

#if canImport(CloudKit)
import CloudKit

@MainActor
final class CloudSyncStore: ObservableObject {
    static let shared = CloudSyncStore()
    static let logger = Logger(subsystem: "com.lanshuagent.kanjo", category: "sync")

    enum Status: Equatable {
        case off
        case waitingForICloud
        case uploaded(Date)
        case failed(String)
    }

    @Published private(set) var status: Status

    private let defaults: UserDefaults
    private var inFlight = false
    private var pendingReport: UsageReport?
    private var forceNextUpload = false

    init(defaults: UserDefaults = AppDefaults.store) {
        self.defaults = defaults
        if defaults.bool(forKey: SettingsKeys.cloudSyncEnabled) {
            status = Self.storedUploadDate(defaults: defaults).map(Status.uploaded) ?? .waitingForICloud
        } else {
            status = .off
        }
    }

    var isEnabled: Bool {
        defaults.bool(forKey: SettingsKeys.cloudSyncEnabled)
    }

    var hideProjectNames: Bool {
        defaults.bool(forKey: SettingsKeys.cloudSyncHideProjectNames)
    }

    func setEnabled(_ enabled: Bool) {
        guard enabled else {
            status = .off
            return
        }
        status = Self.storedUploadDate(defaults: defaults).map(Status.uploaded) ?? .waitingForICloud
    }

    func resetUploadState() {
        defaults.removeObject(forKey: SettingsKeys.cloudSyncLastUploadHash)
        defaults.removeObject(forKey: SettingsKeys.cloudSyncLastFingerprint)
        forceNextUpload = true
    }

    func reportDidRefresh(_ report: UsageReport) {
        guard isEnabled else {
            status = .off
            Self.logger.info("sync skipped: toggle off")
            return
        }
        guard !SnapshotConfig.isSnapshotMode else {
            Self.logger.info("sync skipped: snapshot mode")
            return
        }
        guard AppDefaults.suiteName() == nil else {
            Self.logger.info("sync skipped: test defaults suite")
            return
        }
        Task { await performSync(report) }
    }

    private func performSync(_ report: UsageReport) async {
        if inFlight {
            Self.logger.info("sync deferred: another sync is in flight")
            pendingReport = report
            return
        }
        inFlight = true
        defer {
            inFlight = false
            if let next = pendingReport {
                pendingReport = nil
                Task { await performSync(next) }
            }
        }

        do {
            guard isEnabled else {
                status = .off
                Self.logger.info("sync skipped: toggle off")
                return
            }

            let fingerprint = SyncFingerprint.make(for: report)
            let force = forceNextUpload
            if force {
                forceNextUpload = false
            }
            if !force,
               let lastUploaded = Self.storedUploadDate(defaults: defaults),
               Date().timeIntervalSince(lastUploaded) < 15 * 60,
               defaults.string(forKey: SettingsKeys.cloudSyncLastFingerprint) == fingerprint {
                let minutes = Int(Date().timeIntervalSince(lastUploaded) / 60)
                Self.logger.info("sync skipped: fingerprint unchanged, last upload \(minutes, privacy: .public) min ago")
                status = .uploaded(lastUploaded)
                return
            }
            if force {
                Self.logger.info("sync forced: upload state was reset")
            }

            guard CloudKitEntitlement.hasContainer() else {
                Self.logger.error("sync skipped: no CloudKit entitlement")
                status = .failed(L10n.tr("settings.sync.status.not_configured"))
                return
            }
            let account = try await accountStatus()
            guard account == .available else {
                Self.logger.info("sync skipped: iCloud account status \(Self.accountCode(account), privacy: .public)")
                status = .waitingForICloud
                return
            }
            Self.logger.info("sync started: iCloud account available")

            let source = CLIDataSource(
                command: CLILaunch.command(defaults: defaults),
                workingDirectory: CLILaunch.workingDirectory(defaults: defaults)
            )
            Self.logger.info("export started: hide project names \(self.hideProjectNames, privacy: .public)")
            let exportStart = Date()
            let payload = try await source.loadMobileSnapshot(hideProjectNames: hideProjectNames)
            let exportMs = Int(Date().timeIntervalSince(exportStart) * 1000)
            Self.logger.info("export finished: bytes \(payload.count, privacy: .public), ms \(exportMs, privacy: .public)")
            let hash = SnapshotPayload.contentHash(fromGzip: payload)

            if hash == defaults.string(forKey: SettingsKeys.cloudSyncLastUploadHash) {
                Self.logger.info("hash unchanged: skipping upload")
                defaults.set(fingerprint, forKey: SettingsKeys.cloudSyncLastFingerprint)
                if let uploaded = Self.storedUploadDate(defaults: defaults) {
                    status = .uploaded(uploaded)
                }
                return
            }

            let mobileReport = try ReportDecoder.decode(Gzip.decompress(payload))
            let deviceID = SnapshotDevice.deviceID(defaults: defaults)
            let generatedAt = ReportDates.parseTimestamp(mobileReport.generatedAt) ?? Date()
            let snapshot = SnapshotRecord(
                deviceID: deviceID,
                deviceName: SnapshotDevice.deviceName,
                generatedAt: generatedAt,
                schemaVersion: mobileReport.schemaVersion,
                payload: payload
            )

            let fileManager = FileManager.default
            let caches = try fileManager.url(for: .cachesDirectory, in: .userDomainMask,
                                             appropriateFor: nil, create: true)
            let directory = caches.appendingPathComponent("CloudKitSync", isDirectory: true)
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
            let assetURL = directory.appendingPathComponent("\(deviceID)-\(UUID().uuidString).json.gz")
            try payload.write(to: assetURL, options: .atomic)
            defer { try? fileManager.removeItem(at: assetURL) }

            Self.logger.info("upload started: record \(snapshot.deviceID, privacy: .private), device \(snapshot.deviceName, privacy: .public), bytes \(payload.count, privacy: .public)")
            let uploadStart = Date()
            try await save(snapshot, payloadURL: assetURL, database: database())
            let uploadMs = Int(Date().timeIntervalSince(uploadStart) * 1000)
            Self.logger.info("upload succeeded: record \(snapshot.deviceID, privacy: .private), bytes \(payload.count, privacy: .public), ms \(uploadMs, privacy: .public)")

            let uploaded = Date()
            defaults.set(hash, forKey: SettingsKeys.cloudSyncLastUploadHash)
            defaults.set(fingerprint, forKey: SettingsKeys.cloudSyncLastFingerprint)
            defaults.set(uploaded.timeIntervalSince1970, forKey: SettingsKeys.cloudSyncLastUploadedAt)
            status = .uploaded(uploaded)
        } catch {
            Self.logFailure(error)
            if Self.isQuotaExceeded(error) {
                status = .failed(L10n.tr("settings.sync.status.quota_exceeded"))
            } else {
                let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                status = .failed(message)
            }
        }
    }

    /// iCloud 空间已满：CloudKit 可能直接报 quotaExceeded，也可能包在 partialFailure 里。
    private static func isQuotaExceeded(_ error: Error) -> Bool {
        guard let ckError = error as? CKError else { return false }
        if ckError.code == .quotaExceeded { return true }
        if ckError.code == .partialFailure, let items = ckError.partialErrorsByItemID {
            return items.values.contains { ($0 as? CKError)?.code == .quotaExceeded }
        }
        return false
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

    private static func logFailure(_ error: Error) {
        if let ckError = error as? CKError {
            logger.error("sync failed: CKError code \(ckError.code.rawValue, privacy: .public), description \(ckError.localizedDescription, privacy: .private)")
        } else {
            logger.error("sync failed: \(String(describing: type(of: error)), privacy: .public), description \(error.localizedDescription, privacy: .private)")
        }
    }

    private func database() -> CKDatabase {
        CKContainer(identifier: SnapshotRecord.containerIdentifier).privateCloudDatabase
    }

    private func accountStatus() async throws -> CKAccountStatus {
        let container = CKContainer(identifier: SnapshotRecord.containerIdentifier)
        return try await withCheckedThrowingContinuation { continuation in
            container.accountStatus { status, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: status)
                }
            }
        }
    }

    private func save(_ snapshot: SnapshotRecord, payloadURL: URL, database: CKDatabase) async throws {
        let recordID = CKRecord.ID(recordName: snapshot.deviceID)
        var existing: CKRecord?
        do {
            existing = try await fetch(recordID, in: database)
        } catch let error as CKError where error.code == .unknownItem {
            Self.logger.info("no existing record for \(snapshot.deviceID, privacy: .private); creating new one")
            existing = nil
        }

        let record = snapshot.makeRecord(payloadURL: payloadURL, existing: existing)
        let operation = CKModifyRecordsOperation(recordsToSave: [record], recordIDsToDelete: nil)
        operation.savePolicy = .changedKeys
        operation.isAtomic = true
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            operation.modifyRecordsResultBlock = { result in
                switch result {
                case .success:
                    continuation.resume()
                case .failure(let error):
                    continuation.resume(throwing: error)
                }
            }
            database.add(operation)
        }
    }

    private func fetch(_ recordID: CKRecord.ID, in database: CKDatabase) async throws -> CKRecord? {
        let operation = CKFetchRecordsOperation(recordIDs: [recordID])
        operation.desiredKeys = [SnapshotRecord.fieldGeneratedAt]
        return try await withCheckedThrowingContinuation { continuation in
            var record: CKRecord?
            var recordError: Error?
            operation.perRecordResultBlock = { _, result in
                switch result {
                case .success(let fetched):
                    record = fetched
                case .failure(let error):
                    recordError = error
                }
            }
            operation.fetchRecordsResultBlock = { result in
                switch result {
                case .success:
                    if let record {
                        continuation.resume(returning: record)
                    } else if let error = recordError as? CKError, error.code == .unknownItem {
                        continuation.resume(returning: nil)
                    } else if let recordError {
                        continuation.resume(throwing: recordError)
                    } else {
                        continuation.resume(returning: nil)
                    }
                case .failure(let error):
                    continuation.resume(throwing: error)
                }
            }
            database.add(operation)
        }
    }

    private static func storedUploadDate(defaults: UserDefaults) -> Date? {
        let value = defaults.double(forKey: SettingsKeys.cloudSyncLastUploadedAt)
        return value > 0 ? Date(timeIntervalSince1970: value) : nil
    }
}

#else

@MainActor
final class CloudSyncStore: ObservableObject {
    static let shared = CloudSyncStore()

    enum Status: Equatable {
        case off
        case waitingForICloud
        case uploaded(Date)
        case failed(String)
    }

    @Published private(set) var status: Status = .off

    var isEnabled: Bool { false }
    var hideProjectNames: Bool { false }

    func setEnabled(_ enabled: Bool) {}
    func reportDidRefresh(_ report: UsageReport) {}
}

#endif
