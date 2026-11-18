import XCTest
@testable import KanjoCore

final class AntigravityAggregationTests: XCTestCase {
    private let known = KnownPlan.fallbackPlans["antigravity"] ?? []

    private func account(_ email: String, _ plan: AntigravityAccountPlan?) -> AntigravityAccount {
        AntigravityAccount(email: email, tokens: 0, costUsd: 0, messages: 0, plan: plan)
    }

    private let pro = AntigravityAccountPlan(plan: "google_ai_pro", planLabel: "Google AI Pro", monthlyPriceUsd: 19.99)

    func testAggregationMixedPlans() {
        let accounts = [
            account("a@test.com", AntigravityAccountPlan(plan: "pro", planLabel: "Pro", monthlyPriceUsd: 20.0)),
            account("b@test.com", AntigravityAccountPlan(plan: "pro", planLabel: "Pro", monthlyPriceUsd: 20.0)),
            account("c@test.com", AntigravityAccountPlan(plan: "ultra", planLabel: "Ultra", monthlyPriceUsd: 200.0)),
        ]
        let agg = AntigravityAggregation.aggregate(accounts: accounts)
        XCTAssertEqual(agg?.accountsPriced, 3)
        XCTAssertEqual(agg?.monthlyPriceUsd, 240.0)
        XCTAssertEqual(agg?.plan, "multi")
        XCTAssertEqual(agg?.planLabel, "Ultra + Pro ×2")
    }

    func testNoneAndMissingPlansDoNotCount() {
        let accounts = [
            account("a@test.com", AntigravityAccountPlan(plan: "none", planLabel: "None", monthlyPriceUsd: 0.0)),
            account("b@test.com", AntigravityAccountPlan(plan: "NONE", planLabel: "None", monthlyPriceUsd: 5.0)),
            account("c@test.com", nil),
        ]
        XCTAssertNil(AntigravityAggregation.aggregate(accounts: accounts))
    }

    func testPendingProProNone() {
        let accounts = [account("a@test.com", nil), account("b@test.com", nil), account("c@test.com", pro)]
        let pending = ["a@test.com": "google_ai_pro", "b@test.com": "google_ai_pro", "c@test.com": "none"]
        let applied = AntigravityAggregation.applyPending(accounts: accounts, pending: pending, knownPlans: known)
        let agg = AntigravityAggregation.aggregate(accounts: applied)
        XCTAssertEqual(agg?.planLabel, "Google AI Pro ×2")
        XCTAssertEqual(agg?.plan, "google_ai_pro")
        XCTAssertEqual(agg?.monthlyPriceUsd ?? 0, 39.98, accuracy: 1e-9)
        XCTAssertEqual(agg?.accountsPriced, 2)
    }

    func testPendingEmptyClearsPlan() {
        let accounts = [account("a@test.com", pro), account("b@test.com", pro)]
        let applied = AntigravityAggregation.applyPending(accounts: accounts, pending: ["a@test.com": ""],
                                                          knownPlans: known)
        XCTAssertNil(applied[0].plan)
        XCTAssertEqual(applied[1].plan, pro)
        XCTAssertEqual(AntigravityAggregation.aggregate(accounts: applied)?.planLabel, "Google AI Pro")
        let none = AntigravityAggregation.applyPending(accounts: accounts,
                                                       pending: ["a@test.com": "", "b@test.com": ""],
                                                       knownPlans: known)
        XCTAssertNil(AntigravityAggregation.aggregate(accounts: none))
    }

    func testPendingUsesKnownPlanLabelNotRawKey() {
        let accounts = [account("a@test.com", nil)]
        let applied = AntigravityAggregation.applyPending(accounts: accounts, pending: ["a@test.com": "google_ai_ultra"],
                                                          knownPlans: known)
        XCTAssertEqual(applied[0].plan?.planLabel, "Google AI Ultra")
        XCTAssertEqual(applied[0].plan?.monthlyPriceUsd, 249.99)
        let agg = AntigravityAggregation.aggregate(accounts: applied)
        XCTAssertEqual(agg?.planLabel, "Google AI Ultra")
        XCTAssertFalse(agg?.planLabel.contains("google_ai_ultra") ?? true)
    }

    func testPendingSameKeyKeepsReportedPlan() {
        // 报告里同一 key 可能带自定义价格，保留报告的值。
        let custom = AntigravityAccountPlan(plan: "google_ai_pro", planLabel: "Google AI Pro", monthlyPriceUsd: 9.99)
        let applied = AntigravityAggregation.applyPending(accounts: [account("a@test.com", custom)],
                                                          pending: ["a@test.com": "google_ai_pro"], knownPlans: known)
        XCTAssertEqual(applied[0].plan, custom)
    }

    func testRemainingPendingClearsOnlyWhenReportShowsPlan() {
        let pending = ["a@test.com": "google_ai_pro", "b@test.com": "", "c@test.com": "google_ai_pro", "d@test.com": ""]
        let report = [
            account("a@test.com", pro),
            account("b@test.com", AntigravityAccountPlan(plan: "none", planLabel: "None")),
            account("c@test.com", nil),
            account("d@test.com", nil),
        ]
        XCTAssertEqual(AntigravityAggregation.remainingPending(pending, report: report),
                       ["c@test.com": "google_ai_pro"])
    }

    func testRemainingPendingKeepsBusyAccounts() {
        let pending = ["a@test.com": "google_ai_pro", "b@test.com": "google_ai_pro"]
        let report = [account("a@test.com", pro), account("b@test.com", pro)]
        XCTAssertEqual(AntigravityAggregation.remainingPending(pending, report: report, busy: ["b@test.com"]),
                       ["b@test.com": "google_ai_pro"])
    }

    func testNormalizedPlanKey() {
        XCTAssertEqual(AntigravityAggregation.normalizedPlanKey(nil), "")
        XCTAssertEqual(AntigravityAggregation.normalizedPlanKey(" None "), "")
        XCTAssertEqual(AntigravityAggregation.normalizedPlanKey("google_ai_pro"), "google_ai_pro")
    }
}
