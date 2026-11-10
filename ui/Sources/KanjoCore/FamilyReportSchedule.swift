import Foundation

/// Pure scheduling and decision logic for family usage reporting (spec batch 2).
public enum FamilyReportSchedule {
    /// Minimum time in seconds (15 minutes) between successful reports.
    public static let successInterval: TimeInterval = 15 * 60

    /// Minimum time in seconds (30 minutes) to wait before retrying after a failed report attempt.
    public static let failureRetryBackoff: TimeInterval = 30 * 60

    /// Validates server URL (HTTPS required, except for local test URLs http://127.0.0.1 or http://localhost).
    public static func isValidURL(_ urlString: String) -> Bool {
        let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed),
              let scheme = url.scheme?.lowercased(),
              let host = url.host?.lowercased() else {
            return false
        }
        if scheme == "https" {
            return !host.isEmpty
        }
        if scheme == "http" && (host == "127.0.0.1" || host == "localhost") {
            return true
        }
        return false
    }

    /// Check whether a scheduled family report should run.
    ///
    /// - Parameters:
    ///   - enabled: Whether family reporting is enabled in settings.
    ///   - hasToken: Whether the report token exists in Keychain.
    ///   - url: Target family server URL.
    ///   - lastSuccessAt: Timestamp of the last successful report, if any.
    ///   - lastAttemptAt: Timestamp of the last report attempt, if any.
    ///   - now: Current time (defaults to Date()).
    ///   - noNetwork: Whether network operations are currently suppressed.
    /// - Returns: True if a report should be performed.
    public static func shouldReport(
        enabled: Bool,
        hasToken: Bool,
        url: String,
        lastSuccessAt: Date?,
        lastAttemptAt: Date?,
        now: Date = Date(),
        noNetwork: Bool = false
    ) -> Bool {
        guard enabled else { return false }
        guard hasToken else { return false }
        guard isValidURL(url) else { return false }
        guard !noNetwork else { return false }

        // Backoff: if last attempt was a failure (after last success, or no success yet),
        // wait at least failureRetryBackoff (30 minutes) before retrying.
        if let attempt = lastAttemptAt {
            let wasFailure = lastSuccessAt == nil || attempt > lastSuccessAt!
            if wasFailure && now.timeIntervalSince(attempt) < failureRetryBackoff {
                return false
            }
        }

        // If never succeeded yet and backoff passed, report immediately
        guard let success = lastSuccessAt else {
            return true
        }

        // Guard against clock skews backwards
        guard now >= success else { return false }

        return now.timeIntervalSince(success) >= successInterval
    }
}

/// Helper to build the `report-family` CLI command line string.
/// Note: The token is NEVER placed in the command arguments.
public enum FamilyReportCommand {
    public static func command(from cliCommand: String, url: String, memberLabel: String?) -> String {
        var parts = [DiskCommand.replacingExport(in: cliCommand, with: "report-family").trimmingCharacters(in: .whitespaces)]
        parts.append("--url")
        parts.append(DiskCommand.shellWord(url.trimmingCharacters(in: .whitespacesAndNewlines)))
        if let label = memberLabel?.trimmingCharacters(in: .whitespacesAndNewlines), !label.isEmpty {
            parts.append("--member-label")
            parts.append(DiskCommand.shellWord(label))
        }
        return parts.joined(separator: " ")
    }
}
