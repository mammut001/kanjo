import Foundation

public enum FirstScanHint {
    /// 触发慢速提示的耗时阈值（秒）：加载达到 3 秒及以上时展示。
    public static let thresholdSeconds: TimeInterval = 3.0

    /// 纯函数：决定是否应当展示首次运行慢速提示。
    /// - 没有报告且耗时 >= 3 秒时返回 true；已有报告时（包括后台刷新）返回 false。
    public static func shouldShow(hasReport: Bool, elapsed: TimeInterval) -> Bool {
        !hasReport && elapsed >= thresholdSeconds
    }

    public static func shouldShow(hasReport: Bool, elapsedSeconds: Double) -> Bool {
        shouldShow(hasReport: hasReport, elapsed: elapsedSeconds)
    }

    public static func shouldShow(report: UsageReport?, elapsed: TimeInterval) -> Bool {
        shouldShow(hasReport: report != nil, elapsed: elapsed)
    }

    public static func shouldShow(report: UsageReport?, elapsedSeconds: Double) -> Bool {
        shouldShow(report: report, elapsed: elapsedSeconds)
    }

    public static func shouldShowHint(hasReport: Bool, elapsed: TimeInterval) -> Bool {
        shouldShow(hasReport: hasReport, elapsed: elapsed)
    }

    public static func shouldShowHint(hasReport: Bool, elapsedSeconds: Double) -> Bool {
        shouldShow(hasReport: hasReport, elapsed: elapsedSeconds)
    }

    public static func shouldShowHint(report: UsageReport?, elapsed: TimeInterval) -> Bool {
        shouldShow(report: report, elapsed: elapsed)
    }

    public static func shouldShowHint(report: UsageReport?, elapsedSeconds: Double) -> Bool {
        shouldShow(report: report, elapsed: elapsedSeconds)
    }

    /// 首次扫描解释文案
    public static func explanation(language: String? = nil) -> String {
        L10n.tr("menu.first_scan_hint", language: language)
    }

    /// 已用时间文案（格式化秒数，如 "已用 12 秒" / "12 s elapsed" / "12 s écoulées"）
    public static func elapsedText(seconds: Int, language: String? = nil) -> String {
        L10n.tr("menu.first_scan_elapsed", language: language, max(0, seconds))
    }

    public static func elapsedText(elapsed: TimeInterval, language: String? = nil) -> String {
        elapsedText(seconds: Int(max(0, elapsed)), language: language)
    }
}

public typealias FirstRunHint = FirstScanHint

public func shouldShowFirstScanHint(hasReport: Bool, elapsed: TimeInterval) -> Bool {
    FirstScanHint.shouldShow(hasReport: hasReport, elapsed: elapsed)
}

public func shouldShowFirstScanHint(hasReport: Bool, elapsedSeconds: Double) -> Bool {
    FirstScanHint.shouldShow(hasReport: hasReport, elapsed: elapsedSeconds)
}

public func shouldShowFirstScanHint(report: UsageReport?, elapsed: TimeInterval) -> Bool {
    FirstScanHint.shouldShow(report: report, elapsed: elapsed)
}

public func shouldShowFirstScanHint(report: UsageReport?, elapsedSeconds: Double) -> Bool {
    FirstScanHint.shouldShow(report: report, elapsed: elapsedSeconds)
}

public func shouldShowFirstRunHint(hasReport: Bool, elapsed: TimeInterval) -> Bool {
    FirstScanHint.shouldShow(hasReport: hasReport, elapsed: elapsed)
}

public func shouldShowFirstRunHint(hasReport: Bool, elapsedSeconds: Double) -> Bool {
    FirstScanHint.shouldShow(hasReport: hasReport, elapsed: elapsedSeconds)
}

public func shouldShowFirstRunHint(report: UsageReport?, elapsed: TimeInterval) -> Bool {
    FirstScanHint.shouldShow(report: report, elapsed: elapsed)
}

public func shouldShowFirstRunHint(report: UsageReport?, elapsedSeconds: Double) -> Bool {
    FirstScanHint.shouldShow(report: report, elapsed: elapsedSeconds)
}
