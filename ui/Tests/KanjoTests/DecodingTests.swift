import XCTest
@testable import KanjoCore

final class DecodingTests: KanjoTestCase {
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
        XCTAssertEqual(r.costNoteDisplayText, L10n.tr("common.cost_note_default"))
        XCTAssertTrue((6...8).contains(r.projects.count))
    }

    func testQuotaWindowUsageDecodes() throws {
        let q = try XCTUnwrap(try loadFixture().quotaWindows?["claude"])
        XCTAssertEqual(q.weeklyUsedPercent, 57)
        XCTAssertEqual(q.fiveHourUsedPercent, 13)
        XCTAssertEqual(q.fiveHourWindowHours, 5)
        // 旧导出没有这些字段：仍能解码，值为 nil
        let old = #"{"weekly_resets_at":"2026-10-27T14:00:00Z","weekly_window_hours":168,"five_hour_resets_at":null,"source":"tokei"}"#
        let w = try JSONDecoder().decode(QuotaWindow.self, from: Data(old.utf8))
        XCTAssertNil(w.weeklyUsedPercent)
        XCTAssertNil(w.fiveHourWindowHours)
    }

    func testCostNoteDisplayText() throws {
        var r = try loadFixture()
        r.costNote = "API-equivalent cost estimated from public API prices. Not actual subscription spend."
        XCTAssertEqual(r.costNoteDisplayText, L10n.tr("common.cost_note_default"))

        r.costNote = "   Custom cost note   "
        XCTAssertEqual(r.costNoteDisplayText, "Custom cost note")

        r.costNote = ""
        XCTAssertNil(r.costNoteDisplayText)

        r.costNote = "   \n\t  "
        XCTAssertNil(r.costNoteDisplayText)
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
            let agentKeys = Set(p.byAgent.map(\.agent))
            for d in p.byDay {
                let split = try XCTUnwrap(d.byAgent, "\(p.id) \(d.day) by_agent")
                XCTAssertEqual(split.values.reduce(0, +), d.cost, accuracy: 0.01, "\(p.id) \(d.day) by_agent sum")
                XCTAssertTrue(Set(split.keys).isSubset(of: agentKeys), "\(p.id) \(d.day) by_agent keys")
                let toks = try XCTUnwrap(d.byAgentTokens, "\(p.id) \(d.day) by_agent_tokens")
                XCTAssertEqual(toks.values.reduce(0, +), d.tokens, "\(p.id) \(d.day) by_agent_tokens sum")
                XCTAssertEqual(Set(toks.keys), Set(split.keys), "\(p.id) \(d.day) by_agent_tokens keys")
            }
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
        XCTAssertEqual(agents, ["claude", "codex", "antigravity", "grok", "qwen", "commandcode", "minimax", "opencode", "copilot"])
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

    func testSubscriptionsDecode() throws {
        let r = try loadFixture()
        let claude = try XCTUnwrap(r.subscriptions?["claude"])
        XCTAssertEqual(claude.plan, "max_5x")
        XCTAssertEqual(claude.planLabel, "Claude Max 5x")
        XCTAssertEqual(claude.monthlyPriceUsd, 100)
        XCTAssertEqual(claude.cycleStart, "2026-09-24T16:00:00Z")
        XCTAssertEqual(claude.cycleEnd, "2026-10-24T16:00:00Z")
        XCTAssertEqual(claude.anchorDay, 25)
        XCTAssertEqual(claude.cycleSource, "subscription_date")
        XCTAssertFalse(claude.extraUsageEnabled)
        XCTAssertEqual(claude.source, "detected")
        let codex = try XCTUnwrap(r.subscriptions?["codex"])
        XCTAssertEqual(codex.plan, "plus")
        XCTAssertEqual(codex.planLabel, "ChatGPT Plus")
        XCTAssertEqual(codex.monthlyPriceUsd, 20)
        XCTAssertNil(codex.anchorDay)
        XCTAssertEqual(codex.cycleSource, "rolling_30d")
        let generatedAt = try XCTUnwrap(ReportDates.parseTimestamp(r.generatedAt))
        let cycleStart = try XCTUnwrap(ReportDates.parseTimestamp(codex.cycleStart))
        XCTAssertEqual(generatedAt.timeIntervalSince(cycleStart), 30 * 24 * 60 * 60)
        XCTAssertEqual(codex.cycleEnd, r.generatedAt)
        XCTAssertEqual(codex.source, "detected")
        let grok = try XCTUnwrap(r.subscriptions?["grok"])
        XCTAssertEqual(grok.plan, "supergrok")
        XCTAssertEqual(grok.planLabel, "SuperGrok")
        XCTAssertEqual(grok.monthlyPriceUsd, 30)
        XCTAssertNil(grok.anchorDay)
        XCTAssertEqual(grok.cycleSource, "rolling_30d")
        XCTAssertEqual(grok.source, "detected")
        let antigravity = try XCTUnwrap(r.subscriptions?["antigravity"])
        XCTAssertEqual(antigravity.plan, "google_ai_pro")
        XCTAssertEqual(antigravity.planLabel, "Google AI Pro")
        XCTAssertEqual(antigravity.monthlyPriceUsd, 19.99)
        XCTAssertNil(antigravity.anchorDay)
        XCTAssertEqual(antigravity.cycleSource, "rolling_30d")
        XCTAssertEqual(antigravity.source, "detected")
        let copilot = try XCTUnwrap(r.subscriptions?["copilot"])
        XCTAssertEqual(copilot.plan, "pro")
        XCTAssertEqual(copilot.planLabel, "Copilot Pro")
        XCTAssertEqual(copilot.monthlyPriceUsd, 10)
        XCTAssertNil(copilot.anchorDay)
        XCTAssertEqual(copilot.cycleSource, "rolling_30d")
        XCTAssertEqual(copilot.source, "manual")
        XCTAssertNil(r.subscriptions?["qwen"])
    }

    func testMissingSubscriptionsDecodesAsNil() throws {
        let data = try mutatedFixture { $0.removeValue(forKey: "subscriptions") }
        XCTAssertNil(try ReportDecoder.decode(data).subscriptions)
    }

    func testNullSubscriptionsDecodesAsNil() throws {
        let data = try mutatedFixture { $0["subscriptions"] = NSNull() }
        XCTAssertNil(try ReportDecoder.decode(data).subscriptions)
    }

    func testNullMonthlyPriceDecodes() throws {
        let data = try mutatedFixture { obj in
            var subs = obj["subscriptions"] as! [String: Any]
            var claude = subs["claude"] as! [String: Any]
            claude["monthly_price_usd"] = NSNull()
            subs["claude"] = claude
            obj["subscriptions"] = subs
        }
        let r = try ReportDecoder.decode(data)
        XCTAssertNil(r.subscriptions?["claude"]?.monthlyPriceUsd)
        XCTAssertEqual(r.subscriptions?["claude"]?.planLabel, "Claude Max 5x")
        XCTAssertNil(SubscriptionValue.multiplier(usage: 10, monthlyPriceUsd: r.subscriptions?["claude"]?.monthlyPriceUsd))
    }

    func testDayWithoutByAgentDecodesAsNil() throws {
        let json = #"[{"day": "2026-10-22", "cost": 3.2, "tokens": 120000},"#
            + #"{"day": "2026-10-23", "cost": 1, "tokens": 5, "by_agent": {"claude": 0.75, "codex": 0.25}}]"#
        let days = try JSONDecoder().decode([DayCost].self, from: Data(json.utf8))
        XCTAssertNil(days[0].byAgent)
        XCTAssertEqual(days[1].byAgent, ["claude": 0.75, "codex": 0.25])
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
            _ = try await FileDataSource(url: URL(fileURLWithPath: "/nonexistent/kanjo.json")).load()
            XCTFail("expected error")
        } catch {
            XCTAssertEqual(error as? DataSourceError, .fileNotFound("/nonexistent/kanjo.json"))
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
        XCTAssertEqual(DefaultPaths.dataOverride(arguments: ["x"], environment: ["KANJO_DATA": "/tmp/b.json"])?.path, "/tmp/b.json")
        XCTAssertNil(DefaultPaths.dataOverride(arguments: ["x"], environment: [:]))
    }

    func testResolvedCLIDirectoryFallsBackInOrder() throws {
        let fm = FileManager.default
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("build/kanjo-cli-\(UUID().uuidString)")
        defer { try? fm.removeItem(at: root) }
        let home = root.appendingPathComponent("home")
        let installed = DefaultPaths.installedCLIDirectories(home: home)
        XCTAssertEqual(installed.map(\.path), [home.path + "/.local/share/kanjo/cli", "/usr/local/share/kanjo/cli"])

        let repo = root.appendingPathComponent("repo/cli")
        let user = installed[0]
        let bundled = root.appendingPathComponent("bundle/cli")
        let system = root.appendingPathComponent("system/cli")
        let candidates = [bundled, repo, user, system]
        XCTAssertNil(DefaultPaths.resolvedCLIDirectory(candidates: candidates))

        // 只建目录不建 kanjo/ 包，不算。
        try fm.createDirectory(at: user, withIntermediateDirectories: true)
        XCTAssertNil(DefaultPaths.resolvedCLIDirectory(candidates: candidates))

        try fm.createDirectory(at: system.appendingPathComponent("kanjo"), withIntermediateDirectories: true)
        try Data().write(to: system.appendingPathComponent("kanjo/__init__.py"))
        XCTAssertEqual(DefaultPaths.resolvedCLIDirectory(candidates: candidates), system)
        try fm.createDirectory(at: user.appendingPathComponent("kanjo"), withIntermediateDirectories: true)
        try Data().write(to: user.appendingPathComponent("kanjo/__init__.py"))
        XCTAssertEqual(DefaultPaths.resolvedCLIDirectory(candidates: candidates)?.path, user.path)

        try fm.createDirectory(at: repo.appendingPathComponent("kanjo"), withIntermediateDirectories: true)
        try Data().write(to: repo.appendingPathComponent("kanjo/__init__.py"))
        XCTAssertEqual(DefaultPaths.resolvedCLIDirectory(candidates: candidates)?.path, repo.path)
        try fm.createDirectory(at: bundled.appendingPathComponent("kanjo"), withIntermediateDirectories: true)
        XCTAssertEqual(DefaultPaths.resolvedCLIDirectory(candidates: candidates), repo)
        try Data().write(to: bundled.appendingPathComponent("kanjo/__init__.py"))
        XCTAssertEqual(DefaultPaths.resolvedCLIDirectory(candidates: candidates), bundled)
    }

    func testRepoCLIDirectoryIsFoundFromSource() {
        #if DEBUG
        XCTAssertNotNil(DefaultPaths.packageRoot)
        XCTAssertEqual(DefaultPaths.resolvedCLIDirectory()?.path, DefaultPaths.cliDirectory?.path)
        #else
        XCTAssertNil(DefaultPaths.packageRoot)
        XCTAssertNil(DefaultPaths.cliDirectory)
        #endif
    }
}
