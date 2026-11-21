import XCTest
@testable import KanjoCore

final class ConfigCommandTests: KanjoTestCase {
    func testArguments() throws {
        XCTAssertEqual(try ConfigCommand.arguments(agent: "codex", anchorDay: 8),
                       ["config", "set", "subscriptions.codex.anchor_day", "8"])
        XCTAssertEqual(try ConfigCommand.arguments(agent: "claude", anchorDay: nil),
                       ["config", "unset", "subscriptions.claude.anchor_day"])
        for day in [1, 28] {
            XCTAssertEqual(try ConfigCommand.arguments(agent: "claude", anchorDay: day).last, String(day))
        }
        for day in [0, 29] {
            XCTAssertThrowsError(try ConfigCommand.arguments(agent: "codex", anchorDay: day))
        }
        for agent in ["", "codex; touch /tmp/x", "codex.plan"] {
            XCTAssertThrowsError(try ConfigCommand.arguments(agent: agent, anchorDay: 8))
        }
    }

    func testDerivationPreservesLaunchCommandAndPATH() throws {
        XCTAssertEqual(try ConfigCommand.command(from: CLIDataSource.defaultCommand, agent: "codex", anchorDay: 8),
                       "python3 -m kanjo config set subscriptions.codex.anchor_day 8")
        XCTAssertEqual(try ConfigCommand.command(from: CLIDataSource.defaultCommand, agent: "claude", anchorDay: nil),
                       "python3 -m kanjo config unset subscriptions.claude.anchor_day")
        let prefix = "export PATH=\"$HOME/.local/bin:$PATH\"; '/opt/export tools/bin/python3' -m kanjo "
        XCTAssertEqual(try ConfigCommand.command(from: prefix + "export", agent: "codex", anchorDay: 8),
                       prefix + "config set subscriptions.codex.anchor_day 8")
        XCTAssertEqual(try ConfigCommand.command(from: "  /opt/kanjo export  \n", agent: "claude", anchorDay: nil),
                       "/opt/kanjo config unset subscriptions.claude.anchor_day")
    }

    func testRejectsCommandsWithoutFinalExportSubcommand() {
        for command in ["", "export", "python3 -m kanjo", "export PATH=foo; kanjo", "kanjo re-export", "kanjo export --output report.json"] {
            XCTAssertThrowsError(try ConfigCommand.command(from: command, agent: "codex", anchorDay: 8), command)
        }
    }

    func testFieldArgumentsForArbitraryAgents() throws {
        for agent in ["grok", "copilot", "minimax", "qwen", "commandcode", "opencode", "custom_agent"] {
            XCTAssertEqual(try ConfigCommand.fieldArguments(agent: agent, field: "plan", value: "pro"),
                           ["config", "set", "subscriptions.\(agent).plan", "pro"])
            XCTAssertEqual(try ConfigCommand.fieldArguments(agent: agent, field: "monthly_price_usd", value: "20"),
                           ["config", "set", "subscriptions.\(agent).monthly_price_usd", "20"])
            XCTAssertEqual(try ConfigCommand.fieldArguments(agent: agent, field: "plan", value: nil),
                           ["config", "unset", "subscriptions.\(agent).plan"])
        }
        XCTAssertThrowsError(try ConfigCommand.fieldArguments(agent: "grok", field: "invalid_field", value: "x"))
        XCTAssertThrowsError(try ConfigCommand.fieldArguments(agent: "bad;agent", field: "plan", value: "x"))
    }

    func testQuotaResetArguments() throws {
        XCTAssertEqual(try ConfigCommand.quotaResetArguments(agent: "claude", weeklyReset: "tue 05:00"),
                       ["config", "set", "quota_windows.claude.weekly_reset", "tue 05:00"])
        XCTAssertEqual(try ConfigCommand.quotaResetArguments(agent: "grok", weeklyReset: nil),
                       ["config", "unset", "quota_windows.grok.weekly_reset"])
        XCTAssertEqual(try ConfigCommand.quotaResetArguments(agent: "antigravity", weeklyReset: "  "),
                       ["config", "unset", "quota_windows.antigravity.weekly_reset"])
        for agent in ["grok", "copilot", "minimax", "qwen", "commandcode", "opencode", "custom_agent"] {
            XCTAssertEqual(try ConfigCommand.quotaResetArguments(agent: agent, weeklyReset: "mon 09:00"),
                           ["config", "set", "quota_windows.\(agent).weekly_reset", "mon 09:00"])
        }
        for agent in ["", "bad;agent", "agent with spaces"] {
            XCTAssertThrowsError(try ConfigCommand.quotaResetArguments(agent: agent, weeklyReset: "tue 05:00"))
        }
    }

    func testPlansCommand() throws {
        XCTAssertEqual(ConfigCommand.plansArguments(), ["config", "plans", "--json"])
        XCTAssertEqual(try ConfigCommand.plansCommand(from: CLIDataSource.defaultCommand),
                       "python3 -m kanjo config plans --json")
        let prefix = "export PATH=\"$HOME/.local/bin:$PATH\"; '/opt/tools/bin/python3' -m kanjo "
        XCTAssertEqual(try ConfigCommand.plansCommand(from: prefix + "export"),
                       prefix + "config plans --json")
    }

    func testFamilyScopeArguments() {
        XCTAssertEqual(ConfigCommand.familySinceArguments(since: "2026-11-09"),
                       ["config", "set", "family.since", "2026-11-09"])
        XCTAssertEqual(ConfigCommand.familySinceArguments(since: nil),
                       ["config", "unset", "family.since"])
        XCTAssertEqual(ConfigCommand.familySinceArguments(since: "  "),
                       ["config", "unset", "family.since"])

        XCTAssertEqual(ConfigCommand.familyAgentsArguments(agents: "all"),
                       ["config", "set", "family.agents", "all"])
        XCTAssertEqual(ConfigCommand.familyAgentsArguments(agents: "antigravity"),
                       ["config", "set", "family.agents", "antigravity"])
        XCTAssertEqual(ConfigCommand.familyAgentsArguments(agents: nil),
                       ["config", "unset", "family.agents"])
        XCTAssertEqual(ConfigCommand.familyAgentsArguments(agents: "   "),
                       ["config", "unset", "family.agents"])
    }

    func testAntigravityAccountPlanArguments() throws {
        XCTAssertEqual(
            try ConfigCommand.antigravityAccountPlanArguments(email: "alex@example.com", plan: "google_ai_ultra"),
            ["config", "set", "antigravity_accounts.alex@example.com.plan", "google_ai_ultra"]
        )
        XCTAssertEqual(
            try ConfigCommand.antigravityAccountPlanArguments(email: "alex@example.com", plan: nil),
            ["config", "unset", "antigravity_accounts.alex@example.com.plan"]
        )
        XCTAssertEqual(
            try ConfigCommand.antigravityAccountPlanArguments(email: "alex@example.com", plan: "  "),
            ["config", "unset", "antigravity_accounts.alex@example.com.plan"]
        )
        let cmd = try ConfigCommand.command(
            from: CLIDataSource.defaultCommand,
            arguments: try ConfigCommand.antigravityAccountPlanArguments(email: "alex@example.com", plan: "google_ai_pro")
        )
        XCTAssertEqual(cmd, "python3 -m kanjo config set 'antigravity_accounts.alex@example.com.plan' google_ai_pro")

        let dotted = try ConfigCommand.antigravityAccountPlanArguments(
            email: "first.last+tag@example.com", plan: "google_ai_pro")
        XCTAssertEqual(dotted, ["config", "set", "antigravity_accounts.first.last+tag@example.com.plan", "google_ai_pro"])
        let dottedCmd = try ConfigCommand.command(from: CLIDataSource.defaultCommand, arguments: dotted)
        XCTAssertEqual(dottedCmd, "python3 -m kanjo config set 'antigravity_accounts.first.last+tag@example.com.plan' google_ai_pro")

        for bad in ["", "not-an-email", "bad;email@example.com", "a b@example.com"] {
            XCTAssertThrowsError(try ConfigCommand.antigravityAccountPlanArguments(email: bad, plan: "google_ai_pro"))
        }
    }
}
