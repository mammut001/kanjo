import SwiftUI

private struct SnapshotModeKey: EnvironmentKey {
    static let defaultValue: Bool = false
}

extension EnvironmentValues {
    var isSnapshotMode: Bool {
        get { self[SnapshotModeKey.self] }
        set { self[SnapshotModeKey.self] = newValue }
    }
}

/// 截图模式下跳过 ScrollView，以支持 ImageRenderer 离屏完整渲染。
struct OptionalScrollView<Content: View>: View {
    @Environment(\.isSnapshotMode) private var isSnapshotMode
    @ViewBuilder let content: () -> Content

    var body: some View {
        if isSnapshotMode {
            content()
        } else {
            ScrollView {
                content()
            }
        }
    }
}
