import Foundation

public enum FamilyReportStatusState: Equatable {
    case noNetwork
    case noServer
    case inProgress
    case missingToken
    case failed(String)
    case lastReported(Date)
    case never
}

public enum FamilyReportStatus {
    public static func state(
        url: String,
        hasToken: Bool,
        isReporting: Bool,
        lastError: String?,
        lastSuccessAt: Date?,
        noNetwork: Bool
    ) -> FamilyReportStatusState {
        if noNetwork {
            return .noNetwork
        }
        let trimmed = url.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty || !FamilyReportSchedule.isValidURL(trimmed) {
            return .noServer
        }
        if isReporting {
            return .inProgress
        }
        if !hasToken {
            return .missingToken
        }
        if let err = lastError {
            return .failed(err)
        }
        if let success = lastSuccessAt {
            return .lastReported(success)
        }
        return .never
    }

    public static func text(
        url: String,
        hasToken: Bool,
        isReporting: Bool,
        lastError: String?,
        lastSuccessAt: Date?,
        noNetwork: Bool,
        relativeTo now: Date = Date()
    ) -> String {
        switch state(
            url: url,
            hasToken: hasToken,
            isReporting: isReporting,
            lastError: lastError,
            lastSuccessAt: lastSuccessAt,
            noNetwork: noNetwork
        ) {
        case .noNetwork:
            return L10n.tr("settings.family.status.no_network")
        case .noServer:
            return L10n.tr("settings.family.status.no_server")
        case .inProgress:
            return L10n.tr("settings.family.status.in_progress")
        case .missingToken:
            return L10n.tr("settings.family.status.missing_token")
        case .failed(let err):
            return L10n.tr("settings.family.status.failed", err)
        case .lastReported(let date):
            let formatter = RelativeDateTimeFormatter()
            formatter.unitsStyle = .full
            let relative = formatter.localizedString(for: date, relativeTo: now)
            return L10n.tr("settings.family.status.last_reported", relative)
        case .never:
            return L10n.tr("settings.family.status.never")
        }
    }
}
