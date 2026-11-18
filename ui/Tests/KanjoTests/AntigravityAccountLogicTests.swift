import XCTest
@testable import KanjoCore

final class AntigravityAccountLogicTests: KanjoTestCase {
    func testButtonStates() {
        let currentAccount = AntigravityAccount(
            email: "alex@example.com",
            tokens: 100,
            costUsd: 1.0,
            messages: 5,
            savedLogin: true
        )
        let savedAccount = AntigravityAccount(
            email: "bob@example.com",
            tokens: 50,
            costUsd: 0.5,
            messages: 2,
            savedLogin: true
        )
        let unsavedAccount = AntigravityAccount(
            email: "carol@example.com",
            tokens: 0,
            costUsd: 0.0,
            messages: 0,
            savedLogin: false
        )

        XCTAssertEqual(
            AntigravityAccountLogic.buttonState(for: currentAccount, currentEmail: "alex@example.com"),
            .current
        )
        XCTAssertEqual(
            AntigravityAccountLogic.buttonState(for: currentAccount, currentEmail: "ALEX@EXAMPLE.COM"),
            .current
        )
        XCTAssertEqual(
            AntigravityAccountLogic.buttonState(for: savedAccount, currentEmail: "alex@example.com"),
            .canSwitch
        )
        XCTAssertEqual(
            AntigravityAccountLogic.buttonState(for: unsavedAccount, currentEmail: "alex@example.com"),
            .needSignInOnce
        )
        XCTAssertEqual(
            AntigravityAccountLogic.buttonState(for: unsavedAccount, currentEmail: nil),
            .needSignInOnce
        )
    }

    func testLocalPartOfEmail() {
        XCTAssertEqual(AntigravityAccountLogic.localPart(of: "alex@example.com"), "alex")
        XCTAssertEqual(AntigravityAccountLogic.localPart(of: "first.last@company.co.uk"), "first.last")
        XCTAssertEqual(AntigravityAccountLogic.localPart(of: "plain_user"), "plain_user")
    }

    func testDisplayNameDisambiguatesSharedLocalPart() {
        let alex1 = AntigravityAccount(email: "alex@example.com", tokens: 1, costUsd: 0, messages: 1)
        let alex2 = AntigravityAccount(email: "alex@work.com", tokens: 2, costUsd: 0, messages: 1)
        let bob = AntigravityAccount(email: "bob@example.com", tokens: 3, costUsd: 0, messages: 1)
        let accounts = [alex1, alex2, bob]

        // Distinct local parts -> show the local part.
        XCTAssertEqual(AntigravityAccountLogic.displayName(for: bob, among: accounts), "bob")
        // Two accounts share "alex" -> show the full email for both.
        XCTAssertEqual(AntigravityAccountLogic.displayName(for: alex1, among: accounts), "alex@example.com")
        XCTAssertEqual(AntigravityAccountLogic.displayName(for: alex2, among: accounts), "alex@work.com")

        // On its own, alex shows just the local part.
        XCTAssertEqual(AntigravityAccountLogic.displayName(for: alex1, among: [alex1]), "alex")
    }

    func testSectionTitlesLocalization() {
        let dateStr = "11/6/26, 10:00 AM"

        // English
        XCTAssertEqual(
            AntigravityAccountLogic.sectionTitle(windowKind: "quota_week", windowStartFormatted: dateStr, language: "en"),
            "Antigravity accounts · this quota week (since \(dateStr))"
        )
        XCTAssertEqual(
            AntigravityAccountLogic.sectionTitle(windowKind: "billing_cycle", windowStartFormatted: dateStr, language: "en"),
            "Antigravity accounts · this billing cycle (since \(dateStr))"
        )
        XCTAssertEqual(
            AntigravityAccountLogic.sectionTitle(windowKind: "last_7_days", windowStartFormatted: dateStr, language: "en"),
            "Antigravity accounts · last 7 days (since \(dateStr))"
        )

        // Simplified Chinese
        XCTAssertEqual(
            AntigravityAccountLogic.sectionTitle(windowKind: "quota_week", windowStartFormatted: dateStr, language: "zh-Hans"),
            "Antigravity 账号 · 本额度周（\(dateStr) 起）"
        )
        XCTAssertEqual(
            AntigravityAccountLogic.sectionTitle(windowKind: "billing_cycle", windowStartFormatted: dateStr, language: "zh-Hans"),
            "Antigravity 账号 · 本账期（\(dateStr) 起）"
        )
        XCTAssertEqual(
            AntigravityAccountLogic.sectionTitle(windowKind: "last_7_days", windowStartFormatted: dateStr, language: "zh-Hans"),
            "Antigravity 账号 · 最近 7 天（\(dateStr) 起）"
        )

        // French
        XCTAssertEqual(
            AntigravityAccountLogic.sectionTitle(windowKind: "quota_week", windowStartFormatted: dateStr, language: "fr"),
            "Comptes Antigravity · ce quota hebdomadaire (depuis \(dateStr))"
        )
        XCTAssertEqual(
            AntigravityAccountLogic.sectionTitle(windowKind: "billing_cycle", windowStartFormatted: dateStr, language: "fr"),
            "Comptes Antigravity · ce cycle de facturation (depuis \(dateStr))"
        )
        XCTAssertEqual(
            AntigravityAccountLogic.sectionTitle(windowKind: "last_7_days", windowStartFormatted: dateStr, language: "fr"),
            "Comptes Antigravity · 7 derniers jours (depuis \(dateStr))"
        )
    }

    func testSwitchArgumentsQuitRunning() {
        XCTAssertEqual(
            AgyAccountCommand.switchArguments(email: " a@b.c ", quitRunning: true),
            ["agy-account", "switch", "a@b.c", "--json", "--quit-running"]
        )
    }

    func testAgyAccountCommand() throws {
        XCTAssertEqual(
            AgyAccountCommand.switchArguments(email: "alex@example.com"),
            ["agy-account", "switch", "alex@example.com", "--json"]
        )

        let cmd = try AgyAccountCommand.switchCommand(
            from: "python3 -m kanjo export",
            email: "alex@example.com"
        )
        XCTAssertEqual(cmd, "python3 -m kanjo agy-account switch 'alex@example.com' --json")

        let prefix = "export PATH=\"$HOME/.local/bin:$PATH\"; '/opt/bin/python3' -m kanjo "
        let cmdWithPrefix = try AgyAccountCommand.switchCommand(
            from: prefix + "export",
            email: "bob@example.com"
        )
        XCTAssertEqual(cmdWithPrefix, prefix + "agy-account switch 'bob@example.com' --json")
    }

    func testAccountSharesRangeFilteringNullEmailAndZeroAtBottom() {
        let utc = TimeZone(secondsFromGMT: 0)!
        let cal = RangeEngine.calendar(timezone: utc)
        let now = ReportDates.parseTimestamp("2026-10-23T12:00:00Z")!

        let accounts = [
            AntigravityAccount(email: "alex@example.com", tokens: 0, costUsd: 0, messages: 0, savedLogin: true),
            AntigravityAccount(email: "work@company.com", tokens: 0, costUsd: 0, messages: 0, savedLogin: true),
            AntigravityAccount(email: "backup@gmail.com", tokens: 0, costUsd: 0, messages: 0, savedLogin: false),
        ]
        let byDay = [
            AntigravityAccountDay(day: "2026-09-10", email: "backup@gmail.com", tokens: 100, costUsd: 1.0, messages: 2),
            AntigravityAccountDay(day: "2026-10-18", email: "alex@example.com", tokens: 300, costUsd: 3.0, messages: 6),
            AntigravityAccountDay(day: "2026-10-20", email: "work@company.com", tokens: 150, costUsd: 1.5, messages: 3),
            AntigravityAccountDay(day: "2026-10-21", email: nil, tokens: 50, costUsd: 0.5, messages: 1),
        ]
        let agy = AntigravityAccounts(
            windowStart: "2026-10-16T00:00:00Z",
            windowKind: "quota_week",
            current: "alex@example.com",
            accounts: accounts,
            byDay: byDay
        )

        // All range: all 3 accounts + Unattributed, total = 600, shares sum to 1.0
        let allSpec = RangeSpec(range: .all, calendar: cal)
        let allShares = AntigravityAccountLogic.shares(from: agy, range: allSpec, language: "en")
        XCTAssertEqual(allShares.map(\.displayName), ["alex", "work", "backup", "Unattributed"])
        XCTAssertEqual(allShares.map(\.tokens), [300, 150, 100, 50])
        XCTAssertEqual(allShares.reduce(0.0) { $0 + $1.share }, 1.0, accuracy: 1e-9)
        XCTAssertEqual(allShares[0].share, 0.5, accuracy: 1e-9)
        XCTAssertTrue(allShares.last?.isUnattributed == true)

        // 7d range (2026-10-17 .. 2026-10-23): backup@gmail.com has 0 and sits at bottom
        let days7Spec = RangeEngine.dateInterval(for: .days7, now: now, timezone: utc, quota: nil)
        let days7Shares = AntigravityAccountLogic.shares(from: agy, range: days7Spec, language: "en")
        XCTAssertEqual(days7Shares.map(\.displayName), ["alex", "work", "Unattributed", "backup"])
        XCTAssertEqual(days7Shares.map(\.tokens), [300, 150, 50, 0])
        XCTAssertEqual(days7Shares.last?.share, 0.0)
        XCTAssertEqual(days7Shares.reduce(0.0) { $0 + $1.share }, 1.0, accuracy: 1e-9)

        // Per-agent range rule: sinceReset without antigravity quota window -> empty
        let claudeOnlyQuota = ["claude": QuotaWindow(weeklyResetsAt: "2026-10-28T00:00:00Z")]
        let resetSpecNoAgy = RangeEngine.dateInterval(for: .sinceReset, now: now, timezone: utc, quota: claudeOnlyQuota)
        XCTAssertTrue(AntigravityAccountLogic.shares(from: agy, range: resetSpecNoAgy, language: "en").isEmpty)

        // sinceReset WITH antigravity quota window starting 2026-10-19T00:00:00Z -> only work + Unattributed active
        let agyQuota = ["antigravity": QuotaWindow(weeklyResetsAt: "2026-10-26T00:00:00Z", weeklyWindowHours: 168)]
        let resetSpecAgy = RangeEngine.dateInterval(for: .sinceReset, now: now, timezone: utc, quota: agyQuota)
        let resetShares = AntigravityAccountLogic.shares(from: agy, range: resetSpecAgy, language: "en")
        XCTAssertEqual(resetShares.map(\.displayName), ["work", "Unattributed", "alex", "backup"])
        XCTAssertEqual(resetShares.map(\.tokens), [150, 50, 0, 0])
        XCTAssertEqual(resetShares.reduce(0.0) { $0 + $1.share }, 1.0, accuracy: 1e-9)
    }

    func testAccountSharesEmptyCases() {
        let utc = TimeZone(secondsFromGMT: 0)!
        let cal = RangeEngine.calendar(timezone: utc)
        let allSpec = RangeSpec(range: .all, calendar: cal)

        XCTAssertTrue(AntigravityAccountLogic.shares(from: nil, range: allSpec).isEmpty)

        let noByDay = AntigravityAccounts(windowStart: "2026-10-16T00:00:00Z", windowKind: "quota_week", byDay: nil)
        XCTAssertTrue(AntigravityAccountLogic.shares(from: noByDay, range: allSpec).isEmpty)

        let emptyByDay = AntigravityAccounts(windowStart: "2026-10-16T00:00:00Z", windowKind: "quota_week", byDay: [])
        XCTAssertTrue(AntigravityAccountLogic.shares(from: emptyByDay, range: allSpec).isEmpty)

        let futureNow = ReportDates.parseTimestamp("2030-01-01T12:00:00Z")!
        let futureToday = RangeEngine.dateInterval(for: .today, now: futureNow, timezone: utc, quota: nil)
        let withData = AntigravityAccounts(
            windowStart: "2026-10-16T00:00:00Z",
            windowKind: "quota_week",
            byDay: [AntigravityAccountDay(day: "2026-10-18", email: "alex@example.com", tokens: 100, costUsd: 1.0)]
        )
        XCTAssertTrue(AntigravityAccountLogic.shares(from: withData, range: futureToday).isEmpty)
    }

    func testCompactQuotaTextOrderingAndLocalization() {
        let utc = TimeZone(secondsFromGMT: 0)!
        let quota = AntigravityAccountQuota(
            capturedAt: "2026-11-17T21:30:00Z",
            windows: [
                ExtraQuotaWindow(id: "weekly", title: "Weekly", usedPercent: 4.0, windowHours: 168),
                ExtraQuotaWindow(id: "five_hour", title: "5-hour", usedPercent: 10.0, windowHours: 5),
                ExtraQuotaWindow(id: "3p-weekly", title: "Claude/GPT · Weekly", usedPercent: nil, windowHours: 168),
            ]
        )
        let en = AntigravityAccountLogic.compactQuotaText(quota, timezone: utc, language: "en")
        XCTAssertEqual(en, "5-hour 10% · Weekly 4% · Claude/GPT · Weekly — · as of 11/17, 21:30")

        let zh = AntigravityAccountLogic.compactQuotaText(quota, timezone: utc, language: "zh-Hans")
        XCTAssertEqual(zh, "5 小时 10% · 每周 4% · Claude/GPT · 每周 — · 截至 11/17 21:30")

        let fr = AntigravityAccountLogic.compactQuotaText(quota, timezone: utc, language: "fr")
        XCTAssertEqual(fr, "5 heures 10% · Hebdomadaire 4% · Claude/GPT · Hebdomadaire — · au 17/11 21:30")

        let emptyQuota = AntigravityAccountQuota(capturedAt: "2026-11-17T21:30:00Z", windows: [])
        XCTAssertNil(AntigravityAccountLogic.compactQuotaText(emptyQuota, timezone: utc, language: "en"))
    }
}
