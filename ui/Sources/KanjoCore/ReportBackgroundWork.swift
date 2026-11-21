/// Controls work that is useful for the interactive app but not one-shot renderers.
public struct ReportBackgroundWork {
    public let isEnabled: Bool

    public init(isSnapshot: Bool) {
        isEnabled = !isSnapshot
    }

    public func start(checkPython: () -> Void, loadKnownPlans: () -> Void,
                      restartTimer: () -> Void, setupWatcher: () -> Void,
                      setupNotifications: () -> Void) {
        guard isEnabled else { return }
        setupNotifications()
        checkPython()
        loadKnownPlans()
        restartTimer()
        setupWatcher()
    }

    public func perform(_ work: () -> Void) {
        guard isEnabled else { return }
        work()
    }
}
