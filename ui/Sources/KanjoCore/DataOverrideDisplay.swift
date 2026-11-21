import Foundation

/// Settings 页 `--data` 警告 / 当前来源里显示的路径。
///
/// 截图模式（`--snapshot`）只显示文件名：完整路径会随生成目录变化，
/// 还会把开发机的本地目录写进公开截图。正常运行时仍然显示完整路径。
public enum DataOverrideDisplay {
    public static func path(_ path: String, snapshot: Bool) -> String {
        snapshot ? (path as NSString).lastPathComponent : path
    }

    /// `File (--data): …` 文案（Settings 底部「Current source」与警告条共用）。
    public static func fileDataSourceDescription(path: String, snapshot: Bool) -> String {
        "File (--data): \(Self.path(path, snapshot: snapshot))"
    }
}
