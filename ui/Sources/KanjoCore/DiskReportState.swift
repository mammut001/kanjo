import Foundation

/// DiskStore 使用的纯状态：刷新时始终保留上一份报告。
public struct DiskReportState {
    public private(set) var report: DiskReport?
    public private(set) var isLoading = false

    public init(report: DiskReport? = nil) { self.report = report }

    public var hasReport: Bool { report != nil }
    public var isRescanning: Bool { hasReport && isLoading }

    @discardableResult
    public mutating func beginRefresh() -> Bool {
        guard !isLoading else { return false }
        isLoading = true
        return true
    }

    public mutating func finishRefresh(report: DiskReport? = nil) {
        if let report { self.report = report }
        isLoading = false
    }
}

public enum DiskScanCaption {
    public static func text(for report: DiskReport, now: Date = Date()) -> String {
        guard let date = ReportDates.parseTimestamp(report.scannedAt ?? report.generatedAt) else {
            return L10n.tr("disk.scan_time_unknown")
        }
        let seconds = max(0, now.timeIntervalSince(date))
        if seconds < 60 { return L10n.tr("disk.scanned_just_now") }
        if seconds < 3600 { return L10n.tr("disk.scanned_min_ago", Int(seconds / 60)) }
        if seconds < 86400 { return L10n.tr("disk.scanned_hr_ago", Int(seconds / 3600)) }
        let days = Int(seconds / 86400)
        return days == 1 ? L10n.tr("disk.scanned_day_ago", days) : L10n.tr("disk.scanned_days_ago", days)
    }
}
