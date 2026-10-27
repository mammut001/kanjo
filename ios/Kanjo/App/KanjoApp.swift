import SwiftUI

@main
struct KanjoApp: App {
    @State private var store = SnapshotStore()

    var body: some Scene {
        WindowGroup {
            RootView(store: store)
        }
    }
}
