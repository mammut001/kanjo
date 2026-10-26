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

    public static let fallbackPlans: [String: [KnownPlan]] = [
        "claude": [
            KnownPlan(key: "pro", label: "Claude Pro", monthlyPriceUsd: 20.0),
            KnownPlan(key: "max_5x", label: "Claude Max 5x", monthlyPriceUsd: 100.0),
            KnownPlan(key: "max_20x", label: "Claude Max 20x", monthlyPriceUsd: 200.0)
        ],
        "codex": [
            KnownPlan(key: "plus", label: "ChatGPT Plus", monthlyPriceUsd: 20.0),
            KnownPlan(key: "pro", label: "ChatGPT Pro", monthlyPriceUsd: 200.0),
            KnownPlan(key: "business", label: "ChatGPT Business", monthlyPriceUsd: 30.0),
            KnownPlan(key: "enterprise", label: "ChatGPT Enterprise", monthlyPriceUsd: 60.0),
            KnownPlan(key: "team", label: "ChatGPT Team", monthlyPriceUsd: 25.0),
            KnownPlan(key: "edu", label: "ChatGPT Edu", monthlyPriceUsd: 20.0)
        ],
        "antigravity": [
            KnownPlan(key: "pro", label: "Antigravity Pro", monthlyPriceUsd: 20.0)
        ],
        "grok": [
            KnownPlan(key: "supergrok", label: "SuperGrok", monthlyPriceUsd: 30.0),
            KnownPlan(key: "premium_plus", label: "X Premium+", monthlyPriceUsd: 16.0),
            KnownPlan(key: "premium", label: "X Premium", monthlyPriceUsd: 8.0),
            KnownPlan(key: "basic", label: "X Basic", monthlyPriceUsd: 3.0)
        ],
        "copilot": [
            KnownPlan(key: "free", label: "Copilot Free", monthlyPriceUsd: 0.0),
            KnownPlan(key: "pro", label: "Copilot Pro", monthlyPriceUsd: 10.0),
            KnownPlan(key: "individual", label: "Copilot Pro", monthlyPriceUsd: 10.0),
            KnownPlan(key: "pro_plus", label: "Copilot Pro+", monthlyPriceUsd: 39.0),
            KnownPlan(key: "business", label: "Copilot Business", monthlyPriceUsd: 19.0),
            KnownPlan(key: "enterprise", label: "Copilot Enterprise", monthlyPriceUsd: 39.0)
        ],
        "minimax": [
            KnownPlan(key: "starter", label: "MiniMax Coding Plan Starter", monthlyPriceUsd: 10.0),
            KnownPlan(key: "coding_plan_starter", label: "MiniMax Coding Plan Starter", monthlyPriceUsd: 10.0),
            KnownPlan(key: "plus", label: "MiniMax Coding Plan Plus", monthlyPriceUsd: 20.0),
            KnownPlan(key: "coding_plan_plus", label: "MiniMax Coding Plan Plus", monthlyPriceUsd: 20.0),
            KnownPlan(key: "max", label: "MiniMax Coding Plan Max", monthlyPriceUsd: 50.0),
            KnownPlan(key: "coding_plan_max", label: "MiniMax Coding Plan Max", monthlyPriceUsd: 50.0)
        ],
        "qwen": [
            KnownPlan(key: "coding_plan", label: "Qwen Coding Plan Pro", monthlyPriceUsd: 50.0),
            KnownPlan(key: "pro", label: "Qwen Coding Plan Pro", monthlyPriceUsd: 50.0)
        ],
        "commandcode": [
            KnownPlan(key: "go", label: "Command Code Go", monthlyPriceUsd: 1.0),
            KnownPlan(key: "goat", label: "Command Code GOAT", monthlyPriceUsd: 10.0),
            KnownPlan(key: "provider", label: "Command Code Provider", monthlyPriceUsd: nil),
            KnownPlan(key: "pro", label: "Command Code Pro", monthlyPriceUsd: nil),
            KnownPlan(key: "max", label: "Command Code Max", monthlyPriceUsd: nil)
        ],
        "opencode": [
            KnownPlan(key: "go", label: "OpenCode Go", monthlyPriceUsd: 10.0)
        ]
    ]
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
