#if os(macOS)

import Foundation

public enum AgyAccountCommand {
    public static func switchArguments(email: String) -> [String] {
        let clean = email.trimmingCharacters(in: .whitespacesAndNewlines)
        return ["agy-account", "switch", clean, "--json"]
    }

    public static func switchCommand(from cliCommand: String, email: String) throws -> String {
        try ConfigCommand.command(from: cliCommand, arguments: switchArguments(email: email))
    }
}

#endif
