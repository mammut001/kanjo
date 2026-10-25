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
            return "Scan time unknown"
        }
        let seconds = max(0, now.timeIntervalSince(date))
        if seconds < 60 { return "Scanned just now" }
        if seconds < 3600 { return "Scanned \(Int(seconds / 60)) min ago" }
        if seconds < 86400 { return "Scanned \(Int(seconds / 3600)) hr ago" }
        let days = Int(seconds / 86400)
        return "Scanned \(days) \(days == 1 ? "day" : "days") ago"
    }
}
