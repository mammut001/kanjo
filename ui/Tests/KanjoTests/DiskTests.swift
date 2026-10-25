import XCTest
@testable import KanjoCore

final class DiskTests: XCTestCase {
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
        XCTAssertEqual(r.agents.count, 5)
        XCTAssertEqual(Fmt.bytes(r.totalBytes), "55.2 GB")
        XCTAssertEqual(Fmt.bytes(r.reclaimableBytes), "31.4 GB")
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

    func testFileDiskSourceLoadsFixture() async throws {
        let r = try await FileDiskSource(url: try fixtureURL()).load()
        XCTAssertEqual(r.agents.count, 5)
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

    func testDiskDataSourceReadsFixture() async throws {
        let path = try fixtureURL().path
        let src = DiskDataSource(cliCommand: "cat '\(path)' # export")
        let r = try await src.load()
        XCTAssertEqual(r.schemaVersion, 1)
        XCTAssertEqual(src.reportCommand, "cat '\(path)' # disk --json")
    }
}
