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
    func makeRecord(payloadURL: URL, existing: CKRecord? = nil) -> CKRecord {
        let record = existing ?? CKRecord(
            recordType: Self.recordType,
            recordID: CKRecord.ID(recordName: deviceID)
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
