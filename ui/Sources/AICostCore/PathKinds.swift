import Foundation

// 项目路径分类：把 agent 留下的临时目录（scratchpad、worktree、系统临时目录等）
// 和用户真正的项目目录分开，详情页默认只展示后者。

/// 系统临时目录前缀。
private let temporaryRootPrefixes = ["/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/"]
/// 相对 home 的 agent 数据目录前缀（`~/` 之后的部分）。
private let temporaryHomePrefixes = [".gemini/", ".claude/", ".codex/"]
/// 出现在任一路径分量里就算临时目录。
private let temporaryComponents: Set<String> = ["scratchpad", "scratch", "worktrees", ".worktrees"]

/// 路径是否是临时目录。`~` 按 `home` 展开（默认当前用户 home）。
public func isTemporaryPath(_ path: String, home: String = NSHomeDirectory()) -> Bool {
    let expanded = expandTilde(path, home: home)
    let homeSlash = home.hasSuffix("/") ? home : home + "/"
    let prefixes = temporaryRootPrefixes + temporaryHomePrefixes.map { homeSlash + $0 }
    for prefix in prefixes {
        // 前缀本身（不带结尾斜杠）也算，比如 "/tmp"。
        if expanded.hasPrefix(prefix) || expanded == String(prefix.dropLast()) { return true }
    }
    return expanded.split(separator: "/").contains { temporaryComponents.contains(String($0)) }
}

/// 按 `isTemporaryPath` 拆成主路径和临时路径，两组各自保持原顺序。
public func splitPaths(_ paths: [String], home: String = NSHomeDirectory())
    -> (primary: [String], temporary: [String]) {
    var primary: [String] = []
    var temporary: [String] = []
    for p in paths {
        if isTemporaryPath(p, home: home) { temporary.append(p) } else { primary.append(p) }
    }
    return (primary, temporary)
}

private func expandTilde(_ path: String, home: String) -> String {
    if path == "~" { return home }
    if path.hasPrefix("~/") {
        let base = home.hasSuffix("/") ? String(home.dropLast()) : home
        return base + path.dropFirst()
    }
    return path
}
