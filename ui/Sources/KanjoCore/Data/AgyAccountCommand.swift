#if os(macOS)

import Foundation

public enum AgyAccountCommand {
    public static func switchArguments(email: String, quitRunning: Bool = false) -> [String] {
        let clean = email.trimmingCharacters(in: .whitespacesAndNewlines)
        var args = ["agy-account", "switch", clean, "--json"]
        if quitRunning { args.append("--quit-running") }
        return args
    }

    public static func switchCommand(from cliCommand: String, email: String, quitRunning: Bool = false) throws -> String {
        try ConfigCommand.command(from: cliCommand, arguments: switchArguments(email: email, quitRunning: quitRunning))
    }
}

#endif
