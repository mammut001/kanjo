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
}
