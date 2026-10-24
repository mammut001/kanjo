import AppKit
import SwiftUI
import KanjoCore

/// 项目行右键菜单 / 悬停按钮用到的动作。
enum ProjectActions {
    /// 第一个仍然存在的路径（主路径优先）。
    static func existingPath(_ p: Project) -> String? {
        let split = splitPaths(p.paths)
        return (split.primary + split.temporary).first { FileManager.default.fileExists(atPath: $0) }
    }

    /// 复制用的路径：存在的优先，否则第一个主路径。
    static func displayPath(_ p: Project) -> String? {
        existingPath(p) ?? splitPaths(p.paths).primary.first ?? p.paths.first
    }

    static func openInTerminal(_ path: String) {
        let url = URL(fileURLWithPath: path, isDirectory: true)
        guard let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Terminal") else {
            NSWorkspace.shared.open(url)
            return
        }
        NSWorkspace.shared.open([url], withApplicationAt: app, configuration: NSWorkspace.OpenConfiguration())
    }

    static func showInFinder(_ path: String) {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    static func copy(_ s: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(s, forType: .string)
    }
}

/// 右键菜单：Pin / Unpin、Hide / Unhide、Open in Terminal、Show in Finder、Copy path、Copy remote。
struct ProjectContextMenu: View {
    let project: Project
    let pinned: Bool
    let hidden: Bool
    let onTogglePin: () -> Void
    let onToggleHidden: () -> Void

    var body: some View {
        let existing = ProjectActions.existingPath(project)
        let path = ProjectActions.displayPath(project)
        if !hidden {
            Button(pinned ? "Unpin" : "Pin", action: onTogglePin)
        }
        Button(hidden ? "Unhide" : "Hide", action: onToggleHidden)
        Divider()
        Button("Open in Terminal") { existing.map(ProjectActions.openInTerminal) }
            .disabled(existing == nil)
        Button("Show in Finder") { existing.map(ProjectActions.showInFinder) }
            .disabled(existing == nil)
        Divider()
        Button("Copy path") { path.map(ProjectActions.copy) }
            .disabled(path == nil)
        Button("Copy remote") { project.remote.map(ProjectActions.copy) }
            .disabled(project.remote == nil)
    }
}

/// 行上的小图标按钮（置顶 / 隐藏 / 取消隐藏）。
struct RowIconButton: View {
    let systemName: String
    var tint: Color? = nil
    let help: String
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(tint ?? (hover ? Color.primary : Color.secondary))
                .frame(width: 20, height: 18)
                .background(RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .fill(hover ? AgentPalette.rowPressed : Color.clear))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(help)
    }
}
