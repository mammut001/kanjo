import Foundation

/// One-time migration for legacy family report settings.
///
/// In earlier versions of Kanjo, `familyReportURL` had a built-in default of
/// `https://usage.paytonpei.top`. If an existing user previously enabled family
/// reporting without explicitly overriding the default URL (meaning the key
/// was never written to defaults), we migrate their setting once so their existing
/// family setup continues uninterrupted.
public enum FamilyReportMigration {
    public static let legacyDefaultURL = "https://usage.paytonpei.top"

    @discardableResult
    public static func migrate(defaults: UserDefaults = AppDefaults.store) -> Bool {
        if defaults.bool(forKey: SettingsKeys.familyReportMigrationDone) {
            return false
        }
        defer {
            defaults.set(true, forKey: SettingsKeys.familyReportMigrationDone)
        }

        let isEnabled = defaults.bool(forKey: SettingsKeys.familyReportEnabled)
        let hasStoredURL = defaults.object(forKey: SettingsKeys.familyReportURL) != nil

        if isEnabled && !hasStoredURL {
            defaults.set(legacyDefaultURL, forKey: SettingsKeys.familyReportURL)
            return true
        }
        return false
    }
}
