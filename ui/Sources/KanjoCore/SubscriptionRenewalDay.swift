import Foundation

/// Manual overrides in overrides.json are limited to 1…28; detected subscription dates may be 29–31.
public enum SubscriptionRenewalDay {
    public static let manualMax = 28

    /// Value for the settings stepper (always within the manual override range).
    public static func stepperValue(anchorDay: Int?) -> Int {
        min(manualMax, max(1, anchorDay ?? 1))
    }

    /// Detected anchors above ``manualMax`` follow the real subscription calendar (e.g. day 31 → Feb 28/29).
    public static func isDetectedHighAnchor(_ sub: Subscription) -> Bool {
        guard let day = sub.anchorDay else { return false }
        return day > manualMax && sub.cycleSource != "manual"
    }

    /// Applying the stepper would wrongly clamp a detected high anchor down to 28.
    public static func allowsManualStepper(_ sub: Subscription?) -> Bool {
        guard let sub else { return true }
        return !isDetectedHighAnchor(sub)
    }
}