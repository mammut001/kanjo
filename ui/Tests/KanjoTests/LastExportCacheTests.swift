import XCTest
@testable import KanjoCore

private enum FakeSourceError: LocalizedError {
    case boom

    var errorDescription: String? { "boom" }
}

private final class FakeUsageDataSource: UsageDataSource {
    private let handler: () async throws -> UsageReport

    init(handler: @escaping () async throws -> UsageReport) {
        self.handler = handler
    }

    func load() async throws -> UsageReport {
        try await handler()
    }
}

final class LastExportCacheTests: KanjoTestCase {
    private var tempDir: URL!

    override func setUpWithError() throws {
        try super.setUpWithError()
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("kanjo-last-export-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        if let tempDir {
            try? FileManager.default.removeItem(at: tempDir)
        }
        try super.tearDownWithError()
    }

    private func sampleReportData() throws -> Data {
        try Data(contentsOf: DefaultPaths.sampleFixture)
    }

    private func sampleReportObject() throws -> [String: Any] {
        let data = try sampleReportData()
        return try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    @discardableResult
    private func writeEnvelope(scannedAt: Any, doc: Any, to url: URL? = nil) throws -> URL {
        let target = url ?? tempDir.appendingPathComponent(LastExportCache.fileName)
        let payload: [String: Any] = [
            "fingerprint": "fp-test",
            "scanned_at": scannedAt,
            "doc": doc,
        ]
        let data = try JSONSerialization.data(withJSONObject: payload)
        try data.write(to: target)
        return target
    }

    // MARK: - Cache directory rules

    func testCacheDirectoryMirrorsPythonRules() {
        let home = URL(fileURLWithPath: "/Users/alice", isDirectory: true)

        XCTAssertEqual(
            LastExportCache.cacheDirectory(
                environment: ["KANJO_CACHE_DIR": "/tmp/custom-cache", "XDG_CACHE_HOME": "/tmp/xdg"],
                home: home
            ).path,
            "/tmp/custom-cache"
        )
        XCTAssertEqual(
            LastExportCache.cacheDirectory(
                environment: ["KANJO_CACHE_DIR": "", "XDG_CACHE_HOME": "/tmp/xdg"],
                home: home
            ).path,
            "/tmp/xdg/kanjo"
        )
        XCTAssertEqual(
            LastExportCache.cacheDirectory(environment: [:], home: home).path,
            "/Users/alice/.cache/kanjo"
        )
    }

    // MARK: - LastExportCache.load

    func testLoadValidCacheDecodesUsageReport() throws {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let docObj = try sampleReportObject()
        let file = try writeEnvelope(scannedAt: now.timeIntervalSince1970 - 300, doc: docObj)
        let expected = try ReportDecoder.decode(try sampleReportData())

        let loaded = LastExportCache(fileURL: file).load(now: now)
        XCTAssertEqual(loaded, expected)
    }

    func testLoadAcceptsCacheJustWithinSevenDays() throws {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let file = try writeEnvelope(
            scannedAt: now.timeIntervalSince1970 - (7 * 24 * 3600 - 60),
            doc: try sampleReportObject()
        )
        XCTAssertNotNil(LastExportCache(fileURL: file).load(now: now))
    }

    func testLoadRejectsCacheAtOrOlderThanSevenDays() throws {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let doc = try sampleReportObject()

        let exactBoundary = tempDir.appendingPathComponent("boundary.json")
        try writeEnvelope(scannedAt: now.timeIntervalSince1970 - 7 * 24 * 3600, doc: doc, to: exactBoundary)
        XCTAssertNil(LastExportCache(fileURL: exactBoundary).load(now: now))

        let expired = tempDir.appendingPathComponent("expired.json")
        try writeEnvelope(scannedAt: now.timeIntervalSince1970 - (7 * 24 * 3600 + 1), doc: doc, to: expired)
        XCTAssertNil(LastExportCache(fileURL: expired).load(now: now))
    }

    func testLoadRejectsFutureScannedAt() throws {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let file = try writeEnvelope(scannedAt: now.timeIntervalSince1970 + 60, doc: try sampleReportObject())
        XCTAssertNil(LastExportCache(fileURL: file).load(now: now))
    }

    func testLoadReturnsNilForMissingAndMalformedFiles() throws {
        let missing = tempDir.appendingPathComponent("missing.json")
        XCTAssertNil(LastExportCache(fileURL: missing).load())

        let empty = tempDir.appendingPathComponent("empty.json")
        try Data().write(to: empty)
        XCTAssertNil(LastExportCache(fileURL: empty).load())

        let malformed = tempDir.appendingPathComponent("malformed.json")
        try Data("{\"scanned_at\":".utf8).write(to: malformed)
        XCTAssertNil(LastExportCache(fileURL: malformed).load())

        let boolScannedAt = tempDir.appendingPathComponent("bool.json")
        try writeEnvelope(scannedAt: true, doc: try sampleReportObject(), to: boolScannedAt)
        XCTAssertNil(LastExportCache(fileURL: boolScannedAt).load())
    }

    func testLoadRejectsNonFullDoc() throws {
        let now = Date(timeIntervalSince1970: 1_800_000_000)

        var withoutProjects = try sampleReportObject()
        withoutProjects.removeValue(forKey: "projects")
        let noProjURL = tempDir.appendingPathComponent("no-projects.json")
        try writeEnvelope(scannedAt: now.timeIntervalSince1970 - 60, doc: withoutProjects, to: noProjURL)
        XCTAssertNil(LastExportCache(fileURL: noProjURL).load(now: now))

        var withoutTotals = try sampleReportObject()
        withoutTotals.removeValue(forKey: "totals")
        let noTotalsURL = tempDir.appendingPathComponent("no-totals.json")
        try writeEnvelope(scannedAt: now.timeIntervalSince1970 - 60, doc: withoutTotals, to: noTotalsURL)
        XCTAssertNil(LastExportCache(fileURL: noTotalsURL).load(now: now))

        let publicSummaryDoc: [String: Any] = [
            "schema_version": 1,
            "generated_at": "2026-11-18T00:00:00Z",
            "all_time": ["cost_usd": 10.0],
        ]
        let summaryURL = tempDir.appendingPathComponent("summary.json")
        try writeEnvelope(scannedAt: now.timeIntervalSince1970 - 60, doc: publicSummaryDoc, to: summaryURL)
        XCTAssertNil(LastExportCache(fileURL: summaryURL).load(now: now))
    }

    // MARK: - StaleReportText

    func testStaleTimestampUsesReportTimezoneAndOmitsDateWhenToday() throws {
        // 2026-11-18T03:30:00Z is 2026-11-17 22:30 in America/Montreal (UTC-5)
        let generatedAt = "2026-11-18T03:30:00Z"
        let sameDayNow = try XCTUnwrap(ReportDates.parseTimestamp("2026-11-18T04:15:00Z")) // 2026-11-17 23:15 in Montreal
        let nextDayNow = try XCTUnwrap(ReportDates.parseTimestamp("2026-11-18T06:00:00Z")) // 2026-11-18 01:00 in Montreal

        XCTAssertEqual(
            StaleReportText.timestamp(generatedAt: generatedAt, timezoneIdentifier: "America/Montreal", now: sameDayNow, language: "en"),
            "22:30"
        )
        XCTAssertEqual(
            StaleReportText.footerStatus(generatedAt: generatedAt, timezoneIdentifier: "America/Montreal", isLoading: true, now: sameDayNow, language: "en"),
            "Data from 22:30 · updating…"
        )
        XCTAssertEqual(
            StaleReportText.footerStatus(generatedAt: generatedAt, timezoneIdentifier: "America/Montreal", isLoading: true, now: sameDayNow, language: "zh-Hans"),
            "数据来自 22:30 · 正在更新…"
        )
        XCTAssertEqual(
            StaleReportText.footerStatus(generatedAt: generatedAt, timezoneIdentifier: "America/Montreal", isLoading: true, now: sameDayNow, language: "fr"),
            "Données de 22:30 · actualisation…"
        )

        let enNextDay = StaleReportText.footerStatus(generatedAt: generatedAt, timezoneIdentifier: "America/Montreal", isLoading: true, now: nextDayNow, language: "en")
        XCTAssertTrue(enNextDay.contains("Nov 17") && enNextDay.contains("22:30"), enNextDay)

        let zhNextDay = StaleReportText.footerStatus(generatedAt: generatedAt, timezoneIdentifier: "America/Montreal", isLoading: false, now: nextDayNow, language: "zh-Hans")
        XCTAssertEqual(zhNextDay, "数据来自 11月17日 22:30")
    }

    // MARK: - ReportLoader stale -> live

    func testShouldUseLastExportCacheOnlyInNormalCLIMode() {
        XCTAssertTrue(ReportLoader.shouldUseLastExportCache(sourceKind: .cli, dataOverride: nil, isSnapshotMode: false))
        XCTAssertFalse(ReportLoader.shouldUseLastExportCache(sourceKind: .file, dataOverride: nil, isSnapshotMode: false))
        XCTAssertFalse(ReportLoader.shouldUseLastExportCache(sourceKind: .cli, dataOverride: URL(fileURLWithPath: "/tmp/a.json"), isSnapshotMode: false))
        XCTAssertFalse(ReportLoader.shouldUseLastExportCache(sourceKind: .cli, dataOverride: nil, isSnapshotMode: true))
    }

    @MainActor
    func testReportLoaderStaleToLiveTransitionSkipsHooksForCachedReport() async throws {
        var mutableCached = try ReportDecoder.decode(try sampleReportData())
        mutableCached.generatedAt = "2026-11-17T19:30:00Z"
        let cachedReport = mutableCached

        var liveReport = cachedReport
        liveReport.generatedAt = "2026-11-18T05:00:00Z"
        liveReport.totals.cost += 42.0

        var continuation: CheckedContinuation<UsageReport, Error>?
        let sourceReady = expectation(description: "fake source started")
        let fakeSource = FakeUsageDataSource {
            try await withCheckedThrowingContinuation { cont in
                continuation = cont
                sourceReady.fulfill()
            }
        }

        var liveHookReports: [UsageReport] = []
        let loader = ReportLoader(
            makeSource: { (fakeSource, "Fake CLI", true) },
            loadCachedReport: { cachedReport },
            onLiveReport: { liveHookReports.append($0) }
        )

        loader.startInitialLoad()
        await loader.waitForInitialCache()
        await fulfillment(of: [sourceReady], timeout: 2.0)

        XCTAssertEqual(loader.state.report, cachedReport)
        XCTAssertTrue(loader.state.isStaleReport)
        XCTAssertEqual(loader.state.staleReportGeneratedAt, "2026-11-17T19:30:00Z")
        XCTAssertTrue(loader.state.isLoading)
        XCTAssertNil(loader.state.lastRefresh)
        XCTAssertTrue(liveHookReports.isEmpty, "sync/publish hooks must not run for cached report")

        continuation?.resume(returning: liveReport)
        await loader.waitForRefresh()

        XCTAssertEqual(loader.state.report, liveReport)
        XCTAssertFalse(loader.state.isStaleReport)
        XCTAssertNil(loader.state.staleReportGeneratedAt)
        XCTAssertFalse(loader.state.isLoading)
        XCTAssertNil(loader.state.error)
        XCTAssertNotNil(loader.state.lastRefresh)
        XCTAssertEqual(liveHookReports, [liveReport])
    }

    @MainActor
    func testReportLoaderIgnoresDelayedCacheWhenLiveArrivesFirst() async throws {
        var mutableCached = try ReportDecoder.decode(try sampleReportData())
        mutableCached.generatedAt = "2026-11-17T19:30:00Z"
        let cachedReport = mutableCached

        var liveReport = cachedReport
        liveReport.generatedAt = "2026-11-18T05:00:00Z"
        liveReport.totals.cost += 10.0

        let cacheGate = DispatchSemaphore(value: 0)
        let fakeSource = FakeUsageDataSource { liveReport }

        var liveHookReports: [UsageReport] = []
        let loader = ReportLoader(
            makeSource: { (fakeSource, "Fake CLI", true) },
            loadCachedReport: {
                _ = cacheGate.wait(timeout: .now() + 2.0)
                return cachedReport
            },
            onLiveReport: { liveHookReports.append($0) }
        )

        loader.startInitialLoad()
        await loader.waitForRefresh()
        cacheGate.signal()
        await loader.waitForInitialCache()

        XCTAssertEqual(loader.state.report, liveReport)
        XCTAssertFalse(loader.state.isStaleReport)
        XCTAssertNil(loader.state.staleReportGeneratedAt)
        XCTAssertEqual(liveHookReports, [liveReport])
    }

    @MainActor
    func testReportLoaderAppliesDelayedCacheWhenLiveFailsFirst() async throws {
        let cachedReport = try ReportDecoder.decode(try sampleReportData())
        let cacheGate = DispatchSemaphore(value: 0)
        let fakeSource = FakeUsageDataSource { throw FakeSourceError.boom }
        let loader = ReportLoader(
            makeSource: { (fakeSource, "Fake CLI", true) },
            loadCachedReport: {
                _ = cacheGate.wait(timeout: .now() + 2.0)
                return cachedReport
            }
        )

        loader.startInitialLoad()
        await loader.waitForRefresh()
        cacheGate.signal()
        await loader.waitForInitialCache()

        XCTAssertEqual(loader.state.report, cachedReport)
        XCTAssertTrue(loader.state.isStaleReport)
        XCTAssertEqual(loader.state.error, "boom")
        XCTAssertFalse(loader.state.isLoading)
    }

    @MainActor
    func testReportLoaderKeepsCachedReportAndSetsErrorWhenLiveFails() async throws {
        let cachedReport = try ReportDecoder.decode(try sampleReportData())

        var continuation: CheckedContinuation<UsageReport, Error>?
        let sourceReady = expectation(description: "fake source started")
        let fakeSource = FakeUsageDataSource {
            try await withCheckedThrowingContinuation { cont in
                continuation = cont
                sourceReady.fulfill()
            }
        }

        var liveHookReports: [UsageReport] = []
        var cliFailures = 0
        let loader = ReportLoader(
            makeSource: { (fakeSource, "Fake CLI", true) },
            loadCachedReport: { cachedReport },
            onLiveReport: { liveHookReports.append($0) },
            onCLIFailure: { cliFailures += 1 }
        )

        loader.startInitialLoad()
        await loader.waitForInitialCache()
        await fulfillment(of: [sourceReady], timeout: 2.0)

        continuation?.resume(throwing: FakeSourceError.boom)
        await loader.waitForRefresh()

        XCTAssertEqual(loader.state.report, cachedReport)
        XCTAssertTrue(loader.state.isStaleReport)
        XCTAssertEqual(loader.state.staleReportGeneratedAt, cachedReport.generatedAt)
        XCTAssertEqual(loader.state.error, "boom")
        XCTAssertFalse(loader.state.isLoading)
        XCTAssertEqual(cliFailures, 1)
        XCTAssertTrue(liveHookReports.isEmpty)
    }
}
