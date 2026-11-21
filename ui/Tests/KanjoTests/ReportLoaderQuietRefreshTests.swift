import XCTest
@testable import KanjoCore

/// 每次 load 都挂起，直到测试手动放行，用来控制刷新的先后顺序。
@MainActor
private final class GatedUsageDataSource: UsageDataSource {
    private(set) var pending: [CheckedContinuation<UsageReport, Error>] = []
    private(set) var loads = 0

    func load() async throws -> UsageReport {
        try await withCheckedThrowingContinuation { cont in
            loads += 1
            pending.append(cont)
        }
    }

    func waitForLoads(_ count: Int, file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<2000 where loads < count {
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
        XCTAssertEqual(loads, count, file: file, line: line)
    }

    func resumeNext(with report: UsageReport) {
        guard !pending.isEmpty else { return XCTFail("no load waiting") }
        pending.removeFirst().resume(returning: report)
    }
}

@MainActor
final class ReportLoaderQuietRefreshTests: KanjoTestCase {
    private func makeLoader(_ source: GatedUsageDataSource) -> ReportLoader {
        ReportLoader(makeSource: { (source, "Fake CLI", true) })
    }

    private func sampleReport() throws -> UsageReport {
        try ReportDecoder.decode(try Data(contentsOf: DefaultPaths.sampleFixture))
    }

    private func settle() async {
        for _ in 0..<20 { try? await Task.sleep(nanoseconds: 1_000_000) }
    }

    func testEachAcceptedReportHasANewRevision() async throws {
        let report = try sampleReport()
        let source = GatedUsageDataSource()
        let loader = makeLoader(source)
        loader.refresh()
        await source.waitForLoads(1)
        source.resumeNext(with: report)
        await loader.waitForRefresh()
        let firstRevision = loader.state.reportRevision
        XCTAssertEqual(firstRevision, 1)

        var changed = report
        changed.costNote = "changed with the same generated_at"
        loader.refresh()
        await source.waitForLoads(2)
        source.resumeNext(with: changed)
        await loader.waitForRefresh()
        XCTAssertEqual(loader.state.reportRevision, firstRevision + 1)
        XCTAssertEqual(loader.state.report?.costNote, changed.costNote)
    }

    func testQuietRefreshDuringRefreshRunsOnceAfterIt() async throws {
        let report = try sampleReport()
        let source = GatedUsageDataSource()
        let loader = makeLoader(source)

        loader.refresh()
        await source.waitForLoads(1)
        loader.refresh(quiet: true)
        loader.refresh(quiet: true)
        await settle()
        XCTAssertEqual(source.loads, 1)

        source.resumeNext(with: report)
        await source.waitForLoads(2)
        source.resumeNext(with: report)
        await loader.waitForRefresh()
        await settle()
        XCTAssertEqual(source.loads, 2)
        XCTAssertFalse(loader.scheduler.isRefreshing)
    }

    func testQuietRequestSurvivesSupersededRefresh() async throws {
        let report = try sampleReport()
        let source = GatedUsageDataSource()
        let loader = makeLoader(source)

        loader.refresh()
        await source.waitForLoads(1)
        loader.refresh()
        await source.waitForLoads(2)
        loader.refresh(quiet: true)

        // 被取代的第一次先结束：不能借它补刷，也不能把请求弄丢。
        source.resumeNext(with: report)
        await settle()
        XCTAssertEqual(source.loads, 2)

        source.resumeNext(with: report)
        await source.waitForLoads(3)
        source.resumeNext(with: report)
        await loader.waitForRefresh()
        await settle()
        XCTAssertEqual(source.loads, 3)
    }

    func testRefreshStartedAfterQuietRequestSatisfiesIt() async throws {
        let report = try sampleReport()
        let source = GatedUsageDataSource()
        let loader = makeLoader(source)

        loader.refresh()
        await source.waitForLoads(1)
        loader.refresh(quiet: true)
        loader.refresh()
        await source.waitForLoads(2)

        source.resumeNext(with: report)
        source.resumeNext(with: report)
        await loader.waitForRefresh()
        await settle()
        XCTAssertEqual(source.loads, 2)
    }
}
