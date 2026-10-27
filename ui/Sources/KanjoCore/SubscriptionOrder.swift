import Foundation

// 订阅卡片自定义排序与折叠辅助函数。
// UI 用 @AppStorage 存成逗号分隔的 agent id 字符串。这里只做纯解析、排列与折叠过滤。

public enum SubscriptionOrder {
    /// 逗号分隔 → agent 数组。保持出现顺序，去除重复项与首尾空白。
    public static func parse(_ raw: String) -> [String] {
        var seen = Set<String>()
        var order: [String] = []
        for item in raw.split(separator: ",").map({ $0.trimmingCharacters(in: .whitespacesAndNewlines) }).filter({ !$0.isEmpty }) {
            if seen.insert(item).inserted {
                order.append(item)
            }
        }
        return order
    }

    /// agent 数组 → 逗号分隔。
    public static func serialize(_ order: [String]) -> String {
        order.joined(separator: ",")
    }

    /// 应用保存的顺序：
    /// 1. 保存顺序中的 agent 在前；
    /// 2. 未在保存顺序中的 agent 保持默认排序（按账期用量降序）；
    /// 3. 保存顺序中未知的 agent 忽略。
    public static func apply(order: [String], to rows: [SubscriptionRow]) -> [SubscriptionRow] {
        var rowMap: [String: SubscriptionRow] = [:]
        for row in rows {
            rowMap[row.agent] = row
        }
        var result: [SubscriptionRow] = []
        var placedAgents = Set<String>()
        for agent in order {
            if let row = rowMap[agent], !placedAgents.contains(agent) {
                result.append(row)
                placedAgents.insert(agent)
            }
        }
        for row in rows {
            if !placedAgents.contains(row.agent) {
                result.append(row)
            }
        }
        return result
    }

    /// 将 source 移动到 target 的位置：
    /// 将 source 从列表中移除后，插入到 target 原本所在的位置。
    public static func move(from source: String, to target: String, in list: [String]) -> [String] {
        guard let fromIndex = list.firstIndex(of: source),
              let toIndex = list.firstIndex(of: target),
              fromIndex != toIndex else {
            return list
        }
        var result = list
        let item = result.remove(at: fromIndex)
        result.insert(item, at: toIndex)
        return result
    }

    /// 将 source 移动到 target 的位置（针对 SubscriptionRow 数组）。
    public static func move(from source: String, to target: String, in rows: [SubscriptionRow]) -> [SubscriptionRow] {
        guard let fromIndex = rows.firstIndex(where: { $0.agent == source }),
              let toIndex = rows.firstIndex(where: { $0.agent == target }),
              fromIndex != toIndex else {
            return rows
        }
        var result = rows
        let item = result.remove(at: fromIndex)
        result.insert(item, at: toIndex)
        return result
    }

    /// 基于下标的通用移动操作。
    public static func move<T>(from sourceIndex: Int, to targetIndex: Int, in list: [T]) -> [T] {
        guard sourceIndex != targetIndex,
              list.indices.contains(sourceIndex),
              list.indices.contains(targetIndex) else {
            return list
        }
        var result = list
        let item = result.remove(at: sourceIndex)
        result.insert(item, at: targetIndex)
        return result
    }

    /// 折叠/展开辅助函数：未展开时最多返回 limit 行（默认 3 行）；展开时返回全部。
    public static func visible<T>(_ items: [T], expanded: Bool, limit: Int = 3) -> [T] {
        if expanded || items.count <= limit {
            return items
        }
        return Array(items.prefix(max(0, limit)))
    }

    /// 支持 visible(rows:expanded:limit:) 形式调用。
    public static func visible<T>(rows: [T], expanded: Bool, limit: Int = 3) -> [T] {
        visible(rows, expanded: expanded, limit: limit)
    }

    /// 针对 SubscriptionRow 的专用重载。
    public static func visible(_ rows: [SubscriptionRow], expanded: Bool, limit: Int = 3) -> [SubscriptionRow] {
        if expanded || rows.count <= limit {
            return rows
        }
        return Array(rows.prefix(max(0, limit)))
    }

    public static func visible(rows: [SubscriptionRow], expanded: Bool, limit: Int = 3) -> [SubscriptionRow] {
        visible(rows, expanded: expanded, limit: limit)
    }
}
