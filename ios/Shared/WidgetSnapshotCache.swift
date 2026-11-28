import Foundation
import KanjoCore
import os

/// App Group 共享缓存读写与带超时的 iCloud 拉取（供主 App、后台刷新与小组件扩展共用）。
enum WidgetSnapshotCache {
    static let appGroupIdentifier = "group.com.lanshuagent.kanjo"
    static let fileName = "widget-snapshot.json"
    static let backgroundRefreshIdentifier = "com.lanshuagent.kanjo.ios.refresh"
    static let overviewDeepLink = URL(string: "kanjo://overview")!
    static let defaultTimeoutSeconds: TimeInterval = 8.0

    static var sharedDefaults: UserDefaults? {
        UserDefaults(suiteName: appGroupIdentifier)
    }

    /// 同步主 App 的语言设置到 App Group，便于小组件进程按相同语言渲染。
    static func syncLanguagePreference(_ language: String? = nil) {
        let value = language ?? AppDefaults.store.string(forKey: SettingsKeys.appLanguage)
        if let value, !value.isEmpty {
            sharedDefaults?.set(value, forKey: SettingsKeys.appLanguage)
        } else {
            sharedDefaults?.removeObject(forKey: SettingsKeys.appLanguage)
        }
    }

    /// 小组件侧在渲染前把 App Group 中的语言偏好同步到当前进程的 `AppDefaults.store`。
    static func applySharedLanguagePreference() {
        if let lang = sharedDefaults?.string(forKey: SettingsKeys.appLanguage), !lang.isEmpty {
            AppDefaults.store.set(lang, forKey: SettingsKeys.appLanguage)
        }
    }

    static func containerURL(fileManager: FileManager = .default) -> URL? {
        fileManager.containerURL(forSecurityApplicationGroupIdentifier: appGroupIdentifier)
    }

    static func cacheFileURL(containerURL: URL? = nil, fileManager: FileManager = .default) -> URL? {
        guard let dir = containerURL ?? Self.containerURL(fileManager: fileManager) else {
            return nil
        }
        return dir.appendingPathComponent(fileName, isDirectory: false)
    }

    static func read(from fileURL: URL? = nil) -> WidgetSnapshot? {
        guard let url = fileURL ?? cacheFileURL(),
              FileManager.default.fileExists(atPath: url.path) else {
            return nil
        }
        do {
            let data = try Data(contentsOf: url)
            return try JSONDecoder().decode(WidgetSnapshot.self, from: data)
        } catch {
            SyncLog.sync.error("widget cache read failed: \(error.localizedDescription, privacy: .public)")
            return nil
        }
    }

    @discardableResult
    static func write(_ snapshot: WidgetSnapshot, to fileURL: URL? = nil) throws -> WidgetSnapshot {
        syncLanguagePreference()
        guard let url = fileURL ?? cacheFileURL() else {
            return snapshot
        }
        let dir = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        let data = try encoder.encode(snapshot)
        try data.write(to: url, options: [.atomic])
        SyncLog.sync.info("widget cache wrote \(data.count, privacy: .public) bytes")
        return snapshot
    }

    @discardableResult
    static func write(report: UsageReport, deviceName: String?, to fileURL: URL? = nil) throws -> WidgetSnapshot {
        let snapshot = WidgetSnapshot(report: report, deviceName: deviceName)
        return try write(snapshot, to: fileURL)
    }

    /// 先尝试从 iCloud（KVS / CloudKit）拉取最新快照，最多等待 `timeoutSeconds`（默认 8 秒）；
    /// 拉取成功且不比缓存旧则更新缓存并返回，失败或超时则回退到 App Group 缓存。
    ///
    /// `CloudKitSnapshotSource.load()` 里的 continuation 不响应取消，task group 的
    /// `cancelAll()` 停不掉它，组还会等所有子任务结束。所以拉取放在无结构 `Task` 里，
    /// 和超时 `Task` 抢一个只恢复一次的门闩：谁先到，函数就马上返回。超时先到时返回
    /// 已读到的缓存；拉取若稍后才结束，仍可按“比缓存新才写入”的规则更新缓存。
    static func fetchOrFallbackToCache(
        timeoutSeconds: TimeInterval = defaultTimeoutSeconds,
        fileURL: URL? = nil
    ) async -> WidgetSnapshot? {
        applySharedLanguagePreference()
        let cached = read(from: fileURL)

        let fetched: WidgetSnapshot? = await withCheckedContinuation { continuation in
            let gate = ResumeOnce()
            let timeoutTask = CancelBox()

            Task {
                let snapshot = await loadLiveSnapshot()
                if gate.claim() {
                    timeoutTask.cancel()
                    continuation.resume(returning: snapshot)
                } else if let snapshot {
                    // 函数已经带着缓存返回了。拉取更旧则保留缓存，否则补写。
                    let current = read(from: fileURL)
                    if shouldReplaceCache(current, with: snapshot) {
                        _ = try? write(snapshot, to: fileURL)
                    }
                }
            }
            let timeout = Task {
                let nanos = UInt64(max(0.1, timeoutSeconds) * 1_000_000_000)
                do {
                    try await Task.sleep(nanoseconds: nanos)
                } catch {
                    return
                }
                if gate.claim() {
                    SyncLog.sync.info("widget live fetch timed out after \(timeoutSeconds, privacy: .public)s, using cache")
                    continuation.resume(returning: nil)
                }
            }
            timeoutTask.store(timeout)
        }

        if let fetched {
            if shouldReplaceCache(cached, with: fetched) {
                _ = try? write(fetched, to: fileURL)
                return fetched
            }
            return cached
        }
        return cached
    }

    /// 拉取到的快照比缓存更旧时保留缓存。任一端没有可解析的生成时间则采用拉取结果。
    private static func shouldReplaceCache(_ cached: WidgetSnapshot?, with fetched: WidgetSnapshot) -> Bool {
        if let cached,
           let cachedDate = cached.generatedDate,
           let fetchedDate = fetched.generatedDate,
           fetchedDate < cachedDate {
            return false
        }
        return true
    }

    private static func loadLiveSnapshot() async -> WidgetSnapshot? {
        do {
            let source = CloudKitSnapshotSource()
            guard let report = try await source.load() else {
                return nil
            }
            return WidgetSnapshot(report: report, deviceName: source.lastDeviceName)
        } catch {
            SyncLog.sync.info("widget live fetch failed, using cache: \(error.localizedDescription, privacy: .private)")
            return nil
        }
    }

    /// 只让拉取和超时其中一方恢复 continuation。恢复发生在锁外，避免 resume 同步跑调用方时再入锁。
    private final class ResumeOnce: @unchecked Sendable {
        private let lock = NSLock()
        private var claimed = false

        func claim() -> Bool {
            lock.lock()
            defer { lock.unlock() }
            if claimed { return false }
            claimed = true
            return true
        }
    }

    /// 超时任务可能在 `store` 之前就被拉取结果取消，取消标志要先记下。
    private final class CancelBox: @unchecked Sendable {
        private let lock = NSLock()
        private var task: Task<Void, Never>?
        private var cancelled = false

        func store(_ task: Task<Void, Never>) {
            lock.lock()
            let shouldCancel = cancelled
            self.task = task
            lock.unlock()
            if shouldCancel {
                task.cancel()
            }
        }

        func cancel() {
            lock.lock()
            cancelled = true
            let task = self.task
            lock.unlock()
            task?.cancel()
        }
    }
}
