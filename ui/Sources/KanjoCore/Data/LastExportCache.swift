import Foundation

/// Reads the CLI's last full export (`export-last.json`) so the app can show
/// recent results immediately at launch while a live refresh runs in the background.
public struct LastExportCache: Sendable {
    public static let fileName = "export-last.json"
    public static let defaultMaxAge: TimeInterval = 7 * 24 * 3600

    static let validationContextKey = CodingUserInfoKey(rawValue: "kanjo.lastExportValidationContext")!

    final class ValidationContext: @unchecked Sendable {
        let now: Date
        let maxAge: TimeInterval

        init(now: Date, maxAge: TimeInterval) {
            self.now = now
            self.maxAge = maxAge
        }
    }

    private struct Envelope: Decodable {
        let scannedAt: Double
        let doc: UsageReport?

        enum CodingKeys: String, CodingKey {
            case scannedAt = "scanned_at"
            case doc
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            let scanned = try c.decode(Double.self, forKey: .scannedAt)
            self.scannedAt = scanned
            if let ctx = decoder.userInfo[LastExportCache.validationContextKey] as? ValidationContext {
                let age = ctx.now.timeIntervalSince1970 - scanned
                guard scanned.isFinite, age >= 0, age < ctx.maxAge else {
                    self.doc = nil
                    return
                }
            }
            self.doc = try c.decode(UsageReport.self, forKey: .doc)
        }
    }

    public let fileURL: URL

    /// Mirrors `cli/kanjo/cache.py:_cache_dir` and `cli/kanjo/winsupport.py:kanjo_cache_dir`:
    /// `KANJO_CACHE_DIR` -> `XDG_CACHE_HOME/kanjo` -> `~/.cache/kanjo`.
    public static func cacheDirectory(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        home: URL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
    ) -> URL {
        if let explicit = environment["KANJO_CACHE_DIR"], !explicit.isEmpty {
            let expanded = (explicit as NSString).expandingTildeInPath
            return URL(fileURLWithPath: expanded, isDirectory: true)
        }
        if let xdg = environment["XDG_CACHE_HOME"], !xdg.isEmpty {
            let expanded = (xdg as NSString).expandingTildeInPath
            return URL(fileURLWithPath: expanded, isDirectory: true)
                .appendingPathComponent("kanjo", isDirectory: true)
        }
        return home
            .appendingPathComponent(".cache", isDirectory: true)
            .appendingPathComponent("kanjo", isDirectory: true)
    }

    public init(fileURL: URL) {
        self.fileURL = fileURL
    }

    public init(
        directory: URL? = nil,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        home: URL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
    ) {
        let dir = directory ?? Self.cacheDirectory(environment: environment, home: home)
        self.fileURL = dir.appendingPathComponent(Self.fileName, isDirectory: false)
    }

    public func load(now: Date = Date(), maxAge: TimeInterval = LastExportCache.defaultMaxAge) -> UsageReport? {
        guard let data = try? Data(contentsOf: fileURL), !data.isEmpty else {
            return nil
        }
        let decoder = ReportDecoder.makeDecoder()
        decoder.userInfo[Self.validationContextKey] = ValidationContext(now: now, maxAge: maxAge)
        guard let envelope = try? decoder.decode(Envelope.self, from: data) else {
            return nil
        }
        return envelope.doc
    }
}

/// Formats stale report timestamps in the report's timezone, showing a date when not today.
public enum StaleReportText {
    public static func timestamp(
        generatedAt: String,
        timezoneIdentifier: String?,
        now: Date = Date(),
        language: String? = nil
    ) -> String? {
        guard let date = ReportDates.parseTimestamp(generatedAt) else { return nil }
        let tz = timezoneIdentifier.flatMap(TimeZone.init(identifier:)) ?? .current
        let cal = RangeEngine.calendar(timezone: tz)

        let timeFormatter = DateFormatter()
        timeFormatter.locale = Locale(identifier: "en_US_POSIX")
        timeFormatter.calendar = cal
        timeFormatter.timeZone = tz
        timeFormatter.dateFormat = "HH:mm"
        let timePart = timeFormatter.string(from: date)

        if cal.isDate(date, inSameDayAs: now) {
            return timePart
        }

        let lang = language ?? L10n.currentLanguage
        let dayFormatter = DateFormatter()
        dayFormatter.locale = Locale(identifier: lang)
        dayFormatter.calendar = cal
        dayFormatter.timeZone = tz
        let sameYear = cal.component(.year, from: date) == cal.component(.year, from: now)
        dayFormatter.setLocalizedDateFormatFromTemplate(sameYear ? "MMMd" : "yMMMd")
        return "\(dayFormatter.string(from: date)) \(timePart)"
    }

    public static func footerStatus(
        generatedAt: String?,
        timezoneIdentifier: String?,
        isLoading: Bool,
        now: Date = Date(),
        language: String? = nil
    ) -> String {
        let lang = language ?? L10n.currentLanguage
        guard let generatedAt,
              let formatted = timestamp(
                  generatedAt: generatedAt,
                  timezoneIdentifier: timezoneIdentifier,
                  now: now,
                  language: lang
              ) else {
            return L10n.tr(isLoading ? "menu.refreshing" : "menu.not_refreshed_yet", language: lang)
        }
        return L10n.tr(isLoading ? "menu.stale_updating" : "menu.stale_at", language: lang, formatted)
    }
}
