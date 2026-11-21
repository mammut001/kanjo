import XCTest
@testable import KanjoCore

final class DiskTests: KanjoTestCase {
    private func fixtureURL() throws -> URL {
        let root = try XCTUnwrap(DefaultPaths.packageRoot)
        return root.appendingPathComponent("fixtures/disk-sample.json")
    }

    private func loadFixture() throws -> DiskReport {
        try DiskDecoder.decode(Data(contentsOf: try fixtureURL()))
    }

    func testFixtureDecodes() throws {
        let r = try loadFixture()
        XCTAssertEqual(r.schemaVersion, 1)
        XCTAssertFalse(r.isNewerSchema)
        XCTAssertEqual(r.agents.count, 10)
        XCTAssertNil(r.cached)
        XCTAssertNil(r.scannedAt)
        XCTAssertNil(r.scanSeconds)
        XCTAssertEqual(Fmt.bytes(r.totalBytes), "42.2 GB")
        XCTAssertEqual(Fmt.bytes(r.reclaimableBytes), "25.9 GB")
        let codex = try XCTUnwrap(r.agents.first { $0.agent == "codex" })
        XCTAssertEqual(codex.label, "Codex CLI")
        XCTAssertEqual(Fmt.bytes(codex.bytes), "11.8 GB")
        XCTAssertTrue(r.allEntries.allSatisfy { $0.path.hasPrefix("/Users/alice/") })
    }

    func testReclaimableSumMatchesUnblockedNonNever() throws {
        let r = try loadFixture()
        let summed = r.allEntries.filter { $0.deletable != .never && $0.blocked.isEmpty }.reduce(0) { $0 + $1.bytes }
        XCTAssertEqual(r.reclaimableBytes, summed)
        XCTAssertEqual(r.reclaimableBytes, r.summedReclaimableBytes)
        XCTAssertEqual(r.totalBytes, r.agents.reduce(0) { $0 + $1.bytes })
        for agent in r.agents {
            XCTAssertEqual(agent.bytes, agent.entries.reduce(0) { $0 + $1.bytes }, agent.agent)
        }
    }

    func testFixtureCoversDeletableClassesAndBlockReasons() throws {
        let entries = try loadFixture().allEntries
        XCTAssertTrue(Set(entries.map(\.deletable)).isSuperset(of: [.always, .afterImport, .whenClean, .never]))
        XCTAssertTrue(Set(entries.map(\.kind)).isSuperset(of: [.sessions, .scratch, .worktrees, .cache, .memory, .other]))
        let reasons = Set(entries.flatMap(\.blocked))
        XCTAssertTrue(reasons.isSuperset(of: ["not_imported", "uncommitted_changes", "active"]))
        XCTAssertTrue(entries.contains { $0.isReclaimable })
        XCTAssertTrue(entries.contains { $0.deletable == .never && !$0.isReclaimable })
        XCTAssertTrue(entries.contains { !$0.blocked.isEmpty && !$0.isReclaimable })
    }

    func testUnknownKindAndDeletableDecode() throws {
        let json = """
        {"schema_version":1,"generated_at":"2026-10-25T10:00:00Z","total_bytes":1,"reclaimable_bytes":1,
         "agents":[{"agent":"x","label":"X","bytes":1,"entries":[
           {"id":"x:y","kind":"weird","path":"/Users/alice/x","bytes":1,"files":1,
            "oldest":"2026-01-01","newest":"2026-01-02","deletable":"sometimes","blocked":[]}
         ]}]}
        """
        let entry = try DiskDecoder.decode(Data(json.utf8)).allEntries[0]
        XCTAssertEqual(entry.kind, .unknown("weird"))
        XCTAssertEqual(entry.deletable, .unknown("sometimes"))
        XCTAssertEqual(entry.blocked, [])
        XCTAssertTrue(entry.isReclaimable)
        XCTAssertEqual(DiskBlock.title("custom_reason"), "Blocked: custom reason")
        XCTAssertEqual(DiskBlock.title("not_imported"), "Blocked: not imported")
        XCTAssertEqual(DiskBlock.short("uncommitted_changes"), "uncommitted changes")
    }

    func testMissingFieldNamesThePath() {
        let json = #"{"schema_version":1,"generated_at":"t","total_bytes":0,"reclaimable_bytes":0,"agents":[{"agent":"a","label":"A","bytes":0}]}"#
        XCTAssertThrowsError(try DiskDecoder.decode(Data(json.utf8))) { error in
            guard case DataSourceError.contractMismatch(let why, _) = error else { return XCTFail("\(error)") }
            XCTAssertTrue(why.contains("agents[0].entries"), why)
        }
    }

    func testCommandDerivation() {
        XCTAssertEqual(DiskCommand.report(from: "python3 -m kanjo export"), "python3 -m kanjo disk --json")
        XCTAssertEqual(
            DiskCommand.report(from: "export PATH=\"$HOME/.local/bin:$PATH\"; python3 -m kanjo export"),
            "export PATH=\"$HOME/.local/bin:$PATH\"; python3 -m kanjo disk --json")
        XCTAssertEqual(
            DiskCommand.report(from: "python3 /opt/exporter/bin/python3 -m kanjo export"),
            "python3 /opt/exporter/bin/python3 -m kanjo disk --json")
    }

    func testRescanCommandDerivation() {
        XCTAssertEqual(DiskCommand.report(from: "python3 -m kanjo export", rescan: true),
                       "python3 -m kanjo disk --json --rescan")
        XCTAssertEqual(DiskCommand.report(from: "export PATH=bin; kanjo export", rescan: true),
                       "export PATH=bin; kanjo disk --json --rescan")
        XCTAssertEqual(DiskDataSource(cliCommand: "kanjo export").reportCommand, "kanjo disk --json")
        XCTAssertEqual(DiskDataSource(cliCommand: "kanjo export", rescan: true).reportCommand,
                       "kanjo disk --json --rescan")
    }

    func testCacheMetadataDecodes() throws {
        let json = """
        {"schema_version":1,"generated_at":"2026-10-25T10:00:00Z","total_bytes":0,"reclaimable_bytes":0,
         "agents":[],"cached":true,"scanned_at":"2026-10-25T09:57:00Z","scan_seconds":22.5}
        """
        let report = try DiskDecoder.decode(Data(json.utf8))
        XCTAssertEqual(report.cached, true)
        XCTAssertEqual(report.scannedAt, "2026-10-25T09:57:00Z")
        XCTAssertEqual(report.scanSeconds, 22.5)
    }

    func testScanCaption() throws {
        let now = try XCTUnwrap(ReportDates.parseTimestamp("2026-10-25T10:00:00Z"))
        var report = try loadFixture()
        let cases: [(String, String)] = [
            ("2026-10-25T10:00:05Z", "Scanned just now"),
            ("2026-10-25T09:59:01Z", "Scanned just now"),
            ("2026-10-25T09:59:00Z", "Scanned 1 min ago"),
            ("2026-10-25T09:57:00.000Z", "Scanned 3 min ago"),
            ("2026-10-25T09:00:00+00:00", "Scanned 1 hr ago"),
            ("2026-10-24T10:00:00Z", "Scanned 1 day ago"),
            ("2026-10-23T10:00:00Z", "Scanned 2 days ago"),
        ]
        for (timestamp, expected) in cases {
            report.scannedAt = timestamp
            XCTAssertEqual(DiskScanCaption.text(for: report, now: now), expected)
        }
        report.scannedAt = nil
        report.generatedAt = "2026-10-25T09:57:00Z"
        XCTAssertEqual(DiskScanCaption.text(for: report, now: now), "Scanned 3 min ago")
        report.generatedAt = "invalid"
        XCTAssertEqual(DiskScanCaption.text(for: report, now: now), "Scan time unknown")
    }

    func testPersistedCacheRoundTrip() throws {
        let root = try XCTUnwrap(DefaultPaths.packageRoot)
        let directory = root.appendingPathComponent(".build/disk-cache-test-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = DiskReportCache(directory: directory)
        XCTAssertNil(cache.load())
        var report = try loadFixture()
        report.cached = false
        report.scannedAt = "2026-10-25T09:57:00Z"
        report.scanSeconds = 23.1
        cache.save(report)
        XCTAssertEqual(DiskReportCache(directory: directory).load(), report)
        XCTAssertEqual(cache.fileURL?.lastPathComponent, "disk-report.json")
        report.totalBytes = 42
        cache.save(report)
        XCTAssertEqual(cache.load(), report)
        try Data("corrupt".utf8).write(to: XCTUnwrap(cache.fileURL))
        XCTAssertNil(cache.load())
    }

    func testReportStateKeepsReportWhileRescanning() throws {
        let report = try loadFixture()
        var state = DiskReportState()
        XCTAssertFalse(state.hasReport)
        XCTAssertFalse(state.isRescanning)
        XCTAssertTrue(state.beginRefresh())
        XCTAssertTrue(state.isLoading)
        XCTAssertFalse(state.isRescanning)
        XCTAssertFalse(state.beginRefresh())
        state.finishRefresh(report: report)
        XCTAssertTrue(state.hasReport)
        XCTAssertFalse(state.isLoading)
        XCTAssertFalse(state.isRescanning)
        XCTAssertTrue(state.beginRefresh())
        XCTAssertTrue(state.hasReport)
        XCTAssertTrue(state.isRescanning)
        XCTAssertEqual(state.report, report)
        state.finishRefresh() // 失败时仍保留上一份。
        XCTAssertEqual(state.report, report)
        XCTAssertFalse(state.isRescanning)
        var newer = report
        newer.totalBytes = 10
        XCTAssertTrue(state.beginRefresh())
        state.finishRefresh(report: newer)
        XCTAssertEqual(state.report, newer)
        XCTAssertTrue(DiskReportState(report: report).hasReport)
    }

    func testCleanCommandAssembly() {
        XCTAssertEqual(
            DiskCommand.clean(from: "python3 -m kanjo export",
                              ids: ["codex:sessions", "claude:cache"],
                              olderThan: "30d",
                              confirmed: false),
            "python3 -m kanjo disk clean codex:sessions claude:cache --older-than 30d --dry-run")
        XCTAssertEqual(
            DiskCommand.clean(from: "python3 -m kanjo export",
                              ids: ["codex:sessions"],
                              olderThan: "7d",
                              confirmed: true),
            "python3 -m kanjo disk clean codex:sessions --older-than 7d --yes")
        XCTAssertEqual(
            DiskCommand.clean(from: "python3 -m kanjo export",
                              ids: ["antigravity:worktrees"],
                              olderThan: nil,
                              confirmed: true),
            "python3 -m kanjo disk clean antigravity:worktrees --yes")
        XCTAssertEqual(
            DiskCommand.clean(from: "python3 -m kanjo export",
                              ids: ["id with space"],
                              olderThan: "90d",
                              confirmed: false),
            "python3 -m kanjo disk clean 'id with space' --older-than 90d --dry-run")
        XCTAssertEqual(
            DiskCommand.clean(from: "export PATH=\"$PATH\"; python3 -m kanjo export",
                              ids: ["codex:cache"],
                              olderThan: "",
                              confirmed: false),
            "export PATH=\"$PATH\"; python3 -m kanjo disk clean codex:cache --dry-run")
    }

    /// 空目录的 CLI 报告把 oldest/newest 写成 null。整份磁盘报告仍要能解码，否则磁盘页打不开。
    func testEmptyEntryNullDatesDoNotFailTheReport() throws {
        let report = try DiskDecoder.decode(Data("""
        {"schema_version":1,"generated_at":"2026-10-25T10:00:00Z","total_bytes":0,"reclaimable_bytes":0,
         "agents":[{"agent":"codex","label":"Codex CLI","bytes":0,"entries":[
           {"id":"codex:cache","kind":"cache","path":"/Users/alice/.codex/cache","bytes":0,"files":0,
            "oldest":null,"newest":null,"deletable":"always","blocked":[]}
         ]}]}
        """.utf8))
        let entry = try XCTUnwrap(report.agents.first?.entries.first)
        XCTAssertEqual(entry.id, "codex:cache")
        XCTAssertNil(entry.oldest)
        XCTAssertNil(entry.newest)
        XCTAssertEqual(entry.files, 0)
        XCTAssertTrue(entry.isReclaimable)
    }

    func testCleanPlanText() throws {
        let report = try DiskDecoder.decode(Data("""
        {"schema_version":1,"generated_at":"2026-10-25T10:00:00Z","total_bytes":7000000000,"reclaimable_bytes":7000000000,
         "agents":[
           {"agent":"codex","label":"Codex CLI","bytes":4600000000,"entries":[
             {"id":"codex:sessions","kind":"sessions","path":"/Users/alice/.codex/sessions","bytes":4600000000,"files":2,
              "oldest":"2026-06-30","newest":"2026-10-25","deletable":"after_import","blocked":[]}]},
           {"agent":"claude","label":"Claude Code","bytes":2400000000,"entries":[
             {"id":"claude:cache","kind":"cache","path":"/Users/alice/Library/Caches/claude-cli","bytes":2400000000,"files":3,
              "oldest":"2026-08-02","newest":"2026-10-24","deletable":"always","blocked":[]}]}
         ]}
        """.utf8))
        let whole = CleanResult(
            moved: ["/Users/alice/.codex/sessions", "/Users/alice/Library/Caches/claude-cli"],
            freedBytes: 7_000_000_000,
            skipped: [CleanSkip(id: "claude:scratch", reason: "active")])
        XCTAssertEqual(CleanPlan.text(report: report, result: whole), """
        Codex CLI · sessions
        /Users/alice/.codex/sessions
        1 path · 4.6 GB

        Claude Code · cache
        /Users/alice/Library/Caches/claude-cli
        1 path · 2.4 GB

        Total 2 paths · 7 GB

        Skipped
        claude:scratch — active
        """)

        let files = CleanResult(
            moved: ["/Users/alice/.codex/sessions/a.jsonl", "/Users/alice/.codex/sessions/b.jsonl"],
            freedBytes: 1000,
            skipped: [])
        XCTAssertEqual(CleanPlan.text(report: report, result: files), """
        Codex CLI · sessions
        /Users/alice/.codex/sessions/a.jsonl
        /Users/alice/.codex/sessions/b.jsonl
        2 paths

        Total 2 paths · 1 KB
        """)
    }

    func testDiskDataOverride() {
        XCTAssertEqual(
            DefaultPaths.diskDataOverride(arguments: ["Kanjo", "--disk-data", "/tmp/disk.json"])?.path,
            "/tmp/disk.json")
        XCTAssertNil(DefaultPaths.diskDataOverride(arguments: ["Kanjo", "--data", "/tmp/a.json"]))
    }

    func testConfirmCommandIncludesPreviewPaths() {
        let command = DiskCommand.clean(from: "kanjo export", ids: [], olderThan: nil, confirmed: true,
                                        mergedWorktrees: true, onlyPaths: ["/tmp/a b", "/tmp/other"])
        XCTAssertTrue(command.contains("--only-paths '[\"/tmp/a b\",\"/tmp/other\"]' --yes"))
        XCTAssertTrue(DiskCommand.clean(from: "kanjo export", ids: ["claude:scratch"], olderThan: nil,
                                        confirmed: true, onlyPaths: []).contains("--only-paths '[]' --yes"))
    }

    func testFileDiskSourceLoadsFixture() async throws {
        let r = try await FileDiskSource(url: try fixtureURL()).load()
        XCTAssertEqual(r.agents.count, 10)
        do {
            _ = try await FileDiskSource(url: URL(fileURLWithPath: "/nonexistent/disk.json")).load()
            XCTFail("expected error")
        } catch {
            XCTAssertEqual(error as? DataSourceError, .fileNotFound("/nonexistent/disk.json"))
        }
        do {
            _ = try await FileDiskSource(url: try fixtureURL()).clean(ids: ["codex:cache"], olderThan: nil, confirmed: true)
            XCTFail("file source must not clean")
        } catch let DataSourceError.launchFailed(message) {
            XCTAssertTrue(message.contains("nothing was moved"), message)
        } catch {
            XCTFail("got \(error)")
        }
    }

    private func worktreeReport() throws -> DiskReport {
        try DiskDecoder.decode(Data("""
        {"schema_version":1,"generated_at":"2026-11-18T10:00:00Z","total_bytes":0,"reclaimable_bytes":0,
         "agents":[{"agent":"claude","label":"Claude Code","bytes":0,"entries":[
           {"id":"claude:worktree:p/s1/scratchpad/wt-a","kind":"worktrees","path":"/tmp/claude-501/p/s1/scratchpad/wt-a",
            "bytes":2000000000,"files":10,"oldest":"2026-11-01","newest":"2026-11-10","deletable":"when_clean",
            "blocked":[],"merged":true,"merged_into":"origin/main"},
           {"id":"claude:worktree:p/s2/scratchpad/wt-b","kind":"worktrees","path":"/tmp/claude-501/p/s2/scratchpad/wt-b",
            "bytes":100000000,"files":3,"oldest":"2026-11-01","newest":"2026-11-10","deletable":"when_clean",
            "blocked":[],"merged":true,"merged_into":"origin/main"},
           {"id":"claude:worktree:p/s3/scratchpad/wt-c","kind":"worktrees","path":"/tmp/claude-501/p/s3/scratchpad/wt-c",
            "bytes":500000000,"files":3,"oldest":"2026-11-01","newest":"2026-11-18","deletable":"when_clean",
            "blocked":["uncommitted_changes"],"merged":true,"merged_into":"main"},
           {"id":"claude:worktree:p/s4/scratchpad/wt-d","kind":"worktrees","path":"/tmp/claude-501/p/s4/scratchpad/wt-d",
            "bytes":700000000,"files":3,"oldest":"2026-11-01","newest":"2026-11-10","deletable":"when_clean",
            "blocked":[],"merged":false,"merged_into":"origin/main"},
           {"id":"codex:worktree:x/repo","kind":"worktrees","path":"/Users/alice/.codex/worktrees/x/repo",
            "bytes":900000000,"files":3,"oldest":"2026-11-01","newest":"2026-11-10","deletable":"when_clean",
            "blocked":[],"merged":null,"merged_into":null},
           {"id":"claude:scratch","kind":"scratch","path":"/tmp/claude-501","bytes":1,"files":1,
            "oldest":"2026-11-01","newest":"2026-11-10","deletable":"when_clean","blocked":[]}
         ]}]}
        """.utf8))
    }

    func testMergedFieldsDecode() throws {
        let entries = try worktreeReport().allEntries
        XCTAssertEqual(entries[0].merged, true)
        XCTAssertEqual(entries[0].mergedInto, "origin/main")
        XCTAssertTrue(entries[0].isMergedWorktree)
        XCTAssertEqual(entries[3].merged, false)
        XCTAssertFalse(entries[3].isMergedWorktree)
        XCTAssertNil(entries[4].merged)
        XCTAssertNil(entries[4].mergedInto)
        // Older CLIs (and non-worktree entries) leave both fields out.
        XCTAssertNil(entries[5].merged)
        XCTAssertNil(entries[5].mergedInto)
        XCTAssertFalse(entries[5].isMergedWorktree)
        XCTAssertTrue(try loadFixture().allEntries.allSatisfy { $0.merged == nil })
    }

    func testMergedWorktreeSummary() throws {
        let summary = MergedWorktreeSummary(report: try worktreeReport())
        XCTAssertEqual(summary.mergedCount, 3)
        XCTAssertEqual(summary.reclaimableCount, 2)
        XCTAssertEqual(summary.reclaimableIDs, ["claude:worktree:p/s1/scratchpad/wt-a",
                                                "claude:worktree:p/s2/scratchpad/wt-b"])
        XCTAssertEqual(summary.reclaimableBytes, 2_100_000_000)
        XCTAssertEqual(summary.text, "3 worktrees merged · 2.1 GB reclaimable")
        XCTAssertFalse(summary.isEmpty)
        let none = MergedWorktreeSummary(report: try loadFixture())
        XCTAssertTrue(none.isEmpty)
        XCTAssertEqual(none.reclaimableBytes, 0)
    }

    func testMergedWorktreeAutoClean() throws {
        let report = try worktreeReport()
        let ids: Set<String> = ["claude:worktree:p/s1/scratchpad/wt-a", "claude:worktree:p/s2/scratchpad/wt-b"]
        XCTAssertNil(MergedWorktreeAutoClean.candidates(enabled: false, report: report, lastAttempt: []))
        XCTAssertEqual(MergedWorktreeAutoClean.candidates(enabled: true, report: report, lastAttempt: []), ids)
        // The same set again (git refused last time) is not retried after every scan.
        XCTAssertNil(MergedWorktreeAutoClean.candidates(enabled: true, report: report, lastAttempt: ids))
        XCTAssertNil(MergedWorktreeAutoClean.candidates(enabled: true, report: try loadFixture(), lastAttempt: []))
        let date = try XCTUnwrap(ReportDates.parseTimestamp("2026-11-18T10:00:00Z"))
        let result = CleanResult(moved: ["/a", "/b", "/c"], freedBytes: 2_100_000_000, skipped: [])
        XCTAssertEqual(MergedWorktreeAutoClean.line(result: result, at: date),
                       "Automatically cleaned up 3 merged worktrees, freed 2.1 GB · \(Fmt.clock(date))")
        let one = CleanResult(moved: ["/a"], freedBytes: 1000, skipped: [])
        XCTAssertTrue(MergedWorktreeAutoClean.line(result: one, at: date).hasPrefix("Automatically cleaned up 1 merged worktree,"))
    }

    func testMergedCleanCommandAndSkipDetail() throws {
        XCTAssertEqual(
            DiskCommand.clean(from: "python3 -m kanjo export", ids: [], olderThan: nil, confirmed: false,
                              mergedWorktrees: true),
            "python3 -m kanjo disk clean --merged-worktrees --dry-run")
        XCTAssertEqual(
            DiskCommand.clean(from: "kanjo export", ids: [], olderThan: nil, confirmed: true, mergedWorktrees: true),
            "kanjo disk clean --merged-worktrees --yes")
        let result = try DiskDecoder.decodeClean(Data("""
        {"moved":["/tmp/wt"],"freed_bytes":10,"skipped":[
          {"id":"claude:worktree:a","reason":"worktree_remove_failed","detail":"fatal: cannot remove a locked working tree"},
          {"id":"claude:worktree:b","reason":"not_merged"}]}
        """.utf8))
        XCTAssertEqual(result.skipped[0].detail, "fatal: cannot remove a locked working tree")
        XCTAssertNil(result.skipped[1].detail)
        XCTAssertEqual(DiskBlock.short("not_merged"), "not merged")
        XCTAssertEqual(DiskBlock.short("worktree_remove_failed"), "git refused")
    }

    func testDiskDataSourceReadsFixture() async throws {
        let path = try fixtureURL().path
        let src = DiskDataSource(cliCommand: "cat '\(path)' # export")
        let r = try await src.load()
        XCTAssertEqual(r.schemaVersion, 1)
        XCTAssertEqual(src.reportCommand, "cat '\(path)' # disk --json")
    }
}
