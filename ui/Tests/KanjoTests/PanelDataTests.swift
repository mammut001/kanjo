import XCTest
@testable import KanjoCore

final class PanelDataTests: XCTestCase {
    func testParseTimestamp() {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        let formatterFraction = ISO8601DateFormatter()
        formatterFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        
        let inputs = [
            "2026-11-18T14:16:50Z",
            "2026-11-18T14:16:50.123Z",
            "2026-11-18T14:16:50.123456Z",
            "2026-11-18T14:16:50+05:30",
            "2026-11-18T14:16:50.123-08:00"
        ]
        
        for input in inputs {
            let expected = input.contains(".") ? formatterFraction.date(from: input) : formatter.date(from: input)
            let actual = ReportDates.parseTimestamp(input)
            
            if let expected = expected, let actual = actual {
                XCTAssertEqual(actual.timeIntervalSince1970, expected.timeIntervalSince1970, accuracy: 0.000001, "Failed for \(input)")
            } else {
                XCTAssertEqual(actual, expected, "Failed for \(input)")
            }
        }
        
        let malformed = [
            "", "garbage", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z",
            "2026-11-18 10:00:00Z", "2026-11-18T10:00:00Zjunk", "2026-11-18T1a:00:00Z"
        ]
        for input in malformed {
            let expected = formatter.date(from: input) ?? formatterFraction.date(from: input)
            let actual = ReportDates.parseTimestamp(input)
            if let expected = expected, let actual = actual {
                XCTAssertEqual(actual.timeIntervalSince1970, expected.timeIntervalSince1970, accuracy: 1e-6, "Failed for \(input)")
            } else {
                XCTAssertEqual(actual, expected, "Failed for \(input)")
            }
        }
    }
    
    func testParseTimestampRandom() {
        var seed: UInt64 = 42
        func lcg() -> UInt64 {
            seed = (6364136223846793005 &* seed &+ 1)
            return seed
        }
        
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]
        let isoFractional = ISO8601DateFormatter()
        isoFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        
        for _ in 0..<500 {
            let year = 2000 + Int(lcg() % 41)
            let month = 1 + Int(lcg() % 12)
            let day = 1 + Int(lcg() % 28) // Simple day
            let hour = Int(lcg() % 24)
            let minute = Int(lcg() % 60)
            let second = Int(lcg() % 60)
            
            let fractionDigits = [0, 1, 3, 6, 9][Int(lcg() % 5)]
            var fracStr = ""
            if fractionDigits > 0 {
                fracStr = "."
                for _ in 0..<fractionDigits { fracStr += String(Int(lcg() % 10)) }
            }
            
            let zones = ["Z", "+05:30", "-08:00"]
            let zone = zones[Int(lcg() % 3)]
            
            let s = String(format: "%04d-%02d-%02dT%02d:%02d:%02d%@%@", year, month, day, hour, minute, second, fracStr, zone)
            
            let ref = (fractionDigits > 0 ? isoFractional : iso).date(from: s)
            let actual = ReportDates.parseTimestamp(s)
            
            XCTAssertNotNil(actual, "Failed for \(s)")
            if let ref = ref, let actual = actual {
                XCTAssertEqual(actual.timeIntervalSince1970, ref.timeIntervalSince1970, accuracy: 1e-6, "Failed for \(s)")
            }
        }
    }

    func testPanelDataEquivalence() {
        // Build synthetic report (simplified for brevity, but includes required fields)
        let report = try! JSONDecoder().decode(UsageReport.self, from: """
        {
            "schema_version": 1,
            "generated_at": "2026-11-18T10:00:00Z",
            "currency": "USD",
            "cost_note": "",
            "config": {"dominant_threshold": 0.8},
            "totals": {"cost": 100, "tokens": {"total": 1000}, "sessions": 10},
            "projects": [
                {
                    "id": "p1", "name": "Project 1", "cost": 100, "tokens": {"total": 1000}, "sessions": 10,
                    "by_agent": [{"agent": "a1", "label": "A1", "cost": 100, "tokens": {"total": 1000}, "sessions": 10}],
                    "by_model": [],
                    "by_day": [{"day": "2026-11-17", "cost": 100, "tokens": 1000}],
                    "sessions_detail": [{"id": "s1", "agent": "a1", "label": "A1", "started": "2026-11-17T10:00:00Z", "ended": "2026-11-17T11:00:00Z", "cost": 100, "tokens": {"total": 1000}, "share": 1, "attribution": "none", "subagents": 0}]
                }
            ],
            "buckets": {
                "unattributed": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "excluded": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "parse_failed": {"sessions": 0, "files": []}
            },
            "subscriptions": {"a1": {"plan": "p", "plan_label": "P", "cycle_start": "2026-11-01T00:00:00Z", "cycle_end": "2026-12-01T00:00:00Z", "cycle_source": "manual", "extra_usage_enabled": false, "source": "manual"}},
            "quota_windows": {"a1": {"weekly_resets_at": "2026-11-19T00:00:00Z", "weekly_window_hours": 168, "source": "tokei"}}
        }
        """.data(using: .utf8)!)
        
        let now = Date(timeIntervalSince1970: 1763460000)
        let fallback: (Project) -> String = { p in dominantAgent(p.byAgent)?.agent ?? p.byAgent.first?.agent ?? "unknown" }
        
        for r in TimeRange.allCases {
            let spec = RangeEngine.spec(r, report: report, now: now)
            let panelData = PanelData.compute(report: report, rangeRaw: r.rawValue, now: now)
            let filtered = RangeEngine.filtered(report, range: spec, fallbackAgentFor: fallback)
            
            XCTAssertNotNil(panelData, "Failed for \(r)")
            XCTAssertEqual(panelData!.filteredReport, filtered, "FilteredReport mismatch for \(r)")
            
            let rows = SubscriptionValue.rows(of: report, now: now)
            XCTAssertEqual(panelData!.subscriptionRows, rows, "SubscriptionRows mismatch for \(r)")
        }
    }

    func testPreparedOverviewAndAgentDataMatchesDirectCalculation() throws {
        let report = try ReportDecoder.decode(Data(contentsOf: DefaultPaths.sampleFixture))
        let now = Date(timeIntervalSince1970: 1_795_000_000)
        let reference = WeeklyTokens.reference(now: now, generatedAt: ReportDates.parseTimestamp(report.generatedAt))
        let end = ReportDates.parseTimestamp(report.generatedAt) ?? report.totals.lastActive.flatMap(ReportDates.parseDay) ?? now
        for range in TimeRange.allCases {
            let data = try XCTUnwrap(PanelData.compute(report: report, rangeRaw: range.rawValue, now: now))
            XCTAssertEqual(data.weeklyTokens, WeeklyTokens.since(mondayOfWeekContaining: reference, projects: report.projects, calendar: .current))
            XCTAssertEqual(data.models, ModelAggregation.aggregate(in: data.filteredReport))
            XCTAssertEqual(data.agentSummary, AgentSummary.build(report: report, filtered: data.filteredReport, now: now))
            for item in data.filteredReport.projects {
                let project = item.projected
                XCTAssertEqual(data.heatWeeks[project.id], HeatStrip.weekly(project.byDay, endingOn: end, fallbackAgent: RangeEngine.fallbackAgent(for: project)))
            }
        }
    }

    func testMatches() {
        let report = try! JSONDecoder().decode(UsageReport.self, from: """
        {
            "schema_version": 1,
            "generated_at": "2026-11-18T10:00:00Z",
            "currency": "USD",
            "cost_note": "",
            "config": {"dominant_threshold": 0},
            "totals": {"cost": 0, "tokens": {"total": 0}, "sessions": 0},
            "projects": [],
            "buckets": {
                "unattributed": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "excluded": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "parse_failed": {"sessions": 0, "files": []}
            }
        }
        """.data(using: .utf8)!)
        
        let now = Date(timeIntervalSince1970: 1763460000) // 2026-11-18T10:00:00Z
        let spec = RangeEngine.spec(.all, report: report, now: now)
        let panelData = PanelData(rangeSpec: spec, filteredReport: FilteredReport(spec: spec, projects: [], unattributed: FilteredBucket(cost: 0, tokens: 0, sessions: 0, sessionsDetail: []), excluded: FilteredBucket(cost: 0, tokens: 0, sessions: 0, sessionsDetail: []), cost: 0, tokens: 0, sessions: 0), subscriptionRows: [], reportGeneratedAt: report.generatedAt, subscriptionsFingerprint: "", now: now)
        
        // True: same report, same range, same day
        XCTAssertTrue(panelData.matches(report: report, spec: spec))
        
        // False: different generatedAt
        var report2 = report
        report2.generatedAt = "2026-11-18T11:00:00Z"
        XCTAssertFalse(panelData.matches(report: report2, spec: spec))
        
        // False: different range
        let spec2 = RangeEngine.spec(.today, report: report, now: now)
        XCTAssertFalse(panelData.matches(report: report, spec: spec2))
        
        // False: today when now moves to next day
        let specToday = RangeEngine.spec(.today, report: report, now: now)
        let panelDataToday = PanelData(rangeSpec: specToday, filteredReport: FilteredReport(spec: specToday, projects: [], unattributed: FilteredBucket(cost: 0, tokens: 0, sessions: 0, sessionsDetail: []), excluded: FilteredBucket(cost: 0, tokens: 0, sessions: 0, sessionsDetail: []), cost: 0, tokens: 0, sessions: 0), subscriptionRows: [], reportGeneratedAt: report.generatedAt, subscriptionsFingerprint: "", now: now)
        
        let laterToday = now.addingTimeInterval(60)
        XCTAssertTrue(panelDataToday.matches(report: report, spec: RangeEngine.spec(.today, report: report, now: laterToday)))
        let tomorrow = now.addingTimeInterval(86400)
        XCTAssertFalse(panelDataToday.matches(report: report, spec: RangeEngine.spec(.today, report: report, now: tomorrow)))

        var changedZone = specToday
        changedZone.calendar.timeZone = TimeZone(secondsFromGMT: 3600)!
        XCTAssertFalse(panelDataToday.matches(report: report, spec: changedZone))
        var changedAgentStarts = specToday
        changedAgentStarts.agentStarts = ["example": now]
        XCTAssertFalse(panelDataToday.matches(report: report, spec: changedAgentStarts))
    }

    func testCanReuseSubscriptionRowsRequiresFreshTimeAndMatchingSubscriptions() {
        let report = try! JSONDecoder().decode(UsageReport.self, from: """
        {
            "schema_version": 1,
            "generated_at": "2026-11-18T10:00:00Z",
            "currency": "USD",
            "cost_note": "",
            "config": {"dominant_threshold": 0},
            "totals": {"cost": 0, "tokens": {"total": 0}, "sessions": 0},
            "projects": [],
            "buckets": {
                "unattributed": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "excluded": {"cost": 0, "tokens": {"total": 0}, "sessions": 0, "sessions_detail": []},
                "parse_failed": {"sessions": 0, "files": []}
            },
            "subscriptions": {"claude": {"plan": "pro", "plan_label": "Claude Pro", "monthly_price_usd": 20,
                "cycle_start": "2026-10-25T00:00:00Z", "cycle_end": "2026-11-25T00:00:00Z",
                "anchor_day": 25, "cycle_source": "manual", "extra_usage_enabled": false, "source": "manual"}}
        }
        """.data(using: .utf8)!)

        let base = Date(timeIntervalSince1970: 1_763_462_400)
        let panelData = PanelData.compute(report: report, rangeRaw: TimeRange.all.rawValue, now: base)!
        XCTAssertTrue(panelData.canReuseSubscriptionRows(for: report, now: base.addingTimeInterval(30)))

        var changedPlan = report
        changedPlan.subscriptions?["claude"]?.plan = "max_5x"
        XCTAssertFalse(panelData.canReuseSubscriptionRows(for: changedPlan, now: base.addingTimeInterval(30)))

        XCTAssertFalse(panelData.canReuseSubscriptionRows(for: report, now: base.addingTimeInterval(120)))
    }
}
