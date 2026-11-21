#if os(macOS)
import XCTest
import Darwin
@testable import KanjoCore

/// 新的刷新取代旧的之后，旧刷新的 `kanjo export` 子进程要被终止，而不是白跑到超时。
final class ReportLoaderSupersededProcessTests: KanjoTestCase {
    @MainActor
    func testSupersededRefreshTerminatesItsProcess() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("kanjo-superseded-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let script = dir.appendingPathComponent("export.sh")
        let pidFile = dir.appendingPathComponent("pid")
        let marker = dir.appendingPathComponent("first")
        try """
        #!/bin/sh
        if [ -f '\(marker.path)' ]; then cat '\(DefaultPaths.sampleFixture.path)'; exit 0; fi
        touch '\(marker.path)'
        sleep 30 &
        echo $! > '\(pidFile.path)'
        wait
        """.write(to: script, atomically: true, encoding: .utf8)

        let source = CLIDataSource(command: "/bin/sh '\(script.path)'", workingDirectory: dir, timeout: 60)
        let loader = ReportLoader(makeSource: { (source, "Test CLI", false) })

        loader.refresh()
        var pid: pid_t = 0
        for _ in 0..<100 {
            if let text = try? String(contentsOf: pidFile, encoding: .utf8),
               let value = pid_t(text.trimmingCharacters(in: .whitespacesAndNewlines)) {
                pid = value
                break
            }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTAssertGreaterThan(pid, 0, "first export never started")
        defer { if pid > 0 { kill(pid, SIGKILL) } }

        loader.refresh()
        await loader.waitForRefresh()
        XCTAssertNotNil(loader.state.report)

        var alive = true
        for _ in 0..<60 {
            if kill(pid, 0) != 0 { alive = false; break }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTAssertFalse(alive, "superseded export process \(pid) is still running")
    }
}
#endif
