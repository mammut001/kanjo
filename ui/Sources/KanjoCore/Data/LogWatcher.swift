#if os(macOS)

import Foundation
import CoreServices

public final class LogWatcher {
    private var streamRef: FSEventStreamRef?
    private let queue = DispatchQueue(label: "com.kanjo.logwatcher", qos: .utility)
    private let onChange: () -> Void

    public init(paths: [String], onChange: @escaping () -> Void) {
        self.onChange = onChange
        start(paths: paths)
    }

    deinit {
        stop()
    }

    public func update(paths: [String]) {
        stop()
        start(paths: paths)
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
            watcher.onChange()
        }

        let flags = UInt32(kFSEventStreamCreateFlagNoDefer | kFSEventStreamCreateFlagWatchRoot)
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

    public func stop() {
        guard let stream = streamRef else { return }
        FSEventStreamStop(stream)
        FSEventStreamInvalidate(stream)
        FSEventStreamRelease(stream)
        streamRef = nil
    }
}

#endif
