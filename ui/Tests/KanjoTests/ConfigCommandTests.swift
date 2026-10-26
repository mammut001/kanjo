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
}
