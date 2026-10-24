import Foundation

// 隐藏 / 置顶项目：UI 用 @AppStorage 存成换行分隔的 project id 字符串。这里只做纯解析与排列。

public enum ProjectPrefs {
    /// 换行分隔 → 集合。忽略空行和首尾空白。
    public static func parse(_ raw: String) -> Set<String> {
        Set(raw.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty })
    }

    /// 集合 → 换行分隔（排序后输出，保证稳定）。
    public static func serialize(_ ids: Set<String>) -> String {
        ids.sorted().joined(separator: "\n")
    }

    /// 在集合里加入 / 移除 `id`。
    public static func toggle(_ id: String, in ids: Set<String>) -> Set<String> {
        var s = ids
        if s.contains(id) { s.remove(id) } else { s.insert(id) }
        return s
    }

    /// 直接在存储字符串上切换。
    public static func toggle(_ id: String, in raw: String) -> String {
        serialize(toggle(id, in: parse(raw)))
    }

    /// 列表排列：隐藏的分出去；其余置顶的在前。两组内部都保持输入顺序（输入通常已按 cost 降序）。
    public static func arrange<T>(_ items: [T], id: (T) -> String,
                                  pinned: Set<String>, hidden: Set<String>) -> (visible: [T], hidden: [T]) {
        var top: [T] = [], rest: [T] = [], gone: [T] = []
        for item in items {
            let i = id(item)
            if hidden.contains(i) { gone.append(item) }
            else if pinned.contains(i) { top.append(item) }
            else { rest.append(item) }
        }
        return (top + rest, gone)
    }
}
