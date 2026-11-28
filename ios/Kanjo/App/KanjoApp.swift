import BackgroundTasks
import KanjoCore
import SwiftUI
import WidgetKit
import os

enum BackgroundRefreshManager {
    static let taskIdentifier = WidgetSnapshotCache.backgroundRefreshIdentifier

    static func register() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: taskIdentifier, using: nil) { task in
            guard let refreshTask = task as? BGAppRefreshTask else {
                task.setTaskCompleted(success: false)
                return
            }
            handle(task: refreshTask)
        }
    }

    static func schedule() {
        let request = BGAppRefreshTaskRequest(identifier: taskIdentifier)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 30 * 60)
        do {
            try BGTaskScheduler.shared.submit(request)
            SyncLog.sync.info("BGAppRefreshTask scheduled")
        } catch {
            SyncLog.sync.info("BGAppRefreshTask schedule skipped: \(error.localizedDescription, privacy: .public)")
        }
    }

    private static func handle(task: BGAppRefreshTask) {
        schedule()
        let fetchTask = Task {
            let source = CloudKitSnapshotSource()
            do {
                if let report = try await source.load() {
                    _ = try? WidgetSnapshotCache.write(report: report, deviceName: source.lastDeviceName)
                    WidgetCenter.shared.reloadAllTimelines()
                }
                task.setTaskCompleted(success: true)
            } catch {
                SyncLog.sync.error("BGAppRefreshTask failed: \(error.localizedDescription, privacy: .private)")
                task.setTaskCompleted(success: false)
            }
        }
        task.expirationHandler = {
            fetchTask.cancel()
        }
    }
}

@main
struct KanjoApp: App {
    @State private var store = SnapshotStore()
    @Environment(\.scenePhase) private var scenePhase

    init() {
        BackgroundRefreshManager.register()
        WidgetSnapshotCache.syncLanguagePreference()
    }

    var body: some Scene {
        WindowGroup {
            RootView(store: store)
                .onAppear {
                    print("KANJO root appear args=\(CommandLine.arguments)")
                    BackgroundRefreshManager.schedule()
                }
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                BackgroundRefreshManager.schedule()
            }
        }
    }
}
