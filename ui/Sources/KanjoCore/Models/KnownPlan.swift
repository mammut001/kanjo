import Foundation

/// 从 `kanjo config plans --json` 读取的已知套餐档位。
public struct KnownPlan: Codable, Equatable, Hashable, Identifiable {
    public var id: String { key }
    public let key: String
    public let label: String
    public let monthlyPriceUsd: Double?

    enum CodingKeys: String, CodingKey {
        case key
        case label
        case monthlyPriceUsd = "monthly_price_usd"
    }

    public init(key: String, label: String, monthlyPriceUsd: Double? = nil) {
        self.key = key
        self.label = label
        self.monthlyPriceUsd = monthlyPriceUsd
    }
}

public enum SubscriptionPlanHelper {
    public struct SaveFields: Equatable {
        public let plan: String
        public let monthlyPriceUsd: Double?
        public let anchorDay: Int?

        public init(plan: String, monthlyPriceUsd: Double?, anchorDay: Int?) {
            self.plan = plan
            self.monthlyPriceUsd = monthlyPriceUsd
            self.anchorDay = anchorDay
        }
    }

    /// 决定保存哪些字段：
    /// - list price: 选中的已知档位有公开标价，且输入的月费等于标价（或未填写），则不写价格覆盖（monthlyPriceUsd: nil），由 CLI 自动使用标价。
    /// - override: 选中的已知档位有标价但用户修改了价格，或者已知档位本身无标价，保存用户输入的月费。
    /// - custom: 自定义档位（Other…），始终保存用户输入的月费。
    public static func fieldsToSave(
        plan: String,
        isCustom: Bool,
        enteredPrice: Double?,
        listPrice: Double?,
        anchorDay: Int?
    ) -> SaveFields {
        let trimmedPlan = plan.trimmingCharacters(in: .whitespacesAndNewlines)
        if isCustom {
            return SaveFields(plan: trimmedPlan, monthlyPriceUsd: enteredPrice, anchorDay: anchorDay)
        }
        guard let list = listPrice else {
            // 已知套餐但无标价，必须保存输入的价格
            return SaveFields(plan: trimmedPlan, monthlyPriceUsd: enteredPrice, anchorDay: anchorDay)
        }
        if let entered = enteredPrice, abs(entered - list) >= 0.005 {
            // 输入价格与标价不同，保存覆盖
            return SaveFields(plan: trimmedPlan, monthlyPriceUsd: entered, anchorDay: anchorDay)
        }
        // 输入价格与标价一致，无需保存月费覆盖
        return SaveFields(plan: trimmedPlan, monthlyPriceUsd: nil, anchorDay: anchorDay)
    }

    public static func fieldsToSave(
        planKey: String,
        enteredPrice: Double?,
        anchorDay: Int?,
        knownPlan: KnownPlan?
    ) -> SaveFields {
        fieldsToSave(
            plan: planKey,
            isCustom: knownPlan == nil,
            enteredPrice: enteredPrice,
            listPrice: knownPlan?.monthlyPriceUsd,
            anchorDay: anchorDay
        )
    }

    public static func fieldsToSave(
        planKey: String,
        isCustom: Bool,
        enteredPrice: Double?,
        anchorDay: Int?,
        knownPlans: [KnownPlan] = []
    ) -> SaveFields {
        let matching = isCustom ? nil : knownPlans.first(where: { $0.key == planKey })
        return fieldsToSave(
            plan: planKey,
            isCustom: isCustom || matching == nil,
            enteredPrice: enteredPrice,
            listPrice: matching?.monthlyPriceUsd,
            anchorDay: anchorDay
        )
    }
}
