import Foundation

/// Pure scheduling decision engine for usage refreshes.
/// Handles debouncing, minimum intervals, coalescing, fallback timer, sleep/wake, and Low Power Mode.
public struct RefreshScheduler: Equatable {
    public static let defaultFallbackMinutes = 30
    public static let minimumFallbackMinutes = 15
    public static let debounceInterval: TimeInterval = 60
    public static let minimumRefreshInterval: TimeInterval = 120

    public enum Action: Equatable {
        case none
        case refreshNow
        case scheduleRefresh(after: TimeInterval)
    }

    public private(set) var lastRefreshTime: Date?
    public private(set) var lastEventTime: Date?
    public private(set) var isRefreshing: Bool = false
    public private(set) var hasPendingEventWhileRefreshing: Bool = false
    public private(set) var isAsleep: Bool = false
    public private(set) var isLowPowerMode: Bool = false
    public private(set) var pendingWakeRefresh: Bool = false
    public var fallbackMinutes: Int

    public init(
        fallbackMinutes: Int = defaultFallbackMinutes,
        lastRefreshTime: Date? = nil
    ) {
        self.fallbackMinutes = Self.migrateFallbackMinutes(fallbackMinutes)
        self.lastRefreshTime = lastRefreshTime
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
        if isAsleep || isLowPowerMode {
            pendingWakeRefresh = true
            return .none
        }
        if isRefreshing {
            hasPendingEventWhileRefreshing = true
            return .none
        }
        let debounceTarget = date.addingTimeInterval(Self.debounceInterval)
        let minIntervalTarget = (lastRefreshTime ?? .distantPast).addingTimeInterval(Self.minimumRefreshInterval)
        let scheduledTarget = max(debounceTarget, minIntervalTarget)
        let delay = max(0, scheduledTarget.timeIntervalSince(date))
        return .scheduleRefresh(after: delay)
    }

    /// Called when a refresh starts.
    public mutating func onRefreshStarted(at date: Date = Date()) {
        isRefreshing = true
        hasPendingEventWhileRefreshing = false
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
            let debounceTarget = (lastEventTime ?? date).addingTimeInterval(Self.debounceInterval)
            let minIntervalTarget = date.addingTimeInterval(Self.minimumRefreshInterval)
            let scheduledTarget = max(debounceTarget, minIntervalTarget)
            let delay = max(0, scheduledTarget.timeIntervalSince(date))
            return .scheduleRefresh(after: delay)
        }

        return .none
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
