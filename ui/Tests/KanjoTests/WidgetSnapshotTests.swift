import XCTest
@testable import KanjoCore

/// 小组件瘦身快照：按日花费、跨天、过期、默认 agent、编解码。
/// 期望值都从输入和日历推出来，不写死未推导的金额。
final class WidgetSnapshotTests: KanjoTestCase {
    private func iso(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        return formatter.string(from: date)
    }

    private func day(_ key: String, _ cost: Double) -> DayCost {
        DayCost(day: key, cost: cost, tokens: 0)
    }

    private func project(id: String, days: [DayCost]) -> Project {
        let cost = days.reduce(0.0) { partial, entry in
            partial + (entry.cost.isFinite ? entry.cost : 0)
        }
        return Project(
            id: id,
            name: "Project \(id)",
            remote: nil,
            paths: [],
            pathMissing: false,
            cost: cost,
            tokens: Tokens(),
            sessions: 0,
            byAgent: [],
            byModel: [],
            byDay: days,
            byBranch: [],
            sessionsDetail: []
        )
    }

    private func key(_ offset: Int, from now: Date, calendar: Calendar) -> String {
        let start = calendar.startOfDay(for: now)
        let date = calendar.date(byAdding: .day, value: offset, to: start)!
        return RangeEngine.dayString(date, calendar: calendar)
    }

    private func fiveHourWindow(reset: Date, percent: Double, source: String) -> QuotaWindow {
        QuotaWindow(
            weeklyResetsAt: iso(reset.addingTimeInterval(7 * 86400)),
            weeklyWindowHours: 168,
            weeklyUsedPercent: nil,
            fiveHourResetsAt: iso(reset),
            fiveHourWindowHours: 5,
            fiveHourUsedPercent: percent,
            source: source
        )
    }

    private func decodeReport(
        projects: [Project],
        generatedAt: String,
        timezone: String?,
        quota: [String: QuotaWindow]?
    ) throws -> UsageReport {
        let projectsJSON = try String(decoding: JSONEncoder().encode(projects), as: UTF8.self)
        let quotaJSON: String
        if let quota {
            quotaJSON = try String(decoding: JSONEncoder().encode(quota), as: UTF8.self)
        } else {
            quotaJSON = "null"
        }
        let timezoneJSON = timezone.map { "\"\($0)\"" } ?? "null"
        let json = """
        {"schema_version":1,"generated_at":"\(generatedAt)","timezone":\(timezoneJSON),"currency":"USD","cost_note":"","totals":{"cost":0,"tokens":{"total":0},"sessions":0},"projects":\(projectsJSON),"quota_windows":\(quotaJSON),"buckets":{"unattributed":{"cost":0,"tokens":{"total":0},"sessions":0,"sessions_detail":[]},"excluded":{"cost":0,"tokens":{"total":0},"sessions":0,"sessions_detail":[]},"parse_failed":{"sessions":0,"files":[]}}}
        """
        return try JSONDecoder().decode(UsageReport.self, from: Data(json.utf8))
    }

    func testDailyCostSumsProjectsFillsMissingDaysAndOrdersOldestFirst() {
        let timeZone = TimeZone(identifier: "UTC")!
        let calendar = RangeEngine.calendar(timezone: timeZone)
        let now = calendar.date(from: DateComponents(year: 2026, month: 11, day: 27, hour: 12))!
        let todayPartA = 1.5
        let todayPartB = 2.5
        let yesterdayCost = 0.75
        let olderCost = 4.0
        let dayCount = 4
        let projectA = project(id: "a", days: [
            day(key(0, from: now, calendar: calendar), todayPartA),
            day(key(-1, from: now, calendar: calendar), yesterdayCost),
            day(key(-3, from: now, calendar: calendar), olderCost),
        ])
        let projectB = project(id: "b", days: [
            day(key(0, from: now, calendar: calendar), todayPartB),
        ])
        let projects = [projectA, projectB]
        let summary = WidgetSnapshot.dailyCosts(
            projects: projects,
            timezoneIdentifier: "UTC",
            now: now,
            dayCount: dayCount
        )

        let offsets = (0..<dayCount).map { -(dayCount - 1 - $0) }
        let expectedKeys = offsets.map { key($0, from: now, calendar: calendar) }
        let expectedCosts = expectedKeys.map { dayKey in
            projects.flatMap(\.byDay).filter { $0.day == dayKey }.reduce(0.0) { $0 + $1.cost }
        }
        XCTAssertEqual(summary.days.map(\.day), expectedKeys)
        XCTAssertEqual(summary.days.map(\.cost), expectedCosts)
        XCTAssertEqual(summary.todayCost, todayPartA + todayPartB, accuracy: 1e-9)
        XCTAssertEqual(summary.yesterdayCost, yesterdayCost, accuracy: 1e-9)
        XCTAssertEqual(summary.days.first { $0.day == key(-2, from: now, calendar: calendar) }?.cost, 0)
        XCTAssertEqual(summary.days.last?.day, key(0, from: now, calendar: calendar))

        let stored = WidgetSnapshot(
            generatedAt: iso(now),
            timezone: "UTC",
            days: [WidgetDayCost(day: key(0, from: now, calendar: calendar), cost: todayPartA + todayPartB)]
        )
        let recent = stored.recentDays(count: 3, now: now)
        XCTAssertEqual(recent.map(\.day), [-2, -1, 0].map { key($0, from: now, calendar: calendar) })
        XCTAssertEqual(recent.map(\.cost), [0, 0, todayPartA + todayPartB])

        let current = WidgetSnapshot.dailyCosts(projects: projects, timezoneIdentifier: nil, now: now, dayCount: dayCount)
        let explicitCurrent = WidgetSnapshot.dailyCosts(projects: projects, timezone: .current, now: now, dayCount: dayCount)
        XCTAssertEqual(current, explicitCurrent)
        let unknownZone = WidgetSnapshot.dailyCosts(projects: projects, timezoneIdentifier: "Not/AZone", now: now, dayCount: dayCount)
        XCTAssertEqual(unknownZone, explicitCurrent)
    }

    func testDailyCostTimezoneBoundaryShanghaiVersusUTC() throws {
        let shanghai = TimeZone(identifier: "Asia/Shanghai")!
        let utc = TimeZone(identifier: "UTC")!
        let shanghaiCalendar = RangeEngine.calendar(timezone: shanghai)
        let now = shanghaiCalendar.date(from: DateComponents(year: 2026, month: 11, day: 27, hour: 0, minute: 30))!
        let shanghaiKey = RangeEngine.dayString(now, calendar: shanghaiCalendar)
        let utcKey = RangeEngine.dayString(now, calendar: RangeEngine.calendar(timezone: utc))
        XCTAssertNotEqual(shanghaiKey, utcKey)

        let amount = 6.5
        let projects = [project(id: "a", days: [day(shanghaiKey, amount)])]
        let dayCount = 3
        let inShanghai = WidgetSnapshot.dailyCosts(
            projects: projects,
            timezoneIdentifier: "Asia/Shanghai",
            now: now,
            dayCount: dayCount
        )
        let inUTC = WidgetSnapshot.dailyCosts(
            projects: projects,
            timezoneIdentifier: "UTC",
            now: now,
            dayCount: dayCount
        )

        XCTAssertEqual(inShanghai.todayCost, amount, accuracy: 1e-9)
        XCTAssertEqual(inShanghai.yesterdayCost, 0, accuracy: 1e-9)
        XCTAssertEqual(inShanghai.days.last?.day, shanghaiKey)
        XCTAssertEqual(try XCTUnwrap(inShanghai.days.last).cost, amount, accuracy: 1e-9)
        XCTAssertEqual(inUTC.todayCost, 0, accuracy: 1e-9)
        XCTAssertEqual(inUTC.days.last?.day, utcKey)
        XCTAssertFalse(inUTC.days.contains { $0.day == shanghaiKey })
        XCTAssertEqual(inUTC.days.map(\.cost), Array(repeating: 0, count: dayCount))
    }

    func testTodayIsUnknownWhenSnapshotIsFromThePreviousLocalDay() throws {
        let timeZone = TimeZone(identifier: "Asia/Shanghai")!
        let calendar = RangeEngine.calendar(timezone: timeZone)
        let now = calendar.date(from: DateComponents(year: 2026, month: 11, day: 28, hour: 9))!
        let yesterday = calendar.date(byAdding: .day, value: -1, to: now)!
        let todayKey = key(0, from: now, calendar: calendar)
        let staleToday = WidgetSnapshot(
            generatedAt: iso(yesterday),
            timezone: timeZone.identifier,
            days: [WidgetDayCost(day: todayKey, cost: 9)]
        )
        XCTAssertFalse(staleToday.isTodayKnown(now: now))
        XCTAssertNil(staleToday.todayCost(now: now))

        let earlierToday = calendar.date(from: DateComponents(year: 2026, month: 11, day: 28, hour: 1))!
        let known = WidgetSnapshot(
            generatedAt: iso(earlierToday),
            timezone: timeZone.identifier,
            days: [WidgetDayCost(day: todayKey, cost: 9)]
        )
        XCTAssertTrue(known.isTodayKnown(now: now))
        XCTAssertEqual(try XCTUnwrap(known.todayCost(now: now)), 9, accuracy: 1e-9)

        let utc = TimeZone(identifier: "UTC")!
        let generated = RangeEngine.calendar(timezone: utc).date(
            from: DateComponents(year: 2026, month: 11, day: 27, hour: 16, minute: 30)
        )!
        let sameInstantInShanghai = calendar.date(
            from: DateComponents(year: 2026, month: 11, day: 28, hour: 0, minute: 30)
        )!
        XCTAssertEqual(generated.timeIntervalSince(sameInstantInShanghai), 0, accuracy: 1)
        let laterThatShanghaiDay = calendar.date(from: DateComponents(year: 2026, month: 11, day: 28, hour: 10))!
        XCTAssertTrue(WidgetSnapshot.isTodayKnown(generatedAt: iso(generated), timezone: timeZone, now: laterThatShanghaiDay))
        XCTAssertFalse(WidgetSnapshot.isTodayKnown(generatedAt: iso(generated), timezone: utc, now: laterThatShanghaiDay))
        XCTAssertFalse(WidgetSnapshot.isTodayKnown(generatedAt: "not-a-timestamp", timezone: timeZone, now: now))
    }

    func testStaleThresholdIsJustOverTwoHours() {
        let now = Date(timeIntervalSince1970: 1_763_000_000)
        let threshold = WidgetSnapshot.staleThreshold
        XCTAssertEqual(threshold, 2 * 3600)
        XCTAssertFalse(WidgetSnapshot.isStale(generatedAt: iso(now.addingTimeInterval(-threshold)), now: now))
        XCTAssertFalse(WidgetSnapshot.isStale(generatedAt: iso(now.addingTimeInterval(-(threshold - 1))), now: now))
        XCTAssertTrue(WidgetSnapshot.isStale(generatedAt: iso(now.addingTimeInterval(-(threshold + 1))), now: now))
        XCTAssertTrue(WidgetSnapshot.isStale(generatedAt: "not-a-timestamp", now: now))
    }

    func testDefaultAgentPicksFreshestActiveQuotaAndSkipsAgentsWithoutData() {
        let now = Date(timeIntervalSince1970: 1_763_000_000)
        let windowHours = 5.0
        let claudeReset = now.addingTimeInterval(3 * 3600)
        let codexReset = now.addingTimeInterval(1 * 3600)
        let claudeStart = claudeReset.addingTimeInterval(-windowHours * 3600)
        let codexStart = codexReset.addingTimeInterval(-windowHours * 3600)
        XCTAssertGreaterThan(claudeReset, now)
        XCTAssertGreaterThan(codexReset, now)
        XCTAssertGreaterThan(claudeStart, codexStart)

        let claude = fiveHourWindow(reset: claudeReset, percent: 20, source: "tokei")
        let codex = fiveHourWindow(reset: codexReset, percent: 80, source: "live")
        let grok = QuotaWindow(
            weeklyResetsAt: iso(now.addingTimeInterval(86400)),
            weeklyUsedPercent: nil,
            source: "manual"
        )
        XCTAssertFalse(WidgetSnapshot.hasQuotaData(grok))
        XCTAssertTrue(WidgetSnapshot.hasQuotaData(claude))

        let windows = ["codex": codex, "claude": claude, "grok": grok]
        XCTAssertEqual(WidgetSnapshot.quotaAgents(in: windows, now: now), ["claude", "codex"])
        XCTAssertEqual(WidgetSnapshot.defaultQuotaAgent(in: windows, now: now), "claude")
    }

    func testDefaultAgentBreaksTiesBySourceThenPrefersClaude() {
        let now = Date(timeIntervalSince1970: 1_763_000_000)
        let reset = now.addingTimeInterval(2 * 3600)
        let live = fiveHourWindow(reset: reset, percent: 10, source: "live")
        let tokei = fiveHourWindow(reset: reset, percent: 90, source: "tokei")
        XCTAssertEqual(
            WidgetSnapshot.quotaAgents(in: ["claude": tokei, "codex": live], now: now).first,
            "codex"
        )
        XCTAssertEqual(
            WidgetSnapshot.defaultQuotaAgent(in: ["codex": live, "claude": live], now: now),
            "claude"
        )
    }

    func testDefaultAgentPrefersAnActiveWindowOverANewerExpiredOne() {
        let now = Date(timeIntervalSince1970: 1_763_000_000)
        let activeReset = now.addingTimeInterval(6 * 86400)
        let expiredReset = now.addingTimeInterval(-60)
        let activeStart = activeReset.addingTimeInterval(-168 * 3600)
        let expiredStart = expiredReset.addingTimeInterval(-5 * 3600)
        XCTAssertGreaterThan(activeReset, now)
        XCTAssertLessThan(expiredReset, now)
        XCTAssertGreaterThan(expiredStart, activeStart)

        let claude = QuotaWindow(
            weeklyResetsAt: iso(activeReset),
            weeklyWindowHours: 168,
            weeklyUsedPercent: 30,
            source: "tokei"
        )
        let copilot = QuotaWindow(
            weeklyResetsAt: iso(now.addingTimeInterval(86400)),
            weeklyUsedPercent: nil,
            fiveHourResetsAt: iso(expiredReset),
            fiveHourWindowHours: 5,
            fiveHourUsedPercent: 99,
            source: "live"
        )
        XCTAssertEqual(
            WidgetSnapshot.defaultQuotaAgent(in: ["copilot": copilot, "claude": claude], now: now),
            "claude"
        )
    }

    func testExtraQuotaCountsAndAResetTimeAloneDoesNot() {
        let now = Date(timeIntervalSince1970: 1_763_000_000)
        let extra = QuotaWindow(
            weeklyResetsAt: iso(now.addingTimeInterval(86400)),
            weeklyUsedPercent: nil,
            source: "live",
            extraWindows: [
                ExtraQuotaWindow(
                    id: "sonnet",
                    title: "Sonnet",
                    usedPercent: 12,
                    resetsAt: iso(now.addingTimeInterval(3600)),
                    windowHours: 5
                ),
            ]
        )
        let bare = QuotaWindow(weeklyResetsAt: iso(now.addingTimeInterval(86400)), source: "manual")
        XCTAssertEqual(WidgetSnapshot.quotaAgents(in: ["grok": bare, "claude": extra], now: now), ["claude"])
    }

    func testPassedResetDropsTheOldPercentAndUpcomingResetsSkipThePast() {
        let now = Date(timeIntervalSince1970: 1_763_000_000)
        let past = now.addingTimeInterval(-60)
        let future = now.addingTimeInterval(3600)
        let recordedPercent = 62.0
        let window = QuotaWindow(
            weeklyResetsAt: iso(future),
            weeklyWindowHours: 168,
            weeklyUsedPercent: 40,
            fiveHourResetsAt: iso(past),
            fiveHourWindowHours: 5,
            fiveHourUsedPercent: recordedPercent,
            source: "live"
        )
        let snapshot = WidgetSnapshot(
            generatedAt: iso(now),
            timezone: "UTC",
            days: [],
            quotaWindows: ["claude": window]
        )

        let before = snapshot.fiveHourQuotaBar(for: "claude", now: past.addingTimeInterval(-1))
        XCTAssertEqual(before?.isReset, false)
        XCTAssertEqual(before?.usedPercent, min(max(recordedPercent, 0), 100))
        let atReset = snapshot.fiveHourQuotaBar(for: "claude", now: past)
        XCTAssertEqual(atReset?.isReset, true)
        XCTAssertNil(atReset?.usedPercent)

        let weekly = snapshot.weeklyQuotaBar(for: "claude", now: now)
        XCTAssertEqual(weekly?.isReset, false)
        XCTAssertEqual(weekly?.usedPercent, 40)

        let fiveHourOnly = fiveHourWindow(reset: future, percent: 10, source: "live")
        let codex = WidgetSnapshot(
            generatedAt: iso(now),
            days: [],
            quotaWindows: ["codex": fiveHourOnly]
        )
        XCTAssertNil(codex.weeklyQuotaBar(for: "codex", now: now))
        XCTAssertEqual(codex.fiveHourQuotaBar(for: "codex", now: now)?.usedPercent, 10)
        XCTAssertNil(snapshot.fiveHourQuotaBar(for: "missing", now: now))

        let upcoming = snapshot.upcomingResetDates(after: now)
        let parsedFuture = ReportDates.parseTimestamp(iso(future))!
        XCTAssertEqual(upcoming.count, 1)
        XCTAssertEqual(upcoming[0].timeIntervalSince(parsedFuture), 0, accuracy: 0.001)
        XCTAssertTrue(snapshot.upcomingResetDates(after: future).isEmpty)
    }

    func testWidgetSnapshotBuilderAndEncodeDecodeRoundTrip() throws {
        let timeZone = TimeZone(identifier: "Asia/Shanghai")!
        let calendar = RangeEngine.calendar(timezone: timeZone)
        let now = calendar.date(from: DateComponents(year: 2026, month: 11, day: 27, hour: 15, minute: 4, second: 0))!
        let todayCosts = [1.25, 2.5]
        let yesterdayCost = 0.75
        let today = key(0, from: now, calendar: calendar)
        let yesterday = key(-1, from: now, calendar: calendar)
        let projects = [
            project(id: "a", days: [day(today, todayCosts[0]), day(yesterday, yesterdayCost)]),
            project(id: "b", days: [day(today, todayCosts[1])]),
        ]
        let generatedAt = iso(now)
        let fiveReset = now.addingTimeInterval(90 * 60)
        let weekReset = now.addingTimeInterval(3 * 86400)
        let quota = QuotaWindow(
            weeklyResetsAt: iso(weekReset),
            weeklyWindowHours: 168,
            weeklyUsedPercent: 41,
            fiveHourResetsAt: iso(fiveReset),
            fiveHourWindowHours: 5,
            fiveHourUsedPercent: 62,
            source: "live"
        )
        let report = try decodeReport(
            projects: projects,
            generatedAt: generatedAt,
            timezone: timeZone.identifier,
            quota: ["claude": quota]
        )
        let parsedNow = try XCTUnwrap(ReportDates.parseTimestamp(report.generatedAt))
        let snapshot = WidgetSnapshot(report: report, deviceName: "Studio")
        let expectedDays = WidgetSnapshot.dailyCosts(
            from: report,
            now: parsedNow,
            dayCount: WidgetSnapshot.defaultDayCount
        )

        XCTAssertEqual(snapshot.generatedAt, generatedAt)
        XCTAssertEqual(snapshot.deviceName, "Studio")
        XCTAssertEqual(snapshot.timezone, timeZone.identifier)
        XCTAssertEqual(snapshot.currency, report.currency)
        XCTAssertEqual(snapshot.days, expectedDays.days)
        XCTAssertEqual(snapshot.quotaWindows, report.quotaWindows)
        XCTAssertEqual(try XCTUnwrap(snapshot.todayCost(now: parsedNow)), todayCosts.reduce(0, +), accuracy: 1e-9)
        XCTAssertEqual(snapshot.yesterdayCost(now: parsedNow), yesterdayCost, accuracy: 1e-9)
        XCTAssertFalse(snapshot.days.contains { projects.map(\.name).contains($0.day) })

        let data = try JSONEncoder().encode(snapshot)
        let decoded = try JSONDecoder().decode(WidgetSnapshot.self, from: data)
        XCTAssertEqual(decoded, snapshot)
        let text = String(decoding: data, as: UTF8.self)
        XCTAssertTrue(text.contains("\"generated_at\""))
        XCTAssertTrue(text.contains("\"device_name\""))
        XCTAssertTrue(text.contains("\"quota_windows\""))
        XCTAssertTrue(text.contains("\"by_agent\"") || snapshot.days.allSatisfy { $0.byAgent == nil })
        for name in projects.map(\.name) {
            XCTAssertFalse(text.contains(name))
        }
    }
}
