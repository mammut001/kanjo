import Foundation
import XCTest
@testable import KanjoCore

final class SnapshotRecordTests: XCTestCase {
    private func data(hex: String) -> Data {
        var bytes: [UInt8] = []
        var index = hex.startIndex
        while index < hex.endIndex {
            let next = hex.index(index, offsetBy: 2)
            bytes.append(UInt8(hex[index..<next], radix: 16)!)
            index = next
        }
        return Data(bytes)
    }

    func testGzipDecompressesKnownPayload() throws {
        let compressed = data(hex: "1f8b08000000000002ffab56ca48cdc9c957b2522acf2fca4951aa0500d14109d811000000")
        let plain = try Gzip.decompress(compressed)
        XCTAssertEqual(String(decoding: plain, as: UTF8.self), #"{"hello":"world"}"#)
    }

    func testAccountCodeIsStableShortHex() {
        let code = ICloudAccountCode.make(userRecordName: "_0123456789abcdef")
        XCTAssertEqual(code.count, 6)
        XCTAssertTrue(code.allSatisfy(\.isHexDigit))
        XCTAssertEqual(code, ICloudAccountCode.make(userRecordName: "_0123456789abcdef"))
        XCTAssertNotEqual(code, ICloudAccountCode.make(userRecordName: "_fedcba9876543210"))
    }

    func testGzipRejectsNonGzipData() {
        XCTAssertThrowsError(try Gzip.decompress(Data("not gzip".utf8)))
    }

    func testContentHashIgnoresGeneratedAt() throws {
        let first = data(hex: "1f8b08000000000002ffab564a4fcd4b2d4a2c494d894f2c51b25232323032d3353004a21003032b308a52d2514a54b232d4514a022aa850aa0500f045042335000000")
        let second = data(hex: "1f8b08000000000002ffab564a4fcd4b2d4a2c494d894f2c51b25232323032d3353002a21003232b308a52d2514a54b232d4514a022aa850aa0500daeb1aec35000000")
        XCTAssertEqual(SnapshotPayload.contentHash(fromGzip: first),
                       SnapshotPayload.contentHash(fromGzip: second))

        let canonical = try XCTUnwrap(SnapshotPayload.canonicalData(fromGzip: first))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: canonical) as? [String: Any])
        XCTAssertNil(object["generated_at"])
        XCTAssertEqual(object["a"] as? Int, 1)
        XCTAssertEqual(object["b"] as? String, "x")
    }

    func testFieldDictionaryRoundTrip() throws {
        let generatedAt = Date(timeIntervalSince1970: 1_800_000_000)
        let record = SnapshotRecord(deviceID: "device-1", deviceName: "MacBook Pro",
                                    generatedAt: generatedAt, schemaVersion: 1,
                                    payload: Data([0x1f, 0x8b]))
        let fields = record.fieldValues(payloadValue: "asset-placeholder")
        XCTAssertEqual(fields[SnapshotRecord.fieldDeviceName] as? String, "MacBook Pro")
        XCTAssertEqual(fields[SnapshotRecord.fieldGeneratedAt] as? Date, generatedAt)
        XCTAssertEqual((fields[SnapshotRecord.fieldSchemaVersion] as? Int), 1)

        let parsed = try XCTUnwrap(SnapshotRecord.parse(
            recordName: "device-1", fields: fields, payload: record.payload
        ))
        XCTAssertEqual(parsed, record)
    }

    func testParseRejectsMissingFields() {
        XCTAssertNil(SnapshotRecord.parse(recordName: "device-1", fields: [
            SnapshotRecord.fieldDeviceName: "MacBook Pro",
        ]))
    }

    func testNewestPicksLatestGeneratedAt() {
        let older = SnapshotRecord(deviceID: "a", deviceName: "Old", generatedAt: Date(timeIntervalSince1970: 10), schemaVersion: 1)
        let newer = SnapshotRecord(deviceID: "b", deviceName: "New", generatedAt: Date(timeIntervalSince1970: 20), schemaVersion: 1)
        XCTAssertEqual(SnapshotRecord.newest(in: [older, newer]), newer)
        XCTAssertNil(SnapshotRecord.newest(in: []))
    }

    func testNewestTieBreaksDeterministically() {
        let date = Date(timeIntervalSince1970: 10)
        let a = SnapshotRecord(deviceID: "a", deviceName: "A", generatedAt: date, schemaVersion: 1)
        let b = SnapshotRecord(deviceID: "b", deviceName: "B", generatedAt: date, schemaVersion: 1)
        XCTAssertEqual(SnapshotRecord.newest(in: [a, b]), b)
        XCTAssertEqual(SnapshotRecord.newest(in: [b, a]), b)
    }

    func testDeviceIDIsStableAndPersisted() {
        let suite = "kanjo-snapshot-test-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }

        let first = SnapshotDevice.deviceID(defaults: defaults)
        XCTAssertFalse(first.isEmpty)
        XCTAssertEqual(first, SnapshotDevice.deviceID(defaults: defaults))
        XCTAssertEqual(defaults.string(forKey: SettingsKeys.cloudSyncDeviceID), first)
    }

    func testMobileSnapshotDecodesWithoutFullExportFields() throws {
        let json = """
        {
          "schema_version": 1,
          "generated_at": "2026-10-27T10:42:00Z",
          "timezone": "Asia/Shanghai",
          "currency": "USD",
          "cost_note": "note",
          "totals": {"cost": 1.5, "tokens": {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4, "thinking": 0, "total": 10}, "sessions": 2},
          "projects": [{
            "id": "abc123",
            "name": "Project 1",
            "cost": 1.5,
            "tokens": {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4, "thinking": 0, "total": 10},
            "sessions": 2,
            "first_active": "2026-10-26",
            "last_active": "2026-10-27",
            "by_agent": [],
            "by_model": [],
            "by_day": []
          }],
          "buckets": {
            "unattributed": {"cost": 0, "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "total": 0}, "sessions": 0},
            "excluded": {"cost": 0, "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "total": 0}, "sessions": 0},
            "parse_failed": {"sessions": 0}
          },
          "mobile": {"trimmed": true, "hidden_project_names": true}
        }
        """
        let report = try ReportDecoder.decode(Data(json.utf8))
        XCTAssertEqual(report.config.dominantThreshold, 0.8)
        XCTAssertEqual(report.projects[0].paths, [])
        XCTAssertNil(report.projects[0].remote)
        XCTAssertFalse(report.projects[0].pathMissing)
        XCTAssertEqual(report.projects[0].byBranch, [])
        XCTAssertEqual(report.projects[0].sessionsDetail, [])
        XCTAssertEqual(report.buckets.unattributed.sessionsDetail, [])
        XCTAssertEqual(report.buckets.parseFailed.files, [])
    }
}
