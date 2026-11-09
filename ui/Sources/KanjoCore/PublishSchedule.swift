import Foundation

/// Pure scheduling and decision logic for publishing usage summaries (spec Part B3 & B4).
public enum PublishSchedule {
    /// Minimum time in seconds to wait before retrying after a failed publish attempt.
    public static let failureRetryBackoff: TimeInterval = 3600

    /// Minimum time in seconds for daily frequency.
    public static let dailyInterval: TimeInterval = 86400

    /// Minimum time in seconds for weekly frequency (7 days).
    public static let weeklyInterval: TimeInterval = 7 * 86400

    /// Check whether a scheduled publish should run.
    ///
    /// - Parameters:
    ///   - enabled: Whether publishing is enabled in settings.
    ///   - repoPath: Path to the target git repository.
    ///   - frequency: The configured publish frequency (daily, weekly, monthly).
    ///   - lastSuccessAt: Timestamp of the last successful publish, if any.
    ///   - lastAttemptAt: Timestamp of the last publish attempt, if any.
    ///   - now: Current time (defaults to Date()).
    ///   - timeZone: The timezone for calendar calculations (e.g. from the usage report, defaults to .current).
    /// - Returns: True if a publish should be performed.
    public static func shouldPublish(
        enabled: Bool,
        repoPath: String,
        frequency: PublishFrequency,
        lastSuccessAt: Date?,
        lastAttemptAt: Date?,
        now: Date = Date(),
        timeZone: TimeZone = .current
    ) -> Bool {
        guard enabled else { return false }
        guard !repoPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }

        // Backoff: if last attempt was a failure (after last success, or no success yet),
        // wait at least failureRetryBackoff (1 hour) before retrying.
        if let attempt = lastAttemptAt {
            let wasFailure = lastSuccessAt == nil || attempt > lastSuccessAt!
            if wasFailure && now.timeIntervalSince(attempt) < failureRetryBackoff {
                return false
            }
        }

        // If never succeeded yet and backoff passed, publish immediately
        guard let success = lastSuccessAt else {
            return true
        }

        // Guard against clock skews backwards
        guard now >= success else { return false }

        switch frequency {
        case .daily:
            return now.timeIntervalSince(success) >= dailyInterval
        case .weekly:
            return now.timeIntervalSince(success) >= weeklyInterval
        case .monthly:
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = timeZone
            let successComponents = calendar.dateComponents([.year, .month], from: success)
            let nowComponents = calendar.dateComponents([.year, .month], from: now)
            guard let sy = successComponents.year, let sm = successComponents.month,
                  let ny = nowComponents.year, let nm = nowComponents.month else {
                return false
            }
            return ny > sy || (ny == sy && nm > sm)
        }
    }
}

/// Helper to build the `publish-usage` CLI command line string.
public enum PublishCommand {
    public static func command(from cliCommand: String, repo: String, file: String, branch: String) -> String {
        var parts = [DiskCommand.replacingExport(in: cliCommand, with: "publish-usage").trimmingCharacters(in: .whitespaces)]
        parts.append("--repo")
        parts.append(DiskCommand.shellWord(repo))
        let cleanFile = file.trimmingCharacters(in: .whitespaces)
        if !cleanFile.isEmpty {
            parts.append("--file")
            parts.append(DiskCommand.shellWord(cleanFile))
        }
        let cleanBranch = branch.trimmingCharacters(in: .whitespaces)
        if !cleanBranch.isEmpty {
            parts.append("--branch")
            parts.append(DiskCommand.shellWord(cleanBranch))
        }
        return parts.joined(separator: " ")
    }
}
