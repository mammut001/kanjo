import Foundation

/// 续费日只交给 CLI 写配置。nil 表示移除覆盖，让下一次 export 重新检测。
public enum ConfigCommand {
    public static func arguments(agent: String, anchorDay: Int?) throws -> [String] {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        guard !agent.isEmpty, agent.unicodeScalars.allSatisfy({ allowed.contains($0) }) else {
            throw DataSourceError.launchFailed("Invalid subscription agent: \(agent)")
        }
        let key = "subscriptions.\(agent).anchor_day"
        guard let day = anchorDay else { return ["config", "unset", key] }
        guard (1...28).contains(day) else {
            throw DataSourceError.launchFailed("Renewal day must be between 1 and 28.")
        }
        return ["config", "set", key, String(day)]
    }

    public static func fieldArguments(agent: String, field: String, value: String?) throws -> [String] {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        guard !agent.isEmpty, agent.unicodeScalars.allSatisfy({ allowed.contains($0) }) else {
            throw DataSourceError.launchFailed("Invalid subscription agent: \(agent)")
        }
        guard ["anchor_day", "plan", "monthly_price_usd"].contains(field) else {
            throw DataSourceError.launchFailed("Invalid subscription field: \(field)")
        }
        let key = "subscriptions.\(agent).\(field)"
        guard let val = value, !val.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return ["config", "unset", key]
        }
        return ["config", "set", key, val.trimmingCharacters(in: .whitespacesAndNewlines)]
    }

    public static func quotaResetArguments(agent: String, weeklyReset: String?) throws -> [String] {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        guard !agent.isEmpty, agent.unicodeScalars.allSatisfy({ allowed.contains($0) }) else {
            throw DataSourceError.launchFailed("Invalid agent: \(agent)")
        }
        let key = "quota_windows.\(agent).weekly_reset"
        guard let val = weeklyReset, !val.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return ["config", "unset", key]
        }
        return ["config", "set", key, val.trimmingCharacters(in: .whitespacesAndNewlines)]
    }

    /// 和 DiskCommand 一样只替换最后一个 export，保留 PATH 等 shell 前缀。
    public static func command(from cliCommand: String, arguments: [String]) throws -> String {
        let trimmed = cliCommand.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let token = DiskCommand.lastExportToken(in: trimmed),
              token.upperBound == trimmed.endIndex, token.lowerBound > trimmed.startIndex,
              trimmed[trimmed.index(before: token.lowerBound)].isWhitespace else {
            throw DataSourceError.launchFailed("Editing subscriptions needs a CLI command ending in export.")
        }
        return DiskCommand.replacingExport(in: trimmed, with: arguments.map(DiskCommand.shellWord).joined(separator: " "))
    }

    public static func command(from cliCommand: String, agent: String, anchorDay: Int?) throws -> String {
        let args = try arguments(agent: agent, anchorDay: anchorDay)
        return try command(from: cliCommand, arguments: args)
    }
}

public struct ConfigDataSource {
    public let cliCommand: String
    public let workingDirectory: URL?
    public let timeout: TimeInterval

    public init(cliCommand: String, workingDirectory: URL? = nil, timeout: TimeInterval = 300) {
        self.cliCommand = cliCommand
        self.workingDirectory = workingDirectory
        self.timeout = timeout
    }

    private func execute(args: [String]) async throws {
        let command = try ConfigCommand.command(from: cliCommand, arguments: args)
        let cwd = workingDirectory
        let timeout = self.timeout
        let (status, _, err, timedOut) = try await Task.detached(priority: .utility) {
            try CLIDataSource.run(command: command, cwd: cwd, timeout: timeout)
        }.value
        if timedOut { throw DataSourceError.commandTimedOut(command: command, seconds: Int(timeout)) }
        guard status == 0 else {
            throw DataSourceError.commandFailed(command: command, status: status,
                                                stderr: String(decoding: err, as: UTF8.self))
        }
    }

    public func setAnchorDay(agent: String, day: Int?) async throws {
        let args = try ConfigCommand.arguments(agent: agent, anchorDay: day)
        try await execute(args: args)
    }

    public func setSubscription(agent: String, plan: String?, monthlyPriceUsd: Double?, anchorDay: Int?) async throws {
        if let price = monthlyPriceUsd {
            let priceStr = price.truncatingRemainder(dividingBy: 1) == 0 ? String(format: "%.0f", price) : String(price)
            let args = try ConfigCommand.fieldArguments(agent: agent, field: "monthly_price_usd", value: priceStr)
            try await execute(args: args)
        }
        if let plan = plan, !plan.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let args = try ConfigCommand.fieldArguments(agent: agent, field: "plan", value: plan)
            try await execute(args: args)
        }
        if let day = anchorDay {
            let args = try ConfigCommand.arguments(agent: agent, anchorDay: day)
            try await execute(args: args)
        }
    }

    public func removeSubscription(agent: String) async throws {
        try await execute(args: try ConfigCommand.fieldArguments(agent: agent, field: "plan", value: nil))
        try await execute(args: try ConfigCommand.fieldArguments(agent: agent, field: "monthly_price_usd", value: nil))
        try await execute(args: try ConfigCommand.arguments(agent: agent, anchorDay: nil))
    }

    public func setWeeklyReset(agent: String, reset: String?) async throws {
        let args = try ConfigCommand.quotaResetArguments(agent: agent, weeklyReset: reset)
        try await execute(args: args)
    }
}
