import Foundation

public enum AntigravityAccountButtonState: Equatable, Sendable {
    case current
    case canSwitch
    case needSignInOnce
}

public enum AntigravityAccountLogic {
    public static func buttonState(for account: AntigravityAccount, currentEmail: String?) -> AntigravityAccountButtonState {
        if let current = currentEmail, account.email.lowercased() == current.lowercased() {
            return .current
        }
        if account.savedLogin {
            return .canSwitch
        }
        return .needSignInOnce
    }

    public static func localPart(of email: String) -> String {
        let parts = email.split(separator: "@", maxSplits: 1)
        return parts.first.map(String.init) ?? email
    }

    public static func sectionTitle(windowKind: String, windowStartFormatted: String, language: String? = nil) -> String {
        switch windowKind {
        case "quota_week":
            return L10n.tr("overview.agy.title_quota_week", language: language, windowStartFormatted)
        case "billing_cycle":
            return L10n.tr("overview.agy.title_billing_cycle", language: language, windowStartFormatted)
        default:
            return L10n.tr("overview.agy.title_last_7_days", language: language, windowStartFormatted)
        }
    }
}
