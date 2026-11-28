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

    private enum FetchRaceResult {
        case fetched(WidgetSnapshot?)
        case timedOut
    }

    /// 先尝试从 iCloud（KVS / CloudKit）拉取最新快照，最多等待 `timeoutSeconds`（默认 8 秒）；
    /// 拉取成功则更新缓存并返回，失败或超时则回退到 App Group 缓存。
    static func fetchOrFallbackToCache(
        timeoutSeconds: TimeInterval = defaultTimeoutSeconds,
        fileURL: URL? = nil
    ) async -> WidgetSnapshot? {
        applySharedLanguagePreference()
        let cached = read(from: fileURL)

        let fetched: WidgetSnapshot? = await withTaskGroup(of: FetchRaceResult.self) { group in
            group.addTask {
                do {
                    let source = CloudKitSnapshotSource()
                    guard let report = try await source.load() else {
                        return .fetched(nil)
                    }
                    let snapshot = WidgetSnapshot(report: report, deviceName: source.lastDeviceName)
                    return .fetched(snapshot)
                } catch {
                    SyncLog.sync.info("widget live fetch failed, using cache: \(error.localizedDescription, privacy: .private)")
                    return .fetched(nil)
                }
            }
            group.addTask {
                let nanos = UInt64(max(0.1, timeoutSeconds) * 1_000_000_000)
                try? await Task.sleep(nanoseconds: nanos)
                return .timedOut
            }

            let first = await group.next() ?? .timedOut
            group.cancelAll()
            switch first {
            case .fetched(let snapshot):
                return snapshot
            case .timedOut:
                SyncLog.sync.info("widget live fetch timed out after \(timeoutSeconds, privacy: .public)s, using cache")
                return nil
            }
        }

        if let fetched {
            if let cached,
               let cachedDate = cached.generatedDate,
               let fetchedDate = fetched.generatedDate,
               fetchedDate < cachedDate {
                return cached
            }
            _ = try? write(fetched, to: fileURL)
            return fetched
        }
        return cached
    }
}
