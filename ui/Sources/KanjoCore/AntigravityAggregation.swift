import Foundation

public struct AntigravityAccountAggregation: Equatable, Sendable {
    public var plan: String
    public var planLabel: String
    public var monthlyPriceUsd: Double
    public var accountsPriced: Int
}

public enum AntigravityAggregation {
    public static func aggregate(accounts: [AntigravityAccount]) -> AntigravityAccountAggregation? {
        var counts: [String: Int] = [:]
        var maxPrice: [String: Double] = [:]
        var distinctKeys = Set<String>()
        var totalPrice = 0.0
        var pricedCount = 0

        for acc in accounts {
            guard let plan = acc.plan, !plan.plan.isEmpty, plan.plan.lowercased() != "none" else {
                continue
            }
            
            pricedCount += 1
            distinctKeys.insert(plan.plan)
            let label = plan.planLabel
            let price = plan.monthlyPriceUsd ?? 0.0
            totalPrice += price
            counts[label, default: 0] += 1
            maxPrice[label] = max(maxPrice[label] ?? 0.0, price)
        }

        if pricedCount == 0 {
            return nil
        }

        let orderedLabels = counts.keys.sorted { lblA, lblB in
            let priceA = maxPrice[lblA] ?? 0.0
            let priceB = maxPrice[lblB] ?? 0.0
            if abs(priceA - priceB) > 1e-9 {
                return priceA > priceB
            }
            return lblA < lblB
        }

        let parts = orderedLabels.map { lbl in
            let count = counts[lbl] ?? 0
            if count > 1 {
                return "\(lbl) ×\(count)"
            } else {
                return lbl
            }
        }

        let planKey = distinctKeys.count == 1 ? distinctKeys.first! : "multi"
        let planLabel = parts.joined(separator: " + ")
        
        return AntigravityAccountAggregation(
            plan: planKey,
            planLabel: planLabel,
            monthlyPriceUsd: (totalPrice * 10000).rounded() / 10000,
            accountsPriced: pricedCount
        )
    }
}
