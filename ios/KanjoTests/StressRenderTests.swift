import KanjoCore
import SwiftUI
import UIKit
import XCTest
@testable import Kanjo

/// Offscreen stress renders of the iOS companion against `kanjo export --mobile`-shaped
/// snapshots mutated from `sample-snapshot.json`. Catches crashes, NaN bar widths, and
/// non-finite layout frames without touching a physical device or iCloud.
@MainActor
final class StressRenderTests: XCTestCase {
    private let phone = CGSize(width: 390, height: 844)

    // MARK: - LayoutMath (NaN / divide-by-zero)

    func testBarWidthRejectsZeroAndNonFinite() {
        XCTAssertEqual(LayoutMath.barWidth(available: 100, fraction: 0), 0)
        XCTAssertEqual(LayoutMath.barWidth(available: 100, fraction: .nan), 0)
        XCTAssertEqual(LayoutMath.barWidth(available: 100, fraction: .infinity), 0)
        XCTAssertEqual(LayoutMath.barWidth(available: 0, fraction: 0.5), 0)
        XCTAssertEqual(LayoutMath.barWidth(available: .nan, fraction: 0.5), 0)
        let half = LayoutMath.barWidth(available: 100, fraction: 0.5)
        XCTAssertEqual(half, 50, accuracy: 0.01)
        XCTAssertTrue(half.isFinite)
    }

    func testSegmentWidthsWithZeroTotal() {
        let widths = LayoutMath.segmentWidths(available: 100, weights: [0, 0, 0])
        XCTAssertEqual(widths, [0, 0, 0])
        let mixed = LayoutMath.segmentWidths(available: 100, weights: [1, 0, .nan, 3])
        XCTAssertEqual(mixed.count, 4)
        XCTAssertEqual(mixed[1], 0)
        XCTAssertEqual(mixed[2], 0)
        XCTAssertTrue(mixed[0].isFinite && mixed[0] > 0)
        XCTAssertTrue(mixed[3].isFinite && mixed[3] > 0)
    }

    func testFmtRejectsNonFiniteMoneyAndPercent() {
        XCTAssertEqual(Fmt.money(.nan), "—")
        XCTAssertEqual(Fmt.money(.infinity), "—")
        XCTAssertEqual(Fmt.percent(.nan), "—")
        XCTAssertEqual(Fmt.percent(.infinity), "—")
        XCTAssertEqual(Fmt.money(0), "$0.00")
        XCTAssertEqual(Fmt.percent(0), "0.0%")
        XCTAssertEqual(Fmt.percent(0.5), "50%")
    }

    // MARK: - Stress fixtures → main views

    func testStressRendersAllFixtures() throws {
        let fixtures = try StressFixtures.all()
        XCTAssertGreaterThanOrEqual(fixtures.count, 10)
        for fixture in fixtures {
            let report = try ReportDecoder.decode(fixture.data)
            assertConsistentNumbers(in: report, label: fixture.name)
            renderMainViews(report: report, label: fixture.name)
        }
    }

    func testZeroCostProjectDetailDoesNotProduceNaNBars() throws {
        let report = try StressFixtures.decode(.zeroCostProject)
        let project = try XCTUnwrap(report.projects.first)
        XCTAssertEqual(project.cost, 0)
        let maxCost = project.byAgent.map(\.cost).max() ?? 0
        for agent in project.byAgent {
            let width = LayoutMath.barWidth(
                available: 200,
                fraction: maxCost > 0 ? agent.cost / maxCost : 0
            )
            XCTAssertTrue(width.isFinite, "agent bar width must be finite")
            XCTAssertEqual(width, 0)
        }
        let tokenWidths = LayoutMath.segmentWidths(
            available: 200,
            weights: [0, 0, 0, 0].map(Double.init)
        )
        XCTAssertEqual(tokenWidths, [0, 0, 0, 0])
        render(ProjectDetailView(project: project, report: report, range: .all), label: "zero-cost-detail")
    }

    func testEmptyProjectsDoesNotCrashOverview() async throws {
        let report = try StressFixtures.decode(.zeroProjects)
        XCTAssertTrue(report.projects.isEmpty)
        render(OverviewView(report: report), label: "zero-projects-overview")
        render(ByModelView(report: report, range: .all), label: "zero-projects-models")
        // Empty / setup surface stands in for settings-about on iOS (no Settings screen yet).
        let store = SnapshotStore(source: StressFixtures.StaticSource(report: nil))
        await store.load()
        render(RootView(store: store), label: "empty-root-about")
    }

    func testAllTwentyNineAgentsRender() throws {
        let report = try StressFixtures.decode(.allAgents)
        let agents = Set(report.projects.flatMap(\.byAgent).map(\.agent))
        XCTAssertEqual(agents.count, AgentColors.all.count)
        let project = try XCTUnwrap(report.projects.first)
        render(ProjectDetailView(project: project, report: report, range: .all), label: "all-agents-detail")
        render(OverviewView(report: report), label: "all-agents-overview")
    }

    func testHideProjectNamesOutput() throws {
        let report = try StressFixtures.decode(.hideProjectNames)
        XCTAssertTrue(report.projects.allSatisfy { $0.name.hasPrefix("Project ") })
        renderMainViews(report: report, label: "hide-names")
    }

    func testStaleSnapshotFortyDaysOld() throws {
        let report = try StressFixtures.decode(.stale40Days)
        let generated = try XCTUnwrap(ReportDates.parseTimestamp(report.generatedAt))
        let age = Date().timeIntervalSince(generated)
        XCTAssertGreaterThan(age, 39 * 24 * 3600)
        render(OverviewView(report: report), label: "stale-overview")
    }

    // MARK: - Render helpers

    private func renderMainViews(report: UsageReport, label: String) {
        render(OverviewView(report: report, deviceName: "Test Mac", accountCode: "ABCD"), label: "\(label)-overview")
        if let project = report.projects.first {
            render(ProjectDetailView(project: project, report: report, range: .all), label: "\(label)-detail")
            // Agents live inside project detail on iOS; also pin first/last when many.
            if report.projects.count > 1, let last = report.projects.last {
                render(ProjectDetailView(project: last, report: report, range: .days30), label: "\(label)-detail-last")
            }
        }
        render(ByModelView(report: report, range: .all), label: "\(label)-models")
    }

    private func render<V: View>(_ view: V, label: String) {
        let hosted = view
            .frame(width: phone.width)
            .environment(\.colorScheme, .light)
        let host = UIHostingController(rootView: hosted)
        let fitting = host.sizeThatFits(in: CGSize(width: phone.width, height: UIView.layoutFittingExpandedSize.height))
        let height = min(max(fitting.height, phone.height), 12_000)
        host.view.bounds = CGRect(x: 0, y: 0, width: phone.width, height: height)
        host.view.backgroundColor = .systemBackground
        host.view.layoutIfNeeded()

        XCTAssertTrue(host.view.bounds.width.isFinite && host.view.bounds.height.isFinite,
                      "\(label): host bounds non-finite")
        assertFiniteFrames(in: host.view, label: label)

        // ImageRenderer path (also used by share / screenshot tooling).
        let renderer = ImageRenderer(content: hosted.frame(height: min(height, phone.height * 2)))
        renderer.scale = 1
        let image = renderer.uiImage
        XCTAssertNotNil(image, "\(label): ImageRenderer returned nil")
        if let image {
            XCTAssertGreaterThan(image.size.width, 0, "\(label): empty image width")
            XCTAssertTrue(image.size.width.isFinite && image.size.height.isFinite, "\(label): image size non-finite")
        }

        // Layer snapshot path.
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let snap = UIGraphicsImageRenderer(bounds: host.view.bounds, format: format).image { ctx in
            host.view.layer.render(in: ctx.cgContext)
        }
        XCTAssertGreaterThan(snap.size.width, 0, "\(label): layer snapshot empty")
    }

    private func assertFiniteFrames(in root: UIView, label: String) {
        var stack: [UIView] = [root]
        var checked = 0
        while let view = stack.popLast() {
            checked += 1
            let frame = view.frame
            XCTAssertTrue(frame.origin.x.isFinite && frame.origin.y.isFinite,
                          "\(label): non-finite origin in \(type(of: view))")
            XCTAssertTrue(frame.size.width.isFinite && frame.size.height.isFinite,
                          "\(label): non-finite size in \(type(of: view)) \(frame)")
            XCTAssertFalse(frame.size.width.isNaN || frame.size.height.isNaN,
                           "\(label): NaN size in \(type(of: view))")
            // Soft overflow check: a leaf label wider than the phone by a large margin
            // usually means text escaped its container without truncation.
            if let labelView = view as? UILabel, let text = labelView.text, !text.isEmpty {
                let maxWidth = phone.width + 40
                XCTAssertLessThanOrEqual(labelView.bounds.width, maxWidth,
                                         "\(label): UILabel overflow «\(text.prefix(40))…» width=\(labelView.bounds.width)")
            }
            stack.append(contentsOf: view.subviews)
            if checked > 50_000 { break }
        }
    }

    private func assertConsistentNumbers(in report: UsageReport, label: String) {
        let money = Fmt.money(report.totals.cost, currency: report.currency)
        XCTAssertFalse(money.lowercased().contains("nan"), "\(label): money NaN")
        XCTAssertFalse(money.contains("∞") || money.contains("inf"), "\(label): money inf")
        let tokens = Fmt.tokens(report.totals.tokens.total)
        XCTAssertFalse(tokens.lowercased().contains("nan"), "\(label): tokens NaN")
        for project in report.projects.prefix(5) {
            let m = Fmt.money(project.cost, currency: report.currency)
            XCTAssertEqual(m, Fmt.money(project.cost, currency: report.currency), "\(label): money unstable")
            XCTAssertFalse(m.lowercased().contains("nan"))
        }
    }
}

// MARK: - Fixtures

private enum StressFixtures {
    enum Kind: String, CaseIterable {
        case zeroProjects
        case oneProject
        case twoHundredProjects
        case longCJKEmojiNames
        case hugeTinyNumbers
        case allAgents
        case missingOptionals
        case subscriptionsWithCycles
        case subscriptionsWithoutCycles
        case quotaEndedAndNull
        case stale40Days
        case hideProjectNames
        case zeroTotals
        case zeroCostProject
    }

    struct Fixture {
        let name: String
        let data: Data
    }

    final class StaticSource: SnapshotSource {
        var report: UsageReport?
        init(report: UsageReport?) { self.report = report }
        func load() async throws -> UsageReport? { report }
    }

    static func all() throws -> [Fixture] {
        try Kind.allCases.map { kind in
            Fixture(name: kind.rawValue, data: try data(for: kind))
        }
    }

    static func decode(_ kind: Kind) throws -> UsageReport {
        try ReportDecoder.decode(data(for: kind))
    }

    static func data(for kind: Kind) throws -> Data {
        var json = try baseJSON()
        switch kind {
        case .zeroProjects:
            json["projects"] = []
            json["totals"] = zeroTotalsDict()
            clearBucketUsage(&json)
        case .oneProject:
            if let projects = json["projects"] as? [[String: Any]], let first = projects.first {
                json["projects"] = [first]
                recomputeTotals(&json)
            }
        case .twoHundredProjects:
            json["projects"] = makeProjects(count: 200, name: { "Repo \($0)" })
            recomputeTotals(&json)
        case .longCJKEmojiNames:
            let names = [
                String(repeating: "超长中文项目名🚀", count: 12),
                "日本語プロジェクト名をとても長くしたもの🌸" + String(repeating: "漢", count: 40),
                "emoji-only-" + String(repeating: "🧠💻🔥", count: 20),
                String(repeating: "A", count: 200),
            ]
            json["projects"] = names.enumerated().map { i, name in
                makeProject(index: i + 1, name: name, cost: Double(100 - i), agent: "claude")
            }
            recomputeTotals(&json)
        case .hugeTinyNumbers:
            json["projects"] = [
                makeProject(index: 1, name: "Huge", cost: 1_234_567_890.12,
                            tokens: Tokens(input: 2_000_000_000, output: 1_500_000_000,
                                           cacheRead: 3_000_000_000, cacheWrite: 800_000_000,
                                           thinking: 100_000_000, total: 7_400_000_000),
                            agent: "claude"),
                makeProject(index: 2, name: "Tiny", cost: 0.0004,
                            tokens: Tokens(input: 1, output: 1, cacheRead: 0, cacheWrite: 0,
                                           thinking: 0, total: 2),
                            agent: "codex"),
            ]
            recomputeTotals(&json)
        case .allAgents:
            let agents = AgentColors.all.keys.sorted()
            var byAgent: [[String: Any]] = []
            var byModel: [[String: Any]] = []
            var cost = 0.0
            var totalTokens = 0
            for (i, agent) in agents.enumerated() {
                let c = Double(agents.count - i)
                let t = (i + 1) * 1000
                cost += c
                totalTokens += t
                byAgent.append([
                    "agent": agent,
                    "label": AgentColors.label(for: agent),
                    "cost": c,
                    "tokens": ["input": t / 2, "output": t / 2, "cache_read": 0,
                               "cache_write": 0, "thinking": 0, "total": t],
                    "sessions": 1,
                ])
                byModel.append([
                    "model": "\(agent)-model",
                    "agent": agent,
                    "cost": c,
                    "tokens": ["input": t / 2, "output": t / 2, "cache_read": 0,
                               "cache_write": 0, "thinking": 0, "total": t],
                    "estimated": false,
                ])
            }
            json["projects"] = [[
                "id": "project-1",
                "name": "AllAgents",
                "cost": cost,
                "tokens": ["input": totalTokens / 2, "output": totalTokens / 2, "cache_read": 0,
                           "cache_write": 0, "thinking": 0, "total": totalTokens],
                "sessions": agents.count,
                "first_active": "2026-10-01",
                "last_active": "2026-10-23",
                "by_agent": byAgent,
                "by_model": byModel,
                "by_day": [[
                    "day": "2026-10-20",
                    "cost": cost,
                    "tokens": totalTokens,
                    "by_agent": Dictionary(uniqueKeysWithValues: agents.enumerated().map {
                        ($1, Double(agents.count - $0))
                    }),
                    "by_agent_tokens": Dictionary(uniqueKeysWithValues: agents.enumerated().map {
                        ($1, ($0 + 1) * 1000)
                    }),
                ]],
                "sessions_detail": agents.enumerated().map { i, agent in
                    [
                        "agent": agent,
                        "started": "2026-10-20T0\(i % 10):00:00Z",
                        "ended": "2026-10-20T0\(i % 10):30:00Z",
                        "cost": Double(agents.count - i),
                        "tokens": ["total": (i + 1) * 1000],
                        "models": ["\(agent)-model"],
                    ] as [String: Any]
                },
            ]]
            recomputeTotals(&json)
        case .missingOptionals:
            for key in ["config", "quota_windows", "subscriptions", "generated_by", "timezone", "perf_by_day"] {
                json.removeValue(forKey: key)
            }
            if var projects = json["projects"] as? [[String: Any]] {
                for i in projects.indices {
                    for key in ["config", "paths", "remote", "path_missing", "by_branch"] {
                        projects[i].removeValue(forKey: key)
                    }
                    if var sessions = projects[i]["sessions_detail"] as? [[String: Any]] {
                        for s in sessions.indices {
                            for key in ["id", "title", "cwd", "branch", "label", "share",
                                        "attribution", "subagents", "by_day"] {
                                sessions[s].removeValue(forKey: key)
                            }
                        }
                        projects[i]["sessions_detail"] = sessions
                    }
                }
                json["projects"] = projects
            }
        case .subscriptionsWithCycles:
            // Sample already has cycle_start / cycle_end; leave as-is.
            break
        case .subscriptionsWithoutCycles:
            json.removeValue(forKey: "subscriptions")
        case .quotaEndedAndNull:
            json["quota_windows"] = [
                "claude": [
                    "weekly_resets_at": "2020-01-01T00:00:00Z",
                    "weekly_window_hours": 168,
                    "weekly_used_percent": NSNull(),
                    "five_hour_resets_at": "2020-01-01T00:00:00Z",
                    "five_hour_window_hours": 5,
                    "five_hour_used_percent": NSNull(),
                    "source": "live",
                ],
                "codex": [
                    "weekly_resets_at": "2099-01-01T00:00:00Z",
                    "weekly_window_hours": 168,
                    "weekly_used_percent": 12.0,
                    "five_hour_resets_at": NSNull(),
                    "five_hour_window_hours": NSNull(),
                    "five_hour_used_percent": NSNull(),
                    "source": "live",
                ],
            ]
        case .stale40Days:
            // "Today" in this worktree context is 2026-11-21 → 40 days earlier ≈ 2026-10-12.
            json["generated_at"] = "2026-10-12T12:00:00Z"
        case .hideProjectNames:
            if var projects = json["projects"] as? [[String: Any]] {
                for i in projects.indices {
                    projects[i]["id"] = "project-\(i + 1)"
                    projects[i]["name"] = "Project \(i + 1)"
                }
                json["projects"] = projects
            }
            json["mobile"] = ["trimmed": true, "hidden_project_names": true]
        case .zeroTotals:
            json["projects"] = []
            json["totals"] = zeroTotalsDict()
            clearBucketUsage(&json)
            json.removeValue(forKey: "subscriptions")
            json.removeValue(forKey: "quota_windows")
        case .zeroCostProject:
            json["projects"] = [[
                "id": "project-1",
                "name": "Empty",
                "cost": 0,
                "tokens": ["input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "total": 0],
                "sessions": 0,
                "by_agent": [
                    ["agent": "claude", "label": "Claude Code", "cost": 0,
                     "tokens": ["input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "total": 0],
                     "sessions": 0],
                    ["agent": "codex", "label": "Codex CLI", "cost": 0,
                     "tokens": ["input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "total": 0],
                     "sessions": 0],
                ],
                "by_model": [],
                "by_day": [],
                "sessions_detail": [],
            ]]
            json["totals"] = zeroTotalsDict()
            clearBucketUsage(&json)
        }
        return try JSONSerialization.data(withJSONObject: json)
    }

    private static func baseJSON() throws -> [String: Any] {
        let url = try XCTUnwrap(
            Bundle(for: SnapshotStore.self).url(forResource: "sample-snapshot", withExtension: "json")
        )
        let data = try Data(contentsOf: url)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private static func zeroTotalsDict() -> [String: Any] {
        [
            "cost": 0,
            "tokens": ["input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "total": 0],
            "sessions": 0,
            "first_active": NSNull(),
            "last_active": NSNull(),
        ]
    }

    private static func clearBucketUsage(_ json: inout [String: Any]) {
        guard var buckets = json["buckets"] as? [String: Any] else { return }
        let empty: [String: Any] = [
            "cost": 0,
            "tokens": ["input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "total": 0],
            "sessions": 0,
            "sessions_detail": [],
        ]
        buckets["unattributed"] = empty
        buckets["excluded"] = empty
        buckets["parse_failed"] = ["sessions": 0]
        json["buckets"] = buckets
    }

    private static func makeProjects(count: Int, name: (Int) -> String) -> [[String: Any]] {
        (1...count).map { i in
            makeProject(index: i, name: name(i), cost: Double(count - i + 1) * 0.37, agent: i % 2 == 0 ? "codex" : "claude")
        }
    }

    private static func makeProject(index: Int, name: String, cost: Double,
                                    tokens: Tokens? = nil, agent: String) -> [String: Any] {
        let t = tokens ?? Tokens(input: index * 10, output: index * 8, cacheRead: index * 100,
                                 cacheWrite: index * 5, thinking: index, total: index * 124)
        return [
            "id": "project-\(index)",
            "name": name,
            "cost": cost,
            "tokens": [
                "input": t.input, "output": t.output, "cache_read": t.cacheRead,
                "cache_write": t.cacheWrite, "thinking": t.thinking, "total": t.total,
            ],
            "sessions": max(1, index % 7),
            "first_active": "2026-09-01",
            "last_active": "2026-10-23",
            "by_agent": [[
                "agent": agent,
                "label": AgentColors.label(for: agent),
                "cost": cost,
                "tokens": [
                    "input": t.input, "output": t.output, "cache_read": t.cacheRead,
                    "cache_write": t.cacheWrite, "thinking": t.thinking, "total": t.total,
                ],
                "sessions": max(1, index % 7),
            ]],
            "by_model": [[
                "model": "\(agent)-model",
                "agent": agent,
                "cost": cost,
                "tokens": [
                    "input": t.input, "output": t.output, "cache_read": t.cacheRead,
                    "cache_write": t.cacheWrite, "thinking": t.thinking, "total": t.total,
                ],
                "estimated": false,
            ]],
            "by_day": [[
                "day": "2026-10-20",
                "cost": cost,
                "tokens": t.total,
                "by_agent": [agent: cost],
                "by_agent_tokens": [agent: t.total],
            ]],
            "sessions_detail": [[
                "agent": agent,
                "started": "2026-10-20T12:00:00Z",
                "ended": "2026-10-20T13:00:00Z",
                "cost": cost,
                "tokens": ["total": t.total],
                "models": ["\(agent)-model"],
            ]],
        ]
    }

    private static func recomputeTotals(_ json: inout [String: Any]) {
        let projects = (json["projects"] as? [[String: Any]]) ?? []
        var cost = 0.0
        var sessions = 0
        var input = 0, output = 0, cacheRead = 0, cacheWrite = 0, thinking = 0, total = 0
        for p in projects {
            cost += (p["cost"] as? Double) ?? 0
            sessions += (p["sessions"] as? Int) ?? 0
            if let tok = p["tokens"] as? [String: Any] {
                input += tok["input"] as? Int ?? 0
                output += tok["output"] as? Int ?? 0
                cacheRead += tok["cache_read"] as? Int ?? 0
                cacheWrite += tok["cache_write"] as? Int ?? 0
                thinking += tok["thinking"] as? Int ?? 0
                total += tok["total"] as? Int ?? 0
            }
        }
        json["totals"] = [
            "cost": cost,
            "tokens": [
                "input": input, "output": output, "cache_read": cacheRead,
                "cache_write": cacheWrite, "thinking": thinking, "total": total,
            ],
            "sessions": sessions,
            "first_active": projects.isEmpty ? NSNull() : "2026-09-01",
            "last_active": projects.isEmpty ? NSNull() : "2026-10-23",
        ]
    }
}
