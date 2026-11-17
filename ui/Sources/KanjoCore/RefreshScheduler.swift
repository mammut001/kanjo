import Foundation

/// Pure scheduling decision engine for usage refreshes.
/// Handles debouncing, minimum intervals, coalescing, fallback timer, sleep/wake, and Low Power Mode.
public struct RefreshScheduler: Equatable {
    public static let defaultFallbackMinutes = 30
    public static let minimumFallbackMinutes = 15
    public static let debounceInterval: TimeInterval = 60
    public static let minimumRefreshInterval: TimeInterval = 120
    public static let hiddenMinimumRefreshInterval: TimeInterval = 600
    public static let maxDebounceWait: TimeInterval = 180

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
    public private(set) var pendingWakeRefresh: Bool = false
    public var fallbackMinutes: Int

    public init(
        fallbackMinutes: Int = defaultFallbackMinutes,
        lastRefreshTime: Date? = nil,
        isPanelVisible: Bool = false
    ) {
        self.fallbackMinutes = Self.migrateFallbackMinutes(fallbackMinutes)
        self.lastRefreshTime = lastRefreshTime
        self.isPanelVisible = isPanelVisible
    }

    private var activeMinimumRefreshInterval: TimeInterval {
        isPanelVisible ? Self.minimumRefreshInterval : Self.hiddenMinimumRefreshInterval
    }

    private mutating func scheduleFileEventRefresh(at date: Date, minIntervalAnchor: Date?) -> Action {
        let firstEvent = firstUnhandledEventTime ?? (lastEventTime ?? date)
        let deadline = firstEvent.addingTimeInterval(Self.maxDebounceWait)
        let debounceTarget = (lastEventTime ?? date).addingTimeInterval(Self.debounceInterval)
        let effectiveTarget = min(debounceTarget, deadline)
        let minIntervalTarget = (minIntervalAnchor ?? .distantPast).addingTimeInterval(activeMinimumRefreshInterval)
        let scheduledTarget = max(effectiveTarget, minIntervalTarget)
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
        if isAsleep || isLowPowerMode {
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

        if isAsleep || isLowPowerMode {
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

        if isAsleep || isLowPowerMode || isRefreshing || !hasScheduledRefresh {
            return .none
        }

        if visible {
            let sinceLastRefresh = date.timeIntervalSince(lastRefreshTime ?? .distantPast)
            if sinceLastRefresh > Self.minimumRefreshInterval {
                hasScheduledRefresh = false
                return .refreshNow
            }
        }

        return scheduleFileEventRefresh(at: date, minIntervalAnchor: lastRefreshTime)
    }

    /// Called when the menu panel opens.
    /// Refreshes immediately if last refresh was more than 120s ago or has never occurred.
    public func shouldRefreshOnOpen(at date: Date = Date()) -> Bool {
        if isRefreshing { return false }
        guard let last = lastRefreshTime else { return true }
        return date.timeIntervalSince(last) > Self.minimumRefreshInterval
    }

    /// System will sleep.
    public mutating func onSleep() {
        isAsleep = true
        hasScheduledRefresh = false
    }

    /// System did wake.
    public mutating func onWake(at date: Date = Date()) -> Action {
        isAsleep = false
        guard pendingWakeRefresh else { return .none }
        pendingWakeRefresh = false
        if isRefreshing { return .none }
        let minIntervalTarget = (lastRefreshTime ?? .distantPast).addingTimeInterval(Self.minimumRefreshInterval)
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
            pendingWakeRefresh = false
            if isRefreshing { return .none }
            let minIntervalTarget = (lastRefreshTime ?? .distantPast).addingTimeInterval(Self.minimumRefreshInterval)
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
        if isAsleep || isLowPowerMode {
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
