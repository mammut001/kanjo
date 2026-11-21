import CryptoKit
import Foundation

#if canImport(CloudKit)
import CloudKit
#if os(macOS)
import Security
#endif
#endif

public struct SnapshotRecord: Equatable {
    public static let containerIdentifier = "iCloud.com.lanshuagent.kanjo"
    public static let recordType = "Snapshot"
    public static let zoneName = "_defaultZone"
    public static let latestRecordName = "latest"

    public static let fieldDeviceName = "deviceName"
    public static let fieldGeneratedAt = "generatedAt"
    public static let fieldSchemaVersion = "schemaVersion"
    public static let fieldPayload = "payload"

    public var deviceID: String
    public var deviceName: String
    public var generatedAt: Date
    public var schemaVersion: Int
    public var payload: Data?

    public init(deviceID: String, deviceName: String, generatedAt: Date,
                schemaVersion: Int, payload: Data? = nil) {
        self.deviceID = deviceID
        self.deviceName = deviceName
        self.generatedAt = generatedAt
        self.schemaVersion = schemaVersion
        self.payload = payload
    }

    public func fieldValues(payloadValue: Any) -> [String: Any] {
        [
            Self.fieldDeviceName: deviceName,
            Self.fieldGeneratedAt: generatedAt,
            Self.fieldSchemaVersion: schemaVersion,
            Self.fieldPayload: payloadValue,
        ]
    }

    public static func parse(recordName: String, fields: [String: Any], payload: Data? = nil) -> SnapshotRecord? {
        guard let deviceName = fields[fieldDeviceName] as? String,
              let generatedAt = fields[fieldGeneratedAt] as? Date,
              let schemaVersion = (fields[fieldSchemaVersion] as? NSNumber)?.intValue else {
            return nil
        }
        return SnapshotRecord(deviceID: recordName, deviceName: deviceName,
                              generatedAt: generatedAt, schemaVersion: schemaVersion,
                              payload: payload)
    }

    public static func newest(in records: [SnapshotRecord]) -> SnapshotRecord? {
        records.max { lhs, rhs in
            if lhs.generatedAt != rhs.generatedAt {
                return lhs.generatedAt < rhs.generatedAt
            }
            return lhs.deviceID < rhs.deviceID
        }
    }
}

public enum SnapshotPayload {
    public static func canonicalData(fromGzip data: Data) -> Data? {
        guard let json = try? Gzip.decompress(data),
              var object = try? JSONSerialization.jsonObject(with: json) as? [String: Any] else {
            return nil
        }
        object.removeValue(forKey: "generated_at")
        return try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    }

    public static func contentHash(fromGzip data: Data) -> String {
        let canonical = canonicalData(fromGzip: data) ?? data
        return SHA256.hash(data: canonical).map { String(format: "%02x", $0) }.joined()
    }
}

public enum UbiquitousSnapshotStore {
    public static let kvStoreIdentifier = "Z5D5N7CU6L.com.lanshuagent.kanjo"
    public static let chunkSize = 48 * 1024
    public static let maxPayloadBytes = 900 * 1024

    public static let keyDeviceID = "kanjo.snapshot.deviceID"
    public static let keyDeviceName = "kanjo.snapshot.deviceName"
    public static let keyGeneratedAt = "kanjo.snapshot.generatedAt"
    public static let keySchemaVersion = "kanjo.snapshot.schemaVersion"
    public static let keyChunkCount = "kanjo.snapshot.chunkCount"

    public static func chunkKey(_ index: Int) -> String {
        "kanjo.snapshot.chunk.\(index)"
    }

    public static func splitPayload(_ data: Data, chunkSize: Int = chunkSize) -> [Data] {
        guard !data.isEmpty, chunkSize > 0 else { return [] }
        var chunks: [Data] = []
        var offset = 0
        while offset < data.count {
            let length = min(chunkSize, data.count - offset)
            chunks.append(data.subdata(in: offset..<(offset + length)))
            offset += length
        }
        return chunks
    }

    public static func save(_ snapshot: SnapshotRecord, to store: NSUbiquitousKeyValueStore = .default) -> Bool {
        guard let payload = snapshot.payload, !payload.isEmpty, payload.count <= maxPayloadBytes else {
            return false
        }
        let chunks = splitPayload(payload)
        guard !chunks.isEmpty else { return false }

        let previousCount = Int(store.longLong(forKey: keyChunkCount))
        if previousCount > chunks.count {
            for i in chunks.count..<previousCount {
                store.removeObject(forKey: chunkKey(i))
            }
        }

        for (index, chunk) in chunks.enumerated() {
            store.set(chunk, forKey: chunkKey(index))
        }

        store.set(snapshot.deviceID, forKey: keyDeviceID)
        store.set(snapshot.deviceName, forKey: keyDeviceName)
        store.set(snapshot.generatedAt.timeIntervalSince1970, forKey: keyGeneratedAt)
        store.set(Int64(snapshot.schemaVersion), forKey: keySchemaVersion)
        store.set(Int64(chunks.count), forKey: keyChunkCount)

        _ = store.synchronize()
        return true
    }

    public static func load(from store: NSUbiquitousKeyValueStore = .default) -> SnapshotRecord? {
        _ = store.synchronize()

        guard let deviceID = store.string(forKey: keyDeviceID), !deviceID.isEmpty,
              let deviceName = store.string(forKey: keyDeviceName), !deviceName.isEmpty else {
            return nil
        }

        let generatedAtSeconds = store.double(forKey: keyGeneratedAt)
        let schemaVersion = Int(store.longLong(forKey: keySchemaVersion))
        let chunkCount = Int(store.longLong(forKey: keyChunkCount))

        guard generatedAtSeconds > 0, chunkCount > 0 else {
            return nil
        }

        var combined = Data()
        for i in 0..<chunkCount {
            guard let chunk = store.data(forKey: chunkKey(i)) else {
                return nil
            }
            combined.append(chunk)
        }

        return SnapshotRecord(
            deviceID: deviceID,
            deviceName: deviceName,
            generatedAt: Date(timeIntervalSince1970: generatedAtSeconds),
            schemaVersion: schemaVersion,
            payload: combined
        )
    }
}

public enum SnapshotDevice {
    public static func deviceID(defaults: UserDefaults = AppDefaults.store) -> String {
        if let existing = defaults.string(forKey: SettingsKeys.cloudSyncDeviceID), !existing.isEmpty {
            return existing
        }
        let generated = UUID().uuidString
        defaults.set(generated, forKey: SettingsKeys.cloudSyncDeviceID)
        return generated
    }

    #if os(macOS)
    public static var deviceName: String {
        Host.current().localizedName ?? ProcessInfo.processInfo.hostName
    }
    #endif
}

/// iCloud 账户识别码：CloudKit 用户记录 ID 的 SHA-256 前 6 位。
/// Apple 不给 app 读 Apple ID 邮箱，用它在 Mac 和手机上核对是不是同一个账户；推不回原 ID。
public enum ICloudAccountCode {
    public static func make(userRecordName: String) -> String {
        SHA256.hash(data: Data(userRecordName.utf8)).prefix(3).map { String(format: "%02x", $0) }.joined()
    }

    #if canImport(CloudKit)
    /// 读当前 iCloud 账户在该容器下的识别码；未登录或出错时返回 nil。
    public static func fetch(containerIdentifier: String = SnapshotRecord.containerIdentifier) async -> String? {
        guard let recordID = try? await CKContainer(identifier: containerIdentifier).userRecordID() else {
            return nil
        }
        return make(userRecordName: recordID.recordName)
    }
    #endif
}

#if canImport(CloudKit)
public enum CloudKitEntitlement {
    #if os(macOS)
    public static func hasContainer(_ identifier: String = SnapshotRecord.containerIdentifier) -> Bool {
        guard let task = SecTaskCreateFromSelf(nil) else { return false }
        let containerKey = "com.apple.developer.icloud-container-identifiers" as CFString
        let servicesKey = "com.apple.developer.icloud-services" as CFString
        guard let containerValue = SecTaskCopyValueForEntitlement(task, containerKey, nil),
              let identifiers = containerValue as? [String],
              identifiers.contains(identifier),
              let servicesValue = SecTaskCopyValueForEntitlement(task, servicesKey, nil),
              let services = servicesValue as? [String],
              services.contains("CloudKit") else {
            return false
        }
        return true
    }
    #else
    public static func hasContainer(_ identifier: String = SnapshotRecord.containerIdentifier) -> Bool {
        true
    }
    #endif
}

public extension SnapshotRecord {
    func makeRecord(payloadURL: URL, existing: CKRecord? = nil, recordName: String? = nil) -> CKRecord {
        let record = existing ?? CKRecord(
            recordType: Self.recordType,
            recordID: CKRecord.ID(recordName: recordName ?? deviceID)
        )
        record[Self.fieldDeviceName] = deviceName as CKRecordValue
        record[Self.fieldGeneratedAt] = generatedAt as CKRecordValue
        record[Self.fieldSchemaVersion] = schemaVersion as CKRecordValue
        record[Self.fieldPayload] = CKAsset(fileURL: payloadURL)
        return record
    }

    static func metadata(from record: CKRecord) -> SnapshotRecord? {
        guard let deviceName = record[Self.fieldDeviceName] as? String,
              let generatedAt = record[Self.fieldGeneratedAt] as? Date,
              let schemaVersion = (record[Self.fieldSchemaVersion] as? NSNumber)?.intValue else {
            return nil
        }
        return SnapshotRecord(deviceID: record.recordID.recordName,
                              deviceName: deviceName,
                              generatedAt: generatedAt,
                              schemaVersion: schemaVersion)
    }
}
#endif
