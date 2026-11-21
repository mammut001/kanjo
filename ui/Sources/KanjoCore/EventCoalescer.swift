import Foundation

/// Leading delivery plus one trailing delivery for changes suppressed in the interval.
public struct EventCoalescer {
    public enum Action: Equatable {
        case deliver
        case schedule(after: TimeInterval)
        case none
    }
    public var interval: TimeInterval
    private var lastDelivery: Date?
    private var pending = false

    public init(interval: TimeInterval) { self.interval = interval }

    public mutating func event(at now: Date) -> Action {
        guard let last = lastDelivery else {
            lastDelivery = now
            return .deliver
        }
        let delay = interval - now.timeIntervalSince(last)
        if delay <= 0 {
            pending = false
            lastDelivery = now
            return .deliver
        }
        guard !pending else { return .none }
        pending = true
        return .schedule(after: delay)
    }

    public mutating func fire(at now: Date) -> Bool {
        guard pending else { return false }
        pending = false
        lastDelivery = now
        return true
    }
}
