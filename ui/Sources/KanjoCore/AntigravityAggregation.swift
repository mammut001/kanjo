import Foundation

/// Antigravity 多账号套餐的合计结果，对应 CLI `subscriptions` 里 antigravity 的 plan / plan_label / monthly_price_usd / accounts_priced。
public struct AntigravityAccountAggregation: Equatable, Sendable {
    public var plan: String
    public var planLabel: String
    public var monthlyPriceUsd: Double
    public var accountsPriced: Int
}

/// 设置页的账号套餐选择器在写入 overrides.json 之前就要显示新的合计，
/// 所以这里镜像 cli/kanjo/subscriptions.py 的 `_aggregate_antigravity_accounts`。
public enum AntigravityAggregation {
    /// 空字符串、"none" 和缺省都表示该账号没有套餐。
    public static func normalizedPlanKey(_ key: String?) -> String {
        let trimmed = (key ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.lowercased() == "none" ? "" : trimmed
    }

    public static func aggregate(accounts: [AntigravityAccount]) -> AntigravityAccountAggregation? {
        var counts: [String: Int] = [:]
        var maxPrice: [String: Double] = [:]
        var distinctKeys = Set<String>()
        var totalPrice = 0.0
        var pricedCount = 0

        for acc in accounts {
            guard let plan = acc.plan, !normalizedPlanKey(plan.plan).isEmpty else { continue }
            pricedCount += 1
            distinctKeys.insert(plan.plan)
            let label = plan.planLabel
            let price = plan.monthlyPriceUsd ?? 0.0
            totalPrice += price
            counts[label, default: 0] += 1
            maxPrice[label] = max(maxPrice[label] ?? 0.0, price)
        }

        guard pricedCount > 0 else { return nil }

        let orderedLabels = counts.keys.sorted { a, b in
            let priceA = maxPrice[a] ?? 0.0
            let priceB = maxPrice[b] ?? 0.0
            if priceA != priceB { return priceA > priceB }
            return a < b
        }
        let parts = orderedLabels.map { label -> String in
            let count = counts[label] ?? 0
            return count > 1 ? "\(label) ×\(count)" : label
        }

        return AntigravityAccountAggregation(
            plan: distinctKeys.count == 1 ? distinctKeys.first! : "multi",
            planLabel: parts.joined(separator: " + "),
            monthlyPriceUsd: (totalPrice * 10000).rounded() / 10000,
            accountsPriced: pricedCount
        )
    }

    /// 把还没出现在报告里的选择（email -> plan key，"" 表示无套餐）套到报告的账号上。
    /// 已知套餐用它的名称和价格；报告里已是同一 key 时保留报告的值（可能带自定义价格）。
    public static func applyPending(accounts: [AntigravityAccount], pending: [String: String],
                                    knownPlans: [KnownPlan]) -> [AntigravityAccount] {
        guard !pending.isEmpty else { return accounts }
        return accounts.map { acc in
            guard let raw = pending[acc.email] else { return acc }
            var updated = acc
            let key = normalizedPlanKey(raw)
            if key.isEmpty {
                updated.plan = nil
            } else if let current = acc.plan, current.plan == key {
                updated.plan = current
            } else if let known = knownPlans.first(where: { $0.key == key }) {
                updated.plan = AntigravityAccountPlan(plan: known.key, planLabel: known.label,
                                                      monthlyPriceUsd: known.monthlyPriceUsd)
            } else {
                updated.plan = AntigravityAccountPlan(plan: key, planLabel: key, monthlyPriceUsd: nil)
            }
            return updated
        }
    }

    /// 新报告到达后仍需保留的 pending：报告已显示所选套餐的账号去掉；
    /// `busy` 里的账号（还有写入排队或正在写）一律保留，免得旧报告把较新的选择冲掉。
    public static func remainingPending(_ pending: [String: String], report accounts: [AntigravityAccount],
                                       busy: Set<String> = []) -> [String: String] {
        guard !pending.isEmpty else { return pending }
        var remaining = pending
        for acc in accounts {
            guard let wanted = pending[acc.email], !busy.contains(acc.email) else { continue }
            if normalizedPlanKey(acc.plan?.plan) == normalizedPlanKey(wanted) {
                remaining.removeValue(forKey: acc.email)
            }
        }
        return remaining
    }
}
