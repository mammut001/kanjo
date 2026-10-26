import XCTest
@testable import KanjoCore

final class KnownPlanTests: KanjoTestCase {
    func testDecodeKnownPlansJSON() throws {
        let json = """
        {
          "claude": [
            {
              "key": "max_20x",
              "label": "Claude Max 20x",
              "monthly_price_usd": 200.0
            },
            {
              "key": "pro",
              "label": "Claude Pro",
              "monthly_price_usd": 20.0
            }
          ],
          "grok": [
            {
              "key": "supergrok",
              "label": "SuperGrok",
              "monthly_price_usd": 30.0
            },
            {
              "key": "premium_plus",
              "label": "X Premium+",
              "monthly_price_usd": null
            }
          ]
        }
        """.data(using: .utf8)!

        let decoded = try JSONDecoder().decode([String: [KnownPlan]].self, from: json)
        XCTAssertEqual(decoded.keys.sorted(), ["claude", "grok"])

        let claudePlans = try XCTUnwrap(decoded["claude"])
        XCTAssertEqual(claudePlans.count, 2)
        XCTAssertEqual(claudePlans[0].id, "max_20x")
        XCTAssertEqual(claudePlans[0].key, "max_20x")
        XCTAssertEqual(claudePlans[0].label, "Claude Max 20x")
        XCTAssertEqual(claudePlans[0].monthlyPriceUsd, 200.0)

        XCTAssertEqual(claudePlans[1].key, "pro")
        XCTAssertEqual(claudePlans[1].label, "Claude Pro")
        XCTAssertEqual(claudePlans[1].monthlyPriceUsd, 20.0)

        let grokPlans = try XCTUnwrap(decoded["grok"])
        XCTAssertEqual(grokPlans.count, 2)
        XCTAssertEqual(grokPlans[0].key, "supergrok")
        XCTAssertEqual(grokPlans[0].monthlyPriceUsd, 30.0)
        XCTAssertEqual(grokPlans[1].key, "premium_plus")
        XCTAssertEqual(grokPlans[1].label, "X Premium+")
        XCTAssertNil(grokPlans[1].monthlyPriceUsd)
    }

    func testHelperListPriceDecidesNilMonthlyPrice() {
        let plan = KnownPlan(key: "plus", label: "ChatGPT Plus", monthlyPriceUsd: 20.0)

        // User leaves price at list price: monthlyPriceUsd should be nil (not saved to overrides)
        let fieldsExact = SubscriptionPlanHelper.fieldsToSave(
            planKey: "plus",
            enteredPrice: 20.0,
            anchorDay: 15,
            knownPlan: plan
        )
        XCTAssertEqual(fieldsExact, SubscriptionPlanHelper.SaveFields(
            plan: "plus",
            monthlyPriceUsd: nil,
            anchorDay: 15
        ))

        // Nil entered price on known priced plan defaults to list price -> nil override
        let fieldsNil = SubscriptionPlanHelper.fieldsToSave(
            planKey: "plus",
            enteredPrice: nil,
            anchorDay: 1,
            knownPlan: plan
        )
        XCTAssertEqual(fieldsNil, SubscriptionPlanHelper.SaveFields(
            plan: "plus",
            monthlyPriceUsd: nil,
            anchorDay: 1
        ))

        // Decimal list price (e.g. Google AI Pro $19.99)
        let ultraPlan = KnownPlan(key: "google_ai_pro", label: "Google AI Pro", monthlyPriceUsd: 19.99)
        let fieldsDecimal = SubscriptionPlanHelper.fieldsToSave(
            planKey: "google_ai_pro",
            enteredPrice: 19.99,
            anchorDay: 8,
            knownPlan: ultraPlan
        )
        XCTAssertEqual(fieldsDecimal, SubscriptionPlanHelper.SaveFields(
            plan: "google_ai_pro",
            monthlyPriceUsd: nil,
            anchorDay: 8
        ))
    }

    func testHelperOverridePriceSavesEnteredPrice() {
        let plan = KnownPlan(key: "plus", label: "ChatGPT Plus", monthlyPriceUsd: 20.0)

        // User overrides list price 20.0 with 15.0
        let fieldsOverride = SubscriptionPlanHelper.fieldsToSave(
            planKey: "plus",
            enteredPrice: 15.0,
            anchorDay: 8,
            knownPlan: plan
        )
        XCTAssertEqual(fieldsOverride, SubscriptionPlanHelper.SaveFields(
            plan: "plus",
            monthlyPriceUsd: 15.0,
            anchorDay: 8
        ))

        // Known plan without list price (monthlyPriceUsd is nil) -> price must be saved
        let unpricedPlan = KnownPlan(key: "premium_plus", label: "X Premium+", monthlyPriceUsd: nil)
        let fieldsUnpriced = SubscriptionPlanHelper.fieldsToSave(
            planKey: "premium_plus",
            enteredPrice: 25.0,
            anchorDay: 10,
            knownPlan: unpricedPlan
        )
        XCTAssertEqual(fieldsUnpriced, SubscriptionPlanHelper.SaveFields(
            plan: "premium_plus",
            monthlyPriceUsd: 25.0,
            anchorDay: 10
        ))
    }

    func testHelperCustomPlanAlwaysSavesPrice() {
        // Custom plan (nil knownPlan)
        let fieldsCustom = SubscriptionPlanHelper.fieldsToSave(
            planKey: "custom_enterprise_plan",
            enteredPrice: 150.0,
            anchorDay: 28,
            knownPlan: nil
        )
        XCTAssertEqual(fieldsCustom, SubscriptionPlanHelper.SaveFields(
            plan: "custom_enterprise_plan",
            monthlyPriceUsd: 150.0,
            anchorDay: 28
        ))

        // Custom plan with whitespace
        let fieldsWhitespace = SubscriptionPlanHelper.fieldsToSave(
            plan: "  my plan  ",
            isCustom: true,
            enteredPrice: 12.0,
            listPrice: nil,
            anchorDay: 5
        )
        XCTAssertEqual(fieldsWhitespace, SubscriptionPlanHelper.SaveFields(
            plan: "my plan",
            monthlyPriceUsd: 12.0,
            anchorDay: 5
        ))

        // Passing knownPlans list with isCustom = true ignores matches
        let plans = [KnownPlan(key: "plus", label: "ChatGPT Plus", monthlyPriceUsd: 20.0)]
        let fieldsCustomFlag = SubscriptionPlanHelper.fieldsToSave(
            planKey: "plus",
            isCustom: true,
            enteredPrice: 20.0,
            anchorDay: 8,
            knownPlans: plans
        )
        XCTAssertEqual(fieldsCustomFlag, SubscriptionPlanHelper.SaveFields(
            plan: "plus",
            monthlyPriceUsd: 20.0,
            anchorDay: 8
        ))
    }

    func testHelperLookupFromKnownPlansList() {
        let plans = [
            KnownPlan(key: "pro", label: "Claude Pro", monthlyPriceUsd: 20.0),
            KnownPlan(key: "max_5x", label: "Claude Max 5x", monthlyPriceUsd: 100.0),
        ]

        // List price match
        let listResult = SubscriptionPlanHelper.fieldsToSave(
            planKey: "pro",
            isCustom: false,
            enteredPrice: 20.0,
            anchorDay: 14,
            knownPlans: plans
        )
        XCTAssertEqual(listResult, SubscriptionPlanHelper.SaveFields(
            plan: "pro",
            monthlyPriceUsd: nil,
            anchorDay: 14
        ))

        // Override price match
        let overrideResult = SubscriptionPlanHelper.fieldsToSave(
            planKey: "max_5x",
            isCustom: false,
            enteredPrice: 80.0,
            anchorDay: 14,
            knownPlans: plans
        )
        XCTAssertEqual(overrideResult, SubscriptionPlanHelper.SaveFields(
            plan: "max_5x",
            monthlyPriceUsd: 80.0,
            anchorDay: 14
        ))

        // Unknown plan in list treated as custom
        let unknownResult = SubscriptionPlanHelper.fieldsToSave(
            planKey: "unknown_tier",
            isCustom: false,
            enteredPrice: 45.0,
            anchorDay: 14,
            knownPlans: plans
        )
        XCTAssertEqual(unknownResult, SubscriptionPlanHelper.SaveFields(
            plan: "unknown_tier",
            monthlyPriceUsd: 45.0,
            anchorDay: 14
        ))
    }
}
