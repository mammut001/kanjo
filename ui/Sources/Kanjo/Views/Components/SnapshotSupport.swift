import SwiftUI

private struct SnapshotModeKey: EnvironmentKey {
    static let defaultValue: Bool = false
}

private struct ShareRenderKey: EnvironmentKey {
    static let defaultValue: Bool = false
}

extension EnvironmentValues {
    var isSnapshotMode: Bool {
        get { self[SnapshotModeKey.self] }
        set { self[SnapshotModeKey.self] = newValue }
    }

    /// 分享图离屏渲染（`ImageRenderer`）。为 true 时 `hoverTip` / `hoverCard` 不挂
    /// `NSViewRepresentable` 锚点探针，否则探针会被画成黄色 ⊘ 占位。
    var isShareRender: Bool {
        get { self[ShareRenderKey.self] }
        set { self[ShareRenderKey.self] = newValue }
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
