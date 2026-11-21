#if os(macOS)

import Foundation
import CoreServices

public final class LogWatcher {
    private static let queueKey = DispatchSpecificKey<Bool>()
    private var streamRef: FSEventStreamRef?
    private let queue = DispatchQueue(label: "com.kanjo.logwatcher", qos: .utility)
    private let onChange: () -> Void
    private var coalescer: EventCoalescer
    private var pending: DispatchWorkItem?

    public init(paths: [String], interval: TimeInterval = 60, onChange: @escaping () -> Void) {
        self.onChange = onChange
        self.coalescer = EventCoalescer(interval: interval)
        queue.setSpecific(key: Self.queueKey, value: true)
        start(paths: paths)
    }

    deinit {
        stop()
    }

    public func update(paths: [String]) {
        stop()
        start(paths: paths)
    }

    public func setCoalescingInterval(_ interval: TimeInterval) {
        queue.async { self.coalescer.interval = interval }
    }

    private func start(paths: [String]) {
        let validPaths = paths.filter { FileManager.default.fileExists(atPath: $0) }
        guard !validPaths.isEmpty else { return }

        var context = FSEventStreamContext(
            version: 0,
            info: Unmanaged.passUnretained(self).toOpaque(),
            retain: nil,
            release: nil,
            copyDescription: nil
        )

        let callback: FSEventStreamCallback = { (_, clientCallBackInfo, _, _, _, _) in
            guard let info = clientCallBackInfo else { return }
            let watcher = Unmanaged<LogWatcher>.fromOpaque(info).takeUnretainedValue()
            watcher.handleEvent()
        }

        let flags = UInt32(kFSEventStreamCreateFlagWatchRoot)
        guard let stream = FSEventStreamCreate(
            kCFAllocatorDefault,
            callback,
            &context,
            validPaths as CFArray,
            FSEventStreamEventId(kFSEventStreamEventIdSinceNow),
            5.0,
            flags
        ) else { return }

        self.streamRef = stream
        FSEventStreamSetDispatchQueue(stream, queue)
        FSEventStreamStart(stream)
    }

    private func handleEvent() {
        switch coalescer.event(at: Date()) {
        case .deliver:
            pending?.cancel()
            pending = nil
            onChange()
        case .schedule(let delay):
            pending?.cancel()
            let work = DispatchWorkItem { [weak self] in
                guard let self = self, self.coalescer.fire(at: Date()) else { return }
                self.pending = nil
                self.onChange()
            }
            pending = work
            queue.asyncAfter(deadline: .now() + delay, execute: work)
        case .none: break
        }
    }

    public func stop() {
        guard let stream = streamRef else { return }
        FSEventStreamStop(stream)
        FSEventStreamInvalidate(stream)
        FSEventStreamRelease(stream)
        streamRef = nil
        let cancel = { self.pending?.cancel(); self.pending = nil }
        if DispatchQueue.getSpecific(key: Self.queueKey) != nil { cancel() }
        else { queue.sync(execute: cancel) }
    }
}

#endif
