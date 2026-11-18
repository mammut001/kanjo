import Foundation

public struct RefreshScheduler: Equatable {
    public static let defaultFallbackMinutes = 30
    public static let minimumFallbackMinutes = 15

    public enum Action: Equatable {
        case none
        case refreshNow
        case scheduleRefresh(after: TimeInterval)
    }

    public private(set) var lastRefreshTime: Date?
    public private(set) var lastEventTime: Date?
    public private(set) var firstUnhandledEventTime: Date?
    public private(set) var isRefreshing: Bool = false
    public private(set) var hasPendingEventWhileRefreshing: Bool = false
    public private(set) var hasScheduledRefresh: Bool = false
    public private(set) var isPanelVisible: Bool = false
    public private(set) var isAsleep: Bool = false
    public private(set) var isLowPowerMode: Bool = false
    public private(set) var isSystemBusy: Bool = false
    public private(set) var pendingWakeRefresh: Bool = false
    public var fallbackMinutes: Int
    public var backgroundInterval: TimeInterval

    public init(
        fallbackMinutes: Int = defaultFallbackMinutes,
        backgroundInterval: TimeInterval = 60,
        lastRefreshTime: Date? = nil,
        isPanelVisible: Bool = false
    ) {
        self.fallbackMinutes = Self.migrateFallbackMinutes(fallbackMinutes)
        self.backgroundInterval = backgroundInterval
        self.lastRefreshTime = lastRefreshTime
        self.isPanelVisible = isPanelVisible
    }

    public mutating func onBackgroundIntervalChanged(_ interval: TimeInterval, at date: Date = Date()) -> Action {
        self.backgroundInterval = interval
        if hasScheduledRefresh {
            return scheduleFileEventRefresh(at: date, minIntervalAnchor: lastRefreshTime)
        }
        return .none
    }

    private mutating func scheduleFileEventRefresh(at date: Date, minIntervalAnchor: Date?) -> Action {
        let firstEvent = firstUnhandledEventTime ?? date
        let eventDeadline = firstEvent.addingTimeInterval(5)
        let minIntervalTarget = (minIntervalAnchor ?? .distantPast).addingTimeInterval(backgroundInterval)
        
        let scheduledTarget = max(eventDeadline, minIntervalTarget)
        
        let delay = max(0, scheduledTarget.timeIntervalSince(date))
        hasScheduledRefresh = true
        return .scheduleRefresh(after: delay)
    }

    public static func migrateFallbackMinutes(_ stored: Int) -> Int {
        if stored == 0 { return 0 }
        if stored == 5 || stored < minimumFallbackMinutes {
            return defaultFallbackMinutes
        }
        return stored
    }

    /// Called when an FSEvent notifies us of a file change in an agent log directory.
    public mutating func onFileEvent(at date: Date = Date()) -> Action {
        lastEventTime = date
        if firstUnhandledEventTime == nil {
            firstUnhandledEventTime = date
        }
        if isAsleep || isLowPowerMode || isSystemBusy {
            pendingWakeRefresh = true
            return .none
        }
        if isRefreshing {
            hasPendingEventWhileRefreshing = true
            return .none
        }
        return scheduleFileEventRefresh(at: date, minIntervalAnchor: lastRefreshTime)
    }

    /// Called when a refresh starts.
    public mutating func onRefreshStarted(at date: Date = Date()) {
        isRefreshing = true
        hasPendingEventWhileRefreshing = false
        hasScheduledRefresh = false
        firstUnhandledEventTime = nil
    }

    /// Called when a refresh finishes.
    public mutating func onRefreshFinished(at date: Date = Date()) -> Action {
        isRefreshing = false
        lastRefreshTime = date

        if isAsleep || isLowPowerMode || isSystemBusy {
            return .none
        }

        if hasPendingEventWhileRefreshing {
            hasPendingEventWhileRefreshing = false
            return scheduleFileEventRefresh(at: date, minIntervalAnchor: date)
        }

        return .none
    }

    /// Called when the menu panel becomes visible or hidden.
    /// Re-evaluates any pending scheduled refresh under the updated visibility rules.
    public mutating func onPanelVisibilityChanged(visible: Bool, at date: Date = Date()) -> Action {
        guard isPanelVisible != visible else { return .none }
        isPanelVisible = visible

        if isAsleep || isLowPowerMode || isSystemBusy || isRefreshing || !hasScheduledRefresh {
            return .none
        }

        return scheduleFileEventRefresh(at: date, minIntervalAnchor: lastRefreshTime)
    }

    /// Called when the menu panel opens.
    /// Refreshes immediately only if the report is stale from the launch cache and no refresh is running.
    public func shouldRefreshOnOpen(isStaleReport: Bool = false) -> Bool {
        return isStaleReport && !isRefreshing
    }

    /// System will sleep.
    public mutating func onSleep() {
        isAsleep = true
        hasScheduledRefresh = false
    }

    /// System did wake.
    public mutating func onWake(at date: Date = Date()) -> Action {
        isAsleep = false
        if isSystemBusy {
            pendingWakeRefresh = true
            return .none
        }
        guard pendingWakeRefresh else { return .none }
        pendingWakeRefresh = false
        if isRefreshing { return .none }
        let minIntervalTarget = (lastRefreshTime ?? .distantPast).addingTimeInterval(backgroundInterval)
        if date >= minIntervalTarget {
            return .refreshNow
        } else {
            hasScheduledRefresh = true
            return .scheduleRefresh(after: max(0, minIntervalTarget.timeIntervalSince(date)))
        }
    }

    /// Low Power Mode state changed.
    public mutating func onLowPowerModeChanged(enabled: Bool, at date: Date = Date()) -> Action {
        isLowPowerMode = enabled
        if !enabled && pendingWakeRefresh {
            if isSystemBusy { return .none }
            pendingWakeRefresh = false
            if isRefreshing { return .none }
            let minIntervalTarget = (lastRefreshTime ?? .distantPast).addingTimeInterval(backgroundInterval)
            if date >= minIntervalTarget {
                return .refreshNow
            } else {
                hasScheduledRefresh = true
                return .scheduleRefresh(after: max(0, minIntervalTarget.timeIntervalSince(date)))
            }
        }
        return .none
    }

    /// System busy state changed.
    public mutating func onSystemBusyChanged(busy: Bool, at date: Date = Date()) -> Action {
        isSystemBusy = busy
        if !busy && pendingWakeRefresh {
            if isAsleep || isLowPowerMode { return .none }
            pendingWakeRefresh = false
            if isRefreshing { return .none }
            let minIntervalTarget = (lastRefreshTime ?? .distantPast).addingTimeInterval(backgroundInterval)
            if date >= minIntervalTarget {
                return .refreshNow
            } else {
                hasScheduledRefresh = true
                return .scheduleRefresh(after: max(0, minIntervalTarget.timeIntervalSince(date)))
            }
        }
        return .none
    }

    /// Called when the fallback timer fires.
    public mutating func onFallbackTimerFired(at date: Date = Date()) -> Action {
        if fallbackMinutes <= 0 { return .none }
        if isAsleep || isLowPowerMode || isSystemBusy {
            pendingWakeRefresh = true
            return .none
        }
        if isRefreshing {
            hasPendingEventWhileRefreshing = true
            return .none
        }
        let fallbackSeconds = TimeInterval(fallbackMinutes * 60)
        let elapsed = date.timeIntervalSince(lastRefreshTime ?? .distantPast)
        if elapsed >= fallbackSeconds {
            return .refreshNow
        }
        return .none
    }
}
