import Foundation
import CoreFoundation
import XCTest
@testable import KanjoCore

// Set KANJO_PARITY_DUMP to a path to regenerate the Swift golden file.
final class ParityDumpTests: KanjoTestCase {
    func testDump() throws {
        var report = try ReportDecoder.decode(Data(contentsOf: DefaultPaths.sampleFixture))
        let scenarios = [
            ("America/New_York", "2026-10-24T07:00:00Z"),
            ("Asia/Shanghai", "2026-10-24T07:00:00Z"),
            ("Europe/Berlin", "2026-10-24T07:00:00Z"),
            ("America/New_York", "2026-03-08T07:30:00Z"), // DST transition
            ("America/New_York", "2026-10-26T04:30:00Z"), // Monday 00:30
            ("Asia/Shanghai", "2026-01-31T12:00:00Z"),
            ("Europe/Berlin", "2025-02-28T12:00:00Z"),
            ("America/New_York", "2024-02-29T12:00:00Z"),
        ]
        func cents(_ x: Double) -> Int { Int((x * 100).rounded()) }
        func stamp(_ date: Date) -> String { ISO8601DateFormatter().string(from: date) }
        var result: [String: Any] = [:]
        for (zone, instant) in scenarios {
            report.timezone = zone
            let tz = TimeZone(identifier: zone)!
            let cal = RangeEngine.calendar(timezone: tz)
            let now = ReportDates.parseTimestamp(instant)!
            var ranges: [String: Any] = [:]
            for range in TimeRange.allCases {
                let f = RangeEngine.filtered(report, range: RangeEngine.spec(range, report: report, now: now), fallbackAgentFor: RangeEngine.fallbackAgent)
                let share = ShareSummary.build(report: report, rangeRaw: range.rawValue, now: now)
                let t = share.totals
                let projects = Dictionary(uniqueKeysWithValues: f.projects.map { p in
                    (p.id, ["cost": cents(p.cost), "tokens": p.tokens, "sessions": p.sessions, "agents": Dictionary(uniqueKeysWithValues: p.byAgent.map { ($0.agent, ["cost": cents($0.cost), "tokens": $0.tokens.total]) })] as [String: Any])
                })
                var agentCosts: [String: Double] = [:]
                var agentTokens: [String: Int] = [:]
                for project in f.projects {
                    for agent in project.byAgent {
                        agentCosts[agent.agent, default: 0] += agent.cost
                        agentTokens[agent.agent, default: 0] += agent.tokens.total
                    }
                }
                for session in f.unattributed.sessionsDetail + f.excluded.sessionsDetail {
                    let (cost, tokens) = f.spec.inRangeCostAndTokens(for: session)
                    agentCosts[session.agent, default: 0] += cost
                    agentTokens[session.agent, default: 0] += tokens
                }
                let agents = Dictionary(uniqueKeysWithValues: Set(agentCosts.keys).union(agentTokens.keys).map {
                    ($0, ["cost": cents(agentCosts[$0, default: 0]), "tokens": agentTokens[$0, default: 0]])
                })
                let models = Dictionary(uniqueKeysWithValues: ModelAggregation.aggregate(in: f).map { ($0.id, ["cost": cents($0.cost), "tokens": $0.tokens.total, "estimated": $0.estimated] as [String: Any]) })
                ranges[range.rawValue] = ["start": f.spec.start.map(stamp) as Any? ?? NSNull(), "end": f.spec.end.map(stamp) as Any? ?? NSNull(), "agentStarts": f.spec.agentStarts.mapValues(stamp), "cost": cents(f.cost), "tokens": f.tokens, "sessions": f.sessions, "projects": projects, "models": models,
                    "agents": agents, "shareRows": Dictionary(uniqueKeysWithValues: share.agentRows.map { row in (row.agent, ["sessions": row.sessionCount ?? 0, "input": row.tokenBreakdown.input, "output": row.tokenBreakdown.output, "cacheRead": row.tokenBreakdown.cacheRead, "cacheWrite": row.tokenBreakdown.cacheWrite, "thinking": row.tokenBreakdown.thinking, "multiplier": row.multiplier.map { cents($0) } as Any? ?? NSNull()] as [String: Any]) }), "share": ["cost": cents(t.cost), "tokens": t.tokens, "sessions": t.sessions, "agents": t.agentsCount, "input": t.input, "output": t.output, "cacheRead": t.cacheRead, "cacheWrite": t.cacheWrite, "thinking": t.thinking]]
            }
            let subs = Dictionary(uniqueKeysWithValues: SubscriptionValue.rows(of: report, now: now).map { row in
                let sub = report.subscriptions![row.agent]!
                return (row.agent, ["plan": sub.plan, "start": sub.cycleStart, "end": sub.cycleEnd, "value": cents(row.usage), "multiplier": row.multiplier.map { Int(($0 * 100).rounded()) } as Any? ?? NSNull()] as [String: Any])
            })
            let quotas = Dictionary(uniqueKeysWithValues: (report.quotaWindows ?? [:]).map { agent, q in
                (agent, SubscriptionValue.quotaRows(q, timezone: tz, now: now).map { row in
                    let reset = row.id == "weekly" ? q.weeklyResetsAt : (row.id == "five_hour" ? q.fiveHourResetsAt : q.extraWindows?.first { $0.id == row.id }?.resetsAt)
                    return ["id": row.id, "reset": reset as Any? ?? NSNull(), "ended": row.detail == L10n.tr("overview.quota.ended"), "percent": row.percent as Any? ?? NSNull()] as [String: Any]
                })
            })
            let heat = Dictionary(uniqueKeysWithValues: report.projects.map { p in
                (p.id, HeatStrip.weekly(p.byDay, endingOn: now, fallbackAgent: RangeEngine.fallbackAgent(for: p), calendar: cal).map { ["start": stamp($0.start), "cost": cents($0.cost), "tokens": $0.tokens, "agents": $0.byAgent.mapValues(cents), "agentTokens": $0.byAgentTokens] as [String: Any] })
            })
            let reference = WeeklyTokens.reference(now: now, generatedAt: ReportDates.parseTimestamp(report.generatedAt))
            result[zone + "|" + instant] = ["ranges": ranges, "subscriptions": subs, "quotas": quotas, "weeklyTokens": WeeklyTokens.since(mondayOfWeekContaining: reference, projects: report.projects, calendar: cal), "heat": heat]
        }
        if let path = ProcessInfo.processInfo.environment["KANJO_PARITY_DUMP"] {
            let json = try Self.formattedJSON(result)
            try (json + "\n").write(to: URL(fileURLWithPath: path), atomically: true, encoding: .utf8)
        } else {
            let root = DefaultPaths.sampleFixture.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            let golden = try Data(contentsOf: root.appendingPathComponent("parity/mac.json"))
            let expected = try JSONSerialization.jsonObject(with: golden) as! NSDictionary
            XCTAssertTrue(expected.isEqual(to: result), "Swift parity dump changed; regenerate and compare both goldens")
        }
    }

    private static func formattedJSON(_ value: Any, depth: Int = 0) throws -> String {
        let indent = String(repeating: "  ", count: depth)
        let next = indent + "  "
        if let object = value as? [String: Any] {
            guard !object.isEmpty else { return "{}" }
            let entries = try object.keys.sorted().map { key in
                try next + formattedJSON(key) + ": " + formattedJSON(object[key]!, depth: depth + 1)
            }
            return "{\n" + entries.joined(separator: ",\n") + "\n" + indent + "}"
        }
        if let array = value as? [Any] {
            guard !array.isEmpty else { return "[]" }
            let entries = try array.map { try next + formattedJSON($0, depth: depth + 1) }
            return "[\n" + entries.joined(separator: ",\n") + "\n" + indent + "]"
        }
        if let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
           ["f", "d"].contains(String(cString: number.objCType)) {
            let text = String(number.doubleValue)
            return text.hasSuffix(".0") ? String(text.dropLast(2)) : text
        }
        let data = try JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed, .withoutEscapingSlashes])
        return String(decoding: data, as: UTF8.self)
    }
}
