import XCTest
@testable import AICostCore

final class DecodingTests: XCTestCase {
    private func loadFixture() throws -> UsageReport {
        let data = try Data(contentsOf: DefaultPaths.sampleFixture)
        return try ReportDecoder.decode(data)
    }

    func testFixtureDecodes() throws {
        let r = try loadFixture()
        XCTAssertEqual(r.schemaVersion, 1)
        XCTAssertFalse(r.isNewerSchema)
        XCTAssertEqual(r.currency, "USD")
        XCTAssertFalse(r.costNote.isEmpty)
        XCTAssertTrue((6...8).contains(r.projects.count))
    }

    func testTopLevelInvariantHolds() throws {
        let r = try loadFixture()
        let rec = Reconciliation(report: r)
        XCTAssertTrue(rec.cost.ok, "cost diff \(rec.cost.diff)")
        XCTAssertTrue(rec.tokens.ok, "token diff \(rec.tokens.diff)")
        XCTAssertTrue(rec.sessions.ok, "session diff \(rec.sessions.diff)")
    }

    func testProjectInvariants() throws {
        let r = try loadFixture()
        XCTAssertEqual(r.projects.map(\.cost), r.projects.map(\.cost).sorted(by: >), "projects sorted by cost desc")
        for p in r.projects {
            let t = p.tokens
            XCTAssertEqual(t.total, t.input + t.output + t.cacheRead + t.cacheWrite, p.id)
            XCTAssertLessThanOrEqual(t.thinking, t.output, p.id)
            XCTAssertEqual(p.byAgent.reduce(0) { $0 + $1.cost }, p.cost, accuracy: 0.01, "\(p.id) by_agent")
            XCTAssertEqual(p.byModel.reduce(0) { $0 + $1.cost }, p.cost, accuracy: 0.01, "\(p.id) by_model")
            XCTAssertEqual(p.byDay.reduce(0) { $0 + $1.cost }, p.cost, accuracy: 0.01, "\(p.id) by_day")
            XCTAssertEqual(p.sessionsDetail.reduce(0) { $0 + $1.cost }, p.cost, accuracy: 0.01, "\(p.id) sessions")
            XCTAssertEqual(p.byAgent.reduce(Tokens.zero) { $0 + $1.tokens }, p.tokens, p.id)
            XCTAssertEqual(p.byModel.reduce(0) { $0 + $1.tokens.total }, t.total, p.id)
            XCTAssertEqual(p.byDay.reduce(0) { $0 + $1.tokens }, t.total, p.id)
            XCTAssertEqual(p.sessionsDetail.count, p.sessions, p.id)
            XCTAssertEqual(p.byAgent.reduce(0) { $0 + $1.sessions }, p.sessions, p.id)
            if !p.byBranch.isEmpty {
                XCTAssertEqual(p.byBranch.reduce(0) { $0 + $1.cost }, p.cost, accuracy: 0.01, "\(p.id) by_branch")
            }
            XCTAssertEqual(p.byDay.map(\.day), p.byDay.map(\.day).sorted(), "\(p.id) by_day sorted by date")
            let starts = p.sessionsDetail.compactMap(\.startedDate)
            XCTAssertEqual(starts.count, p.sessionsDetail.count, "\(p.id) all started parse")
            XCTAssertEqual(starts, starts.sorted(by: >), "\(p.id) sessions sorted by started desc")
            for s in p.sessionsDetail {
                XCTAssertTrue(s.share > 0 && s.share <= 1, s.id)
                if s.attribution == "split" { XCTAssertLessThan(s.share, 1, s.id) }
            }
        }
    }

    func testFixtureCoversRequiredCases() throws {
        let r = try loadFixture()
        let agents = Set(r.projects.flatMap { $0.byAgent.map(\.agent) })
        XCTAssertEqual(agents, ["claude", "antigravity", "codex"])
        XCTAssertTrue(r.projects.contains { $0.byAgent.count == 1 }, "single-agent project")
        XCTAssertTrue(r.projects.contains { $0.pathMissing }, "path_missing project")
        XCTAssertTrue(r.projects.contains { $0.remote == nil && $0.id.hasPrefix("/") }, "no-remote project")
        let attrs = Set(r.projects.flatMap { $0.sessionsDetail.map(\.attribution) })
        XCTAssertTrue(attrs.isSuperset(of: ["dominant", "split", "cwd"]))
        XCTAssertTrue(r.projects.contains { $0.byModel.contains(where: \.estimated) })
        XCTAssertGreaterThan(r.buckets.unattributed.cost, 0)
        XCTAssertGreaterThan(r.buckets.excluded.cost, 0)
        XCTAssertGreaterThan(r.buckets.parseFailed.sessions, 0)
        XCTAssertTrue(r.buckets.unattributed.sessionsDetail.allSatisfy { $0.attribution == "none" && $0.share == 1 })
        XCTAssertTrue(r.buckets.excluded.sessionsDetail.allSatisfy { $0.attribution == "excluded" && $0.share == 1 })
        // 拆分会话：同一 id 出现在两个项目，share 之和为 1
        var shares: [String: Double] = [:]
        for p in r.projects { for s in p.sessionsDetail where s.attribution == "split" { shares[s.id, default: 0] += s.share } }
        XCTAssertFalse(shares.isEmpty)
        for (id, sum) in shares { XCTAssertEqual(sum, 1, accuracy: 0.0001, id) }
    }

    // MARK: - 变体

    private func mutatedFixture(_ mutate: (inout [String: Any]) -> Void) throws -> Data {
        var obj = try JSONSerialization.jsonObject(with: Data(contentsOf: DefaultPaths.sampleFixture)) as! [String: Any]
        mutate(&obj)
        return try JSONSerialization.data(withJSONObject: obj)
    }

    func testNewerSchemaStillDecodes() throws {
        let data = try mutatedFixture { $0["schema_version"] = 2 }
        let r = try ReportDecoder.decode(data)
        XCTAssertTrue(r.isNewerSchema)
    }

    func testUnknownAgentKeyDecodes() throws {
        let data = try mutatedFixture { obj in
            var projects = obj["projects"] as! [[String: Any]]
            var agents = projects[0]["by_agent"] as! [[String: Any]]
            agents[0]["agent"] = "gemini-cli"
            agents[0]["label"] = "Gemini CLI"
            projects[0]["by_agent"] = agents
            obj["projects"] = projects
        }
        let r = try ReportDecoder.decode(data)
        XCTAssertEqual(r.projects[0].byAgent[0].agent, "gemini-cli")
        XCTAssertEqual(r.projects[0].byAgent[0].label, "Gemini CLI")
    }

    func testBrokenCostFailsReconciliation() throws {
        let data = try mutatedFixture { obj in
            var projects = obj["projects"] as! [[String: Any]]
            projects[0]["cost"] = (projects[0]["cost"] as! Double) + 1.5
            obj["projects"] = projects
        }
        let rec = Reconciliation(report: try ReportDecoder.decode(data))
        XCTAssertFalse(rec.cost.ok)
        XCTAssertEqual(rec.cost.diff, -1.5, accuracy: 0.0001)
    }

    func testInvalidJSONThrowsReadableError() {
        XCTAssertThrowsError(try ReportDecoder.decode(Data("{\"schema_version\": 1,".utf8))) { e in
            guard case DataSourceError.invalidJSON = e else { return XCTFail("got \(e)") }
            XCTAssertTrue((e as? LocalizedError)?.errorDescription?.contains("Not valid JSON") == true)
        }
    }

    func testMissingFieldNamesThePath() throws {
        let data = try mutatedFixture { obj in
            var projects = obj["projects"] as! [[String: Any]]
            projects[1].removeValue(forKey: "by_day")
            obj["projects"] = projects
        }
        XCTAssertThrowsError(try ReportDecoder.decode(data)) { e in
            let msg = (e as? LocalizedError)?.errorDescription ?? ""
            XCTAssertTrue(msg.contains("projects[1].by_day"), msg)
        }
    }

    func testEmptyInputIsReported() {
        XCTAssertThrowsError(try ReportDecoder.decode(Data("  \n".utf8))) { e in
            guard case DataSourceError.emptyInput = e else { return XCTFail("got \(e)") }
        }
    }

    func testFileDataSourceMissingFile() async {
        do {
            _ = try await FileDataSource(url: URL(fileURLWithPath: "/nonexistent/aicost.json")).load()
            XCTFail("expected error")
        } catch {
            XCTAssertEqual(error as? DataSourceError, .fileNotFound("/nonexistent/aicost.json"))
        }
    }

    func testCLIDataSourceReadsStdout() async throws {
        let cmd = "cat '\(DefaultPaths.sampleFixture.path)'"
        let r = try await CLIDataSource(command: cmd).load()
        XCTAssertEqual(r.schemaVersion, 1)
    }

    func testCLIDataSourceReportsFailure() async {
        do {
            _ = try await CLIDataSource(command: "echo boom >&2; exit 3").load()
            XCTFail("expected error")
        } catch let DataSourceError.commandFailed(_, status, stderr) {
            XCTAssertEqual(status, 3)
            XCTAssertTrue(stderr.contains("boom"))
        } catch {
            XCTFail("got \(error)")
        }
    }

    func testDataOverrideArgument() {
        XCTAssertEqual(DefaultPaths.dataOverride(arguments: ["x", "--data", "/tmp/a.json"], environment: [:])?.path, "/tmp/a.json")
        XCTAssertEqual(DefaultPaths.dataOverride(arguments: ["x"], environment: ["AICOST_DATA": "/tmp/b.json"])?.path, "/tmp/b.json")
        XCTAssertNil(DefaultPaths.dataOverride(arguments: ["x"], environment: [:]))
    }
}
